"""
Обработчики нажатий на inline-кнопки.
"""
import asyncio
import logging
import re
import time

from maxapi.types import MessageCallback

from keyboards.main_menu import WELCOME_TEXT, id_harvest_keyboard, main_menu_keyboard
from middleware.subscription import require_subscription

from handlers.admin import route_admin_callback

logger = logging.getLogger(__name__)

_last_callback = {}
CALLBACK_DUPLICATE_TIMEOUT = 2
HARVEST_STATE_TTL = 600

WAITING_FOR_LINK = "WAITING_FOR_LINK"
WAITING_FOR_FORWARD = "WAITING_FOR_FORWARD"
_harvest_states = {}


def set_harvest_state(
    user_id: int,
    state: str,
    *,
    instruction_message_id: str | None = None,
    result_chat_id: int | None = None,
) -> None:
    """Сохраняет режим ожидания для пользователя."""
    _harvest_states[int(user_id)] = {
        "state": state,
        "instruction_message_id": instruction_message_id,
        "result_chat_id": result_chat_id,
        "timestamp": time.time(),
    }


def get_harvest_state(user_id: int) -> str | None:
    """Возвращает активный режим ожидания пользователя."""
    state_data = _harvest_states.get(int(user_id))
    if not state_data:
        return None

    if time.time() - state_data["timestamp"] > HARVEST_STATE_TTL:
        _harvest_states.pop(int(user_id), None)
        return None

    return state_data["state"]


def get_harvest_state_data(user_id: int) -> dict | None:
    """Возвращает активное состояние разведки вместе с metadata."""
    state_data = _harvest_states.get(int(user_id))
    if not state_data:
        return None

    if time.time() - state_data["timestamp"] > HARVEST_STATE_TTL:
        _harvest_states.pop(int(user_id), None)
        return None

    return state_data


def clear_harvest_state(user_id: int) -> None:
    """Очищает режим ожидания пользователя."""
    _harvest_states.pop(int(user_id), None)


def resolve_channel_link_fallback(url):
    """
    Возвращает username канала из ссылки, сохраняя старую логику разбора.

    Args:
        url: Ссылка, username или ID канала.
    """
    m = re.search(r'max\.ru/(id\d+_biz)', url)
    if m:
        return m.group(1)

    if 'max.ru/' in url:
        return url.split('/')[-1].strip()

    if url.startswith('@'):
        return url[1:]

    return url.strip()


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


def _get_message_identifier(message) -> str | None:
    """Достает ID сообщения из SDK-объекта MAX."""
    value = _get_field(message, "message_id", "messageId", "id", "mid")
    return str(value) if value is not None else None


async def _answer_callback(event, notification: str = "✅ Готово") -> None:
    """Отвечает на callback, чтобы кнопка не зависала в клиенте."""
    try:
        await event.bot.send_callback(
            callback_id=event.callback.callback_id,
            notification=notification,
        )
    except Exception as error:
        logger.warning(f"Failed to answer callback: {error}")


async def _delete_callback_message(event) -> str:
    """Удаляет сообщение с кнопкой, если SDK и права это позволяют."""
    try:
        if event.message and hasattr(event.message, "delete"):
            await event.message.delete()
            return "Удалено"
        return "Сообщение недоступно"
    except Exception as error:
        logger.warning(f"Could not delete callback message: {error}")
        return "Уже удалено"


def _chat_id_from_callback(event) -> int | None:
    recipient = getattr(event.message, "recipient", None)
    chat_id = getattr(recipient, "chat_id", None) if recipient else None
    return chat_id or getattr(event, "chat_id", None)


def register_callback_handlers(dp):
    """
    Регистрирует обработчики для callback кнопок.

    Args:
        dp: Dispatcher экземпляр для регистрации обработчиков.
    """

    @dp.message_callback()
    @require_subscription
    async def on_callback(event: MessageCallback):
        payload = None
        try:
            payload = event.callback.payload
            user = event.callback.user
            chat_id = _chat_id_from_callback(event)

            logger.info(
                f"Callback received: payload={payload}, user={user.user_id}"
            )

            is_duplicate = False
            if chat_id:
                current_time = time.time()
                last_data = _last_callback.get(chat_id)
                if last_data:
                    last_payload, last_time = last_data
                    is_duplicate = (
                        last_payload == payload
                        and current_time - last_time < CALLBACK_DUPLICATE_TIMEOUT
                    )
                _last_callback[chat_id] = (payload, current_time)

            if payload == "dismiss":
                notification = await _delete_callback_message(event)
                await _answer_callback(event, notification)
                return

            text = None
            response_keyboard = main_menu_keyboard()

            if payload == "get_user_id":
                first_name = getattr(user, 'first_name', '') or ''
                last_name = getattr(user, 'last_name', None) or ''
                username = getattr(user, 'username', None)
                full_name = f"{first_name} {last_name}".strip()
                username_display = f"@{username}" if username else "не задан"
                text = (
                    "👤 Информация о вас:\n\n"
                    f"User ID: {user.user_id}\n"
                    f"Имя: {full_name}\n"
                    f"Ник: {username_display}\n\n"
                    "Чтобы узнать ID другого пользователя — перешлите "
                    "мне любое его сообщение.\n\n"
                    "Нажмите /start для возврата в главное меню"
                )

            elif payload == "get_bot_id":
                me = event.bot.me
                if me is None:
                    me = await event.bot.get_me()
                bot_id = getattr(me, 'user_id', 'N/A')
                bot_name = getattr(me, 'first_name', 'N/A')
                bot_username = getattr(me, 'username', None)
                description = getattr(me, 'description', None)
                username_display = (
                    f"@{bot_username}" if bot_username else "не задан"
                )
                desc_display = description if description else "отсутствует"
                text = (
                    "🤖 Информация о боте:\n\n"
                    f"Bot ID: {bot_id}\n"
                    f"Имя: {bot_name}\n"
                    f"Ник: {username_display}\n"
                    f"Описание: {desc_display}\n\n"
                    "Нажмите /start для возврата в главное меню"
                )

            elif payload == "get_chat_id":
                text = (
                    "💬 Получить ID группового чата\n\n"
                    "Есть два способа:\n\n"
                    "1️⃣ Пересылка сообщения:\n"
                    "Перешлите мне любое сообщение из нужного чата, "
                    "и я покажу его ID.\n\n"
                    "2️⃣ Добавление бота:\n"
                    "Добавьте меня в групповой чат — я автоматически "
                    "отправлю ID чата при добавлении.\n\n"
                    "Нажмите /start для возврата в главное меню"
                )

            elif payload == "get_channel_id":
                text = (
                    "📣 Получить ID канала\n\n"
                    "Отправьте мне ссылку на канал, например "
                    "https://max.ru/channel_name или @channel_name. "
                    "Также можно отправить числовой ID канала.\n\n"
                    "Для приватных каналов добавьте бота администратором, "
                    "и я автоматически пришлю ID.\n\n"
                    "Нажмите /start для возврата в главное меню"
                )

            elif payload == "get_sticker_info":
                text = (
                    "🎟 Получить информацию о стикере\n\n"
                    "Просто отправьте мне любой стикер, "
                    "и я покажу его код, прямую ссылку и размеры.\n\n"
                    "Нажмите /start для возврата в главное меню"
                )

            elif payload == "harvest_menu":
                clear_harvest_state(user.user_id)
                response_keyboard = id_harvest_keyboard()
                text = (
                    "🔍 Разведка ID\n\n"
                    "Выберите способ поиска идентификатора:\n\n"
                    "🆔 ID по ссылке — пришлите ссылку MAX, "
                    "я найду ID чата или канала.\n"
                    "✉️ ID по сообщению — перешлите сообщение, "
                    "я покажу ID отправителя.\n"
                    "🤖 ID этого бота — покажу мой текущий Bot ID."
                )

            elif payload == "harvest_bot_id":
                clear_harvest_state(user.user_id)
                response_keyboard = id_harvest_keyboard()
                me = event.bot.me
                if me is None:
                    me = await event.bot.get_me()
                bot_id = getattr(me, 'user_id', 'N/A')
                bot_name = getattr(me, 'first_name', 'N/A')
                bot_username = getattr(me, 'username', None)
                username_display = (
                    f"@{bot_username}" if bot_username else "не задан"
                )
                text = (
                    "🤖 ID этого бота\n\n"
                    f"Bot ID: {bot_id}\n"
                    f"Имя: {bot_name}\n"
                    f"Ник: {username_display}"
                )

            elif payload == "harvest_by_link":
                set_harvest_state(
                    user.user_id,
                    WAITING_FOR_LINK,
                    instruction_message_id=_get_message_identifier(event.message),
                    result_chat_id=chat_id,
                )
                response_keyboard = id_harvest_keyboard()
                text = (
                    "🆔 ID по ссылке\n\n"
                    "Пришлите ссылку на канал/чат MAX.\n\n"
                    "Пример: https://max.ru/channel_name"
                )

            elif payload == "harvest_by_message":
                set_harvest_state(
                    user.user_id,
                    WAITING_FOR_FORWARD,
                    instruction_message_id=_get_message_identifier(event.message),
                    result_chat_id=chat_id,
                )
                response_keyboard = id_harvest_keyboard()
                text = (
                    "✉️ ID по сообщению\n\n"
                    "Перешлите сообщение пользователя или бота, "
                    "чей ID нужно узнать."
                )

            elif payload == "harvest_back":
                clear_harvest_state(user.user_id)
                response_keyboard = main_menu_keyboard()
                text = WELCOME_TEXT

            elif payload == "subscription_retry":
                clear_harvest_state(user.user_id)
                response_keyboard = main_menu_keyboard()
                text = WELCOME_TEXT

            elif payload and isinstance(payload, str) and payload.startswith("admin_"):
                # Ровно один маршрут для admin_* callback: делегируем
                # в handlers/admin.py. handle_admin_callback сам отвечает
                # на callback и редактирует сообщение.
                await route_admin_callback(event)
                return

            else:
                logger.warning(f"Unknown callback payload: {payload}")
                text = (
                    "❌ Неизвестная команда\n\n"
                    "Нажмите /start для возврата в главное меню"
                )

            if is_duplicate:
                await _answer_callback(event)
                return

            if text and event.message:
                results = await asyncio.gather(
                    event.message.edit(
                        text=text,
                        attachments=[response_keyboard],
                    ),
                    event.bot.send_callback(
                        callback_id=event.callback.callback_id,
                        notification="✅ Готово",
                    ),
                    return_exceptions=True,
                )
                if isinstance(results[0], Exception):
                    logger.warning(f"Failed to edit callback message: {results[0]}")
                    recipient = getattr(event.message, "recipient", None)
                    if recipient:
                        await event.bot.send_message(
                            chat_id=recipient.chat_id,
                            text=text,
                            attachments=[response_keyboard],
                        )
                if isinstance(results[1], Exception):
                    logger.warning(f"Failed to answer callback: {results[1]}")

        except Exception as error:
            logger.error(f"Error in callback handler: {error}", exc_info=True)
            await _answer_callback(event, "Ошибка")

    logger.info("Callback handlers registered")
