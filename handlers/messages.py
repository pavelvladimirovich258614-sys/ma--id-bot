"""
Обработчик входящих сообщений: стикеры, пересланные сообщения, каналы.

ВАЖНО: В maxapi dispatcher при регистрации нескольких обработчиков на одно
событие (message_created), если первый обработчик завершился без ошибки
(даже просто return), остальные не вызываются. Поэтому все обработчики
объединены в ОДИН.
"""
import asyncio
import logging
import re
import time
from urllib.parse import parse_qs, urlparse

from maxapi.enums.message_link_type import MessageLinkType
from maxapi.types import MessageCreated
from maxapi.types.attachments.sticker import Sticker

from config import CHANNEL_CHAT_ID, CHANNEL_ID, CHANNEL_LINK
from database.postgres_storage import save_discovered_entity
from handlers.callbacks import (
    WAITING_FOR_FORWARD,
    WAITING_FOR_LINK,
    clear_harvest_state,
    get_harvest_state,
    resolve_channel_link_fallback,
)
from keyboards.main_menu import dismiss_keyboard, id_harvest_keyboard
from middleware.subscription import require_subscription

from handlers.admin import route_admin_message

logger = logging.getLogger(__name__)

_CHATS_CACHE_TTL = 60
_chats_cache = {'data': None, 'timestamp': 0}
MAX_LINK_RE = re.compile(
    r"""
    ^\s*
    (?:https?://)?
    (?:www\.)?
    max\.ru/
    (?P<slug>[A-Za-z0-9][A-Za-z0-9_.-]*)
    /?
    (?:[?#][^\s]*)?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _plain_text(value, fallback: str = "") -> str:
    """Готовит значение к выводу в MAX без HTML escaping."""
    text = str(value if value is not None else fallback)
    return re.sub(r"\s+", " ", text).strip()


def _is_chat_not_found_or_restricted(error: Exception) -> bool:
    """Проверяет, что MAX API ожидаемо не отдал чат или канал."""
    error_text = str(error).lower()
    return any(
        marker in error_text
        for marker in (
            "403",
            "404",
            "chat.not.found",
            "not found",
            "access",
            "forbidden",
            "restricted",
        )
    )


async def _delete_original_message(event: MessageCreated) -> None:
    """Удаляет исходное сообщение, если SDK и права это позволяют."""
    if event.message and hasattr(event.message, 'delete'):
        try:
            await event.message.delete()
            logger.info("Deleted original forwarded message")
        except Exception as error:
            logger.warning(f"Could not delete original message: {error}")


async def _send_feedback(message, text: str, attachments=None):
    """Отправляет пользователю ответ с кнопкой удаления."""
    if attachments is None:
        attachments = [dismiss_keyboard()]
    return await message.answer(
        text=text,
        attachments=attachments,
    )


def _get_field(source, *names):
    """Безопасно читает поле из объекта SDK или словаря."""
    if source is None:
        return None

    for name in names:
        if isinstance(source, dict) and name in source:
            return source.get(name)

        value = getattr(source, name, None)
        if value is not None:
            return value

    return None


def _nested_sources(source, max_depth: int = 2):
    """Возвращает объект и его вложенные SDK/dict-поля для поиска ID."""
    if source is None:
        return

    seen = set()
    queue = [(source, 0)]
    while queue:
        current, depth = queue.pop(0)
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        yield current

        if depth >= max_depth:
            continue

        if isinstance(current, dict):
            values = current.values()
        elif hasattr(current, '__dict__'):
            values = vars(current).values()
        else:
            continue

        for value in values:
            if isinstance(value, (str, int, float, bool, type(None))):
                continue
            queue.append((value, depth + 1))


def _get_deep_field(*sources, names: tuple[str, ...]):
    """Ищет первое непустое поле в нескольких вложенных источниках."""
    for source in sources:
        for nested_source in _nested_sources(source):
            value = _get_field(nested_source, *names)
            if value is not None:
                return value
    return None


def _extract_max_link_slug(text: str) -> str | None:
    """Возвращает slug из валидной ссылки max.ru."""
    match = MAX_LINK_RE.fullmatch(text)
    if not match:
        return None
    return match.group('slug')


def _normalize_max_link(value: str) -> str | None:
    """Возвращает единый slug MAX-ссылки или None."""
    text = value.strip()
    if not text:
        return None

    text = re.sub(r"\s+", " ", text).strip()
    lowered = text.lower()

    if lowered.startswith("http://"):
        text = text[7:]
        lowered = text.lower()
    elif lowered.startswith("https://"):
        text = text[8:]
        lowered = text.lower()

    if lowered.startswith("www."):
        text = text[4:]
        lowered = text.lower()
    elif lowered.startswith("web."):
        text = text[4:]
        lowered = text.lower()

    if lowered.startswith("max.ru/"):
        text = text[7:]

    text = text.lstrip("/")

    if text.lower().startswith("@"):
        text = text[1:]

    if "#" in text:
        text = text.split("#", 1)[0]
    if "?" in text:
        text = text.split("?", 1)[0]
    text = text.rstrip("/")

    if not text:
        return None

    if MAX_LINK_RE.fullmatch("https://max.ru/" + text):
        return text
    if MAX_LINK_RE.fullmatch("max.ru/" + text):
        return text
    if MAX_LINK_RE.fullmatch("@" + text):
        return text
    if MAX_LINK_RE.fullmatch(text):
        return text
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", text):
        return text

    return None


def _is_forward_link_type(link_type) -> bool:
    """Проверяет, что link.type соответствует пересланному сообщению."""
    if link_type == MessageLinkType.FORWARD:
        return True

    value = getattr(link_type, 'value', link_type)
    return str(value).lower() == 'forward'


def _sender_entity_type(sender, link) -> str:
    """Определяет тип отправителя пересланного сообщения."""
    is_bot = (
        _get_deep_field(sender, link, names=('is_bot', 'bot', 'isBot'))
        or False
    )
    if is_bot:
        return "bot"

    sender_type = _get_deep_field(
        sender,
        link,
        names=(
            'type',
            'entity_type',
            'sender_type',
            'from_type',
            'user_type',
            'kind',
        ),
    )
    if sender_type and "bot" in str(sender_type).lower():
        return "bot"

    username = _get_deep_field(sender, link, names=('username', 'login'))
    if username and str(username).lower().endswith('_bot'):
        return "bot"

    class_names = (
        sender.__class__.__name__ if sender is not None else "",
        link.__class__.__name__ if link is not None else "",
    )
    if any("bot" in class_name.lower() for class_name in class_names):
        return "bot"

    return "user"


def _schedule_discovered_entity_save(
    *,
    entity_id,
    entity_type: str,
    discovered_by_user_id: int,
) -> None:
    """Ставит сохранение найденного ID в фон, не задерживая ответ."""
    if not entity_id:
        return

    asyncio.create_task(
        save_discovered_entity(
            entity_id=str(entity_id),
            entity_type=entity_type,
            discovered_by_user_id=discovered_by_user_id,
        )
    )


def _extract_forward_sender(message) -> dict | None:
    """Извлекает отправителя из пересланного сообщения MAX."""
    link = _get_field(message, 'link')
    if not link or not _is_forward_link_type(_get_field(link, 'type')):
        return None

    sender = _get_deep_field(
        link,
        names=('sender', 'from_user', 'user', 'author'),
    )
    sender_id = _get_deep_field(
        sender,
        link,
        message,
        names=(
            'user_id',
            'sender_id',
            'from_id',
            'bot_id',
            'author_id',
            'owner_id',
            'id',
        ),
    )
    if not sender_id:
        return None

    first_name = _get_deep_field(
        sender,
        link,
        names=('first_name', 'name', 'title'),
    ) or ''
    last_name = _get_deep_field(sender, link, names=('last_name',)) or ''
    username = _get_deep_field(sender, link, names=('username', 'login'))

    return {
        "sender_id": sender_id,
        "entity_type": _sender_entity_type(sender, link),
        "full_name": f"{first_name} {last_name}".strip() or "не указано",
        "username": f"@{username}" if username else "не задан",
    }


async def _get_cached_chats(bot):
    """Получает список чатов с кэшированием."""
    global _chats_cache

    current_time = time.time()
    if (
        _chats_cache['data'] is not None
        and current_time - _chats_cache['timestamp'] < _CHATS_CACHE_TTL
    ):
        logger.debug("Using cached chats")
        return _chats_cache['data']

    logger.info("Updating chats cache")
    chats_result = await bot.get_chats(count=100)
    _chats_cache['data'] = chats_result
    _chats_cache['timestamp'] = current_time
    return chats_result


async def _handle_harvest_link(
    event: MessageCreated,
    message,
    text: str,
) -> bool:
    """Обрабатывает режим разведки ID по ссылке MAX."""
    await _delete_original_message(event)
    search_query = _normalize_max_link(text)
    if not search_query:
        await _send_feedback(
            message,
            "❌ Это не похоже на ссылку MAX.\n\n"
            "Пришлите ссылку в формате https://max.ru/channel_name.",
        )
        return True

    chat_info = None
    try:
        channel_slug = _normalize_max_link(CHANNEL_LINK)
        channel_id_slug = _normalize_max_link(CHANNEL_ID) if CHANNEL_ID else None

        input_slug = search_query
        matched_slugs = {
            slug
            for slug in (channel_id_slug, channel_slug)
            if isinstance(slug, str) and slug
        }

        if matched_slugs and input_slug.casefold() in {slug.casefold() for slug in matched_slugs}:
            if CHANNEL_CHAT_ID:
                chat_info = type("Chat", (), {})()
                chat_info.chat_id = CHANNEL_CHAT_ID
                chat_info.title = "Канал"
                chat_info.type = "chat"
                chat_info.link = CHANNEL_LINK

        if chat_info is None:
            chat_info = await event.bot.get_chat_by_link(link=search_query)
    except Exception as error:
        if _is_chat_not_found_or_restricted(error):
            logger.warning(
                "Harvest link lookup did not find accessible object: "
                f"link={text}; query={search_query}; error={error}"
            )
            response_text = (
                "❌ MAX API не смог определить ID по этой публичной ссылке.\n\n"
                "Попробуйте один из надёжных способов:"
                "\n• перешлите сообщение из канала или чата;"
                "\n• добавьте бота в чат или канал;"
                "\n• используйте «ID по сообщению»."
            )
            await _send_feedback(
                message,
                response_text,
                attachments=[id_harvest_keyboard()],
            )
            return True
        logger.error(
            "Unexpected harvest link lookup error: "
            f"link={text}; query={search_query}; error={error}",
            exc_info=True,
        )
        await _send_feedback(
            message,
            "❌ Не удалось получить данные объекта из-за временной ошибки API.",
        )
        return True

    chat_id = _get_field(chat_info, 'chat_id', 'id')
    title = _plain_text(_get_field(chat_info, 'title'), "Без названия")
    chat_type = _plain_text(_get_field(chat_info, 'type'), "N/A")
    chat_link = _get_field(chat_info, 'link')

    clear_harvest_state(event.from_user.user_id)
    _schedule_discovered_entity_save(
        entity_id=chat_id,
        entity_type="chat",
        discovered_by_user_id=event.from_user.user_id,
    )
    response_text = (
        "🆔 ID по ссылке\n\n"
        f"Название: {title}\n"
        f"ID: {chat_id}\n"
        f"Тип: {chat_type}"
    )
    if chat_link:
        response_text += f"\nСсылка: {_plain_text(chat_link)}"

    await _send_feedback(message, response_text)
    return True


async def _handle_harvest_forward(
    event: MessageCreated,
    message,
) -> bool:
    """Обрабатывает режим разведки ID по пересланному сообщению."""
    sender_data = _extract_forward_sender(message)
    if not sender_data:
        await _send_feedback(
            message,
            "❌ Пожалуйста, перешлите именно сообщение от другого "
            "пользователя или бота.",
        )
        return True

    clear_harvest_state(event.from_user.user_id)
    await _delete_original_message(event)
    _schedule_discovered_entity_save(
        entity_id=sender_data["sender_id"],
        entity_type=sender_data["entity_type"],
        discovered_by_user_id=event.from_user.user_id,
    )
    await _send_feedback(
        message,
        "✉️ ID по сообщению\n\n"
        f"Sender ID: {sender_data['sender_id']}\n"
        f"Тип: {'Бот' if sender_data['entity_type'] == 'bot' else 'Пользователь'}\n"
        f"Имя: {_plain_text(sender_data['full_name'])}\n"
        f"Ник: {_plain_text(sender_data['username'])}",
    )
    return True


async def _handle_sticker(event: MessageCreated, message, attachments) -> bool:
    """Показывает информацию о первом стикере в сообщении."""
    for attachment in attachments:
        is_sticker = (
            isinstance(attachment, Sticker)
            or attachment.__class__.__name__ == 'Sticker'
            or getattr(attachment, 'type', None) == 'sticker'
        )
        if not is_sticker:
            continue

        logger.info(f"Sticker detected from user {event.from_user.user_id}")
        payload = getattr(attachment, 'payload', None)
        code = getattr(payload, 'code', None) if payload else None
        code = code or getattr(attachment, 'code', None)
        if not code and payload and hasattr(payload, '__dict__'):
            code = payload.__dict__.get('code')

        url = getattr(payload, 'url', None) if payload else None
        url = url or getattr(attachment, 'url', None)
        if not code and url:
            try:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                smile_id = params.get('smileId', [None])[0]
                if smile_id:
                    code = smile_id
                    logger.info(f"Extracted smileId from URL: {code}")
            except Exception as error:
                logger.warning(f"Failed to parse sticker URL: {error}")

        width = getattr(attachment, 'width', None)
        height = getattr(attachment, 'height', None)
        text = "🎟 Информация о стикере:\n\n"
        text += f"Код: {code}" if code else "Код недоступен"
        if url:
            text += f"\n\nСсылка: {url}"
        if width and height:
            text += f"\nРазмер: {width}×{height}"
        text += "\n\nНажмите /start для возврата в главное меню"

        await _send_feedback(message, text)
        return True
    return False


async def _handle_forward(event: MessageCreated, message) -> bool:
    """Показывает ID из пересланного сообщения."""
    if not getattr(message, 'link', None):
        return False

    link = message.link
    if not _is_forward_link_type(getattr(link, 'type', None)):
        return False

    link_chat_id = getattr(link, 'chat_id', None)
    link_sender = getattr(link, 'sender', None)
    logger.info(
        "Forward: chat_id=%s, sender=%s",
        link_chat_id,
        getattr(link_sender, 'user_id', None) if link_sender else None,
    )

    if link_chat_id:
        try:
            chat = await event.bot.get_chat_by_id(id=link_chat_id)
            title = getattr(chat, 'title', None) or 'Без названия'
            chat_type = getattr(chat, 'type', 'N/A')
            chat_link = getattr(chat, 'link', None)
            is_public = getattr(chat, 'is_public', False)
            participants_count = getattr(chat, 'participants_count', 'N/A')

            text = (
                "📨 Информация из пересланного сообщения:\n\n"
                f"Chat ID: {link_chat_id}\n"
                f"Название: {title}\n"
                f"Тип: {chat_type}\n"
            )
            if chat_link:
                text += f"Ссылка: {chat_link}\n"
            text += (
                f"Участников: {participants_count}\n"
                f"Публичный: {'Да' if is_public else 'Нет'}\n\n"
                "Нажмите /start для возврата в главное меню"
            )
            await _send_feedback(message, text)
            await _delete_original_message(event)
            return True
        except Exception as error:
            if _is_chat_not_found_or_restricted(error):
                logger.warning(
                    "Forwarded chat is not available via MAX API: "
                    f"chat_id={link_chat_id}; error={error}"
                )
                reason = "Объект не найден или доступ ограничен."
            else:
                logger.error(
                    "Unexpected error getting chat info from forwarded message: "
                    f"{error}",
                    exc_info=True,
                )
                reason = "Не удалось получить данные объекта из-за временной ошибки API."

            await _send_feedback(
                message,
                "📨 Информация из пересланного сообщения:\n\n"
                f"Chat ID: {link_chat_id}\n"
                f"{reason}\n"
                "Для получения полной информации добавьте бота в этот чат "
                "или канал.\n\n"
                "Нажмите /start для возврата в главное меню",
            )
            await _delete_original_message(event)
            return True

    if link_sender:
        sender_id = getattr(link_sender, 'user_id', None)
        first_name = getattr(link_sender, 'first_name', None) or ''
        last_name = getattr(link_sender, 'last_name', None) or ''
        username = getattr(link_sender, 'username', None)
        full_name = f"{first_name} {last_name}".strip()
        username_display = f"@{username}" if username else "не задан"
        await _send_feedback(
            message,
            "👤 Информация об отправителе:\n\n"
            f"User ID: {sender_id}\n"
            f"Имя: {full_name}\n"
            f"Ник: {username_display}\n\n"
            "Нажмите /start для возврата в главное меню",
        )
        await _delete_original_message(event)
        return True

    await _send_feedback(
        message,
        "❌ Не удалось определить информацию из пересланного сообщения.\n\n"
        "Нажмите /start для возврата в главное меню",
    )
    return True


async def _handle_chat_lookup(event: MessageCreated, message, text: str) -> bool:
    """Показывает информацию о канале/чате по ссылке или ID."""
    chat_info = None
    search_query = None
    search_by_id = None

    if 'max.ru/' in text or text.startswith('@'):
        search_query = resolve_channel_link_fallback(text)
        logger.info(f"Searching channel by username: {search_query}")
    else:
        try:
            search_by_id = int(text)
            logger.info(f"Searching chat by ID: {search_by_id}")
        except ValueError:
            return False

    try:
        if search_query:
            chat_info = await event.bot.get_chat_by_link(link=search_query)
        elif search_by_id is not None:
            chat_info = await event.bot.get_chat_by_id(id=search_by_id)
    except Exception as error:
        if _is_chat_not_found_or_restricted(error):
            logger.warning(
                "Chat lookup did not find accessible object: "
                f"query={search_query or search_by_id}; error={error}"
            )
        else:
            logger.error(
                "Unexpected direct chat lookup error: "
                f"query={search_query or search_by_id}; error={error}",
                exc_info=True,
            )
        chat_info = None

    if chat_info is None:
        try:
            logger.info("Trying to find in bot's chats via get_chats()")
            chats_result = await _get_cached_chats(event.bot)
            chats_list = getattr(chats_result, 'chats', []) or []
            logger.info(f"Got {len(chats_list)} chats from get_chats()")

            for chat in chats_list:
                if search_by_id is not None:
                    chat_chat_id = getattr(chat, 'chat_id', None)
                    if chat_chat_id == search_by_id:
                        chat_info = chat
                        break

                if search_query:
                    chat_link = getattr(chat, 'link', '') or ''
                    chat_title = getattr(chat, 'title', '') or ''
                    chat_chat_id_str = str(getattr(chat, 'chat_id', ''))
                    if search_query.lower() in chat_link.lower():
                        chat_info = chat
                        break
                    if search_query.lower() in chat_title.lower():
                        chat_info = chat
                        break
                    if search_query in chat_chat_id_str:
                        chat_info = chat
                        break
        except Exception as error:
            logger.error(f"Error in get_chats(): {error}", exc_info=True)

    if chat_info:
        chat_id = getattr(chat_info, 'chat_id', None)
        title = getattr(chat_info, 'title', 'Без названия')
        chat_type = getattr(chat_info, 'type', 'N/A')
        is_public = getattr(chat_info, 'is_public', False)
        chat_link = getattr(chat_info, 'link', None)
        participants_count = getattr(chat_info, 'participants_count', 'N/A')
        description = getattr(chat_info, 'description', None)

        response_text = "📣 Информация о канале/чате:\n\n"
        if chat_id:
            response_text += f"Chat ID: {chat_id}\n"
        response_text += f"Название: {title}\n"
        response_text += f"Тип: {chat_type}\n"
        if chat_link:
            response_text += f"Ссылка: {chat_link}\n"
        response_text += f"Участников: {participants_count}\n"
        response_text += f"Публичный: {'Да' if is_public else 'Нет'}\n"
        if description:
            response_text += f"Описание: {description}\n"
        response_text += "\nНажмите /start для возврата в главное меню"

        await _send_feedback(message, response_text)
        return True

    await _send_feedback(
        message,
        "❌ Канал или чат не найден.\n\n"
        "Возможные причины:\n"
        "• Канал приватный и бот не добавлен\n"
        "• Ссылка некорректная\n"
        "• Бот не является участником канала\n\n"
        "Для приватных каналов добавьте бота администратором — "
        "информация придёт автоматически.\n\n"
        "Нажмите /start для возврата в главное меню",
    )
    return True


def register_message_handler(dp):
    """
    Регистрирует обработчик для стикеров, пересланных сообщений и каналов.

    Args:
        dp: Dispatcher экземпляр для регистрации обработчиков.
    """

    @dp.message_created()
    @require_subscription
    async def on_message(event: MessageCreated):
        """
        Обработчик события message_created.
        Проверяет: режим разведки → стикеры → пересылки → каналы/чаты.
        """
        try:
            message = event.message
            if not message or not message.body:
                return

            user_id = getattr(getattr(event, 'from_user', None), 'user_id', None)
            harvest_state = get_harvest_state(user_id) if user_id else None
            message_text = (getattr(message.body, 'text', None) or '').strip()

            # Админ-маршрутизация: активная админ-сессия обрабатывается
            # здесь и только здесь (один путь, без catch-all handler).
            if user_id and await route_admin_message(event):
                return

            if harvest_state == WAITING_FOR_LINK:
                await _handle_harvest_link(event, message, message_text)
                return

            if harvest_state == WAITING_FOR_FORWARD:
                await _handle_harvest_forward(event, message)
                return

            attachments = getattr(message.body, 'attachments', None) or []
            if attachments and await _handle_sticker(event, message, attachments):
                return

            if await _handle_forward(event, message):
                return

            if message_text and await _handle_chat_lookup(event, message, message_text):
                return

        except Exception as error:
            logger.error(f"Error in message handler: {error}", exc_info=True)
            try:
                await event.message.answer(
                    text=(
                        "❌ Внутренняя ошибка обработки сообщения.\n\n"
                        "Попробуйте повторить действие чуть позже."
                    ),
                    attachments=[dismiss_keyboard()],
                )
            except Exception:
                logger.exception("Could not notify user about message handler error")

    logger.info("Message handler registered")
