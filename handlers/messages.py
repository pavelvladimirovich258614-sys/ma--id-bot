"""
Обработчик входящих сообщений: стикеры, пересланные сообщения, каналы.

ВАЖНО: В maxapi dispatcher при регистрации нескольких обработчиков на одно
событие (message_created), если первый обработчик завершился без ошибки
(даже просто return), остальные не вызываются. Поэтому все обработчики
объединены в ОДИН.
"""
import logging
import time
from urllib.parse import urlparse, parse_qs

from maxapi.types import MessageCreated
from maxapi.types.attachments.sticker import Sticker
from maxapi.enums.parse_mode import ParseMode
from maxapi.enums.message_link_type import MessageLinkType
from keyboards.main_menu import dismiss_keyboard

logger = logging.getLogger(__name__)

# Кэш для get_chats() - TTL 60 секунд
_CHATS_CACHE_TTL = 60
_chats_cache = {'data': None, 'timestamp': 0}


async def _get_cached_chats(bot):
    """
    Получает список чатов с кэшированием.
    
    Args:
        bot: Экземпляр бота для вызова get_chats()
        
    Returns:
        Результат get_chats() - список чатов бота
    """
    global _chats_cache
    
    current_time = time.time()
    if _chats_cache['data'] is not None and \
       (current_time - _chats_cache['timestamp']) < _CHATS_CACHE_TTL:
        logger.debug("Using cached chats")
        return _chats_cache['data']
    
    # Кэш устарел или отсутствует - обновляем
    logger.info("Updating chats cache")
    chats_result = await bot.get_chats(count=100)
    _chats_cache['data'] = chats_result
    _chats_cache['timestamp'] = current_time
    return chats_result


def register_message_handler(dp):
    """
    Регистрирует обработчик для стикеров, пересланных сообщений и каналов.

    Args:
        dp: Dispatcher экземпляр для регистрации обработчиков
    """

    @dp.message_created()
    async def on_message(event: MessageCreated):
        """
        Обработчик события message_created.
        Проверяет: стикеры → пересылки → каналы/чаты по ссылке или ID.
        """
        try:
            message = event.message

            # Проверяем наличие body
            if not message or not message.body:
                return

            # === ПРОВЕРКА 1: СТИКЕРЫ ===
            attachments = getattr(message.body, 'attachments', None) or []

            if attachments:
                logger.info(f"Message received, attachments count: {len(attachments)}")

                # Ищем стикер среди вложений
                for attachment in attachments:
                    is_sticker = False

                    # Способ 1: isinstance (приоритетный)
                    if isinstance(attachment, Sticker):
                        is_sticker = True

                    # Способ 2: имя класса
                    elif attachment.__class__.__name__ == 'Sticker':
                        is_sticker = True

                    # Способ 3: строковое значение type
                    elif getattr(attachment, 'type', None) == 'sticker':
                        is_sticker = True

                    if is_sticker:
                        logger.info(f"Sticker detected from user {event.from_user.user_id}")
                        # Извлекаем код стикера
                        code = None
                        payload = getattr(attachment, 'payload', None)

                        # Способ 1: напрямую из payload.code
                        if payload:
                            code = getattr(payload, 'code', None)

                        # Способ 2: из самого attachment
                        if not code:
                            code = getattr(attachment, 'code', None)

                        # Способ 3: через __dict__
                        if not code and payload and hasattr(payload, '__dict__'):
                            code = payload.__dict__.get('code')

                        # Способ 4: парсим smileId из URL
                        # (payload приходит как OtherAttachmentPayload)
                        url = None
                        if payload:
                            url = getattr(payload, 'url', None)
                        if not url:
                            url = getattr(attachment, 'url', None)

                        if not code and url:
                            try:
                                parsed = urlparse(url)
                                params = parse_qs(parsed.query)
                                smile_id = params.get('smileId', [None])[0]
                                if smile_id:
                                    code = smile_id
                                    logger.info(f"Extracted smileId from URL: {code}")
                            except Exception as parse_err:
                                logger.warning(f"Failed to parse URL: {parse_err}")

                        # width и height — атрибуты класса Sticker
                        width = getattr(attachment, 'width', None)
                        height = getattr(attachment, 'height', None)

                        # Формируем HTML-ответ
                        if code:
                            text = (
                                f"🎟 <b>Информация о стикере:</b>\n\n"
                                f"<b>Код:</b> <code>{code}</code>"
                            )
                        else:
                            text = (
                                "🎟 <b>Информация о стикере:</b>\n\n"
                                "<i>Код недоступен</i>"
                            )

                        if url:
                            text += f'\n\n<b>Ссылка:</b> <a href="{url}">Открыть стикер</a>'

                        if width and height:
                            text += f"\n<b>Размер:</b> {width}×{height}"

                        text += "\n\nНажмите /start для возврата в главное меню"

                        await message.answer(
                            text=text,
                            parse_mode=ParseMode.HTML,
                            attachments=[dismiss_keyboard()]
                        )
                        return

            # === ПРОВЕРКА 2: ПЕРЕСЛАННЫЕ СООБЩЕНИЯ ===
            if message.link:
                link = message.link

                # Проверяем, что это пересланное сообщение (forward)
                link_type = getattr(link, 'type', None)
                is_forward = (
                    link_type == MessageLinkType.FORWARD
                    or link_type == 'forward'
                )

                if is_forward:
                    link_chat_id = getattr(link, 'chat_id', None)
                    link_sender = getattr(link, 'sender', None)

                    logger.info(
                        f"Forward: chat_id={link_chat_id}, "
                        f"sender={link_sender.user_id if link_sender else None}"
                    )

                    # СНАЧАЛА проверяем chat_id — показываем информацию о чате
                    if link_chat_id:
                        try:
                            chat = await event.bot.get_chat_by_id(id=link_chat_id)

                            title = getattr(chat, 'title', None) or 'Без названия'
                            chat_type = getattr(chat, 'type', 'N/A')
                            chat_link = getattr(chat, 'link', None)
                            is_public = getattr(chat, 'is_public', False)
                            participants_count = getattr(
                                chat, 'participants_count', 'N/A'
                            )

                            if chat_link:
                                text = (
                                    f"📨 <b>Информация из пересланного "
                                    f"сообщения:</b>\n\n"
                                    f"<b>Chat ID:</b> "
                                    f"<code>{link_chat_id}</code>\n"
                                    f"<b>Название:</b> {title}\n"
                                    f"<b>Тип:</b> {chat_type}\n"
                                    f"<b>Ссылка:</b> {chat_link}\n"
                                    f"<b>Участников:</b> {participants_count}\n\n"
                                    f"Нажмите /start для возврата в главное меню"
                                )
                            else:
                                text = (
                                    f"📨 <b>Информация из пересланного "
                                    f"сообщения:</b>\n\n"
                                    f"<b>Chat ID:</b> "
                                    f"<code>{link_chat_id}</code>\n"
                                    f"<b>Название:</b> {title}\n"
                                    f"<b>Тип:</b> {chat_type}\n"
                                    f"<b>Участников:</b> {participants_count}\n"
                                    f"<b>Публичный:</b> "
                                    f"{'Да' if is_public else 'Нет'}\n\n"
                                    f"Нажмите /start для возврата в главное меню"
                                )

                            await message.answer(
                                text=text,
                                parse_mode=ParseMode.HTML,
                                attachments=[dismiss_keyboard()]
                            )
                            # Удаляем оригинальное пересланное сообщение
                            if event.message and hasattr(event.message, 'delete'):
                                try:
                                    await event.message.delete()
                                    logger.info(f"Deleted original forwarded message")
                                except Exception as del_err:
                                    logger.warning(f"Could not delete original message: {del_err}")
                            return

                        except Exception as e:
                            logger.error(
                                f"Error getting chat info from forwarded message: "
                                f"{e}", exc_info=True
                            )
                            # Отправляем хотя бы сырой chat_id
                            text = (
                                f"📨 <b>Информация из пересланного "
                                f"сообщения:</b>\n\n"
                                f"<b>Chat ID:</b> "
                                f"<code>{link_chat_id}</code>\n"
                                f"<i>Бот не имеет доступа к этому чату. "
                                f"Для получения полной информации добавьте бота в этот чат.</i>\n\n"
                                f"Нажмите /start для возврата в главное меню"
                            )
                            await message.answer(
                                text=text,
                                parse_mode=ParseMode.HTML,
                                attachments=[dismiss_keyboard()]
                            )
                            # Удаляем оригинальное пересланное сообщение
                            if event.message and hasattr(event.message, 'delete'):
                                try:
                                    await event.message.delete()
                                    logger.info(f"Deleted original forwarded message")
                                except Exception as del_err:
                                    logger.warning(f"Could not delete original message: {del_err}")
                            return

                    # Если chat_id нет — показываем информацию об отправителе
                    if link_sender:
                        sender_id = getattr(link_sender, 'user_id', None)
                        first_name = getattr(link_sender, 'first_name', None) or ''
                        last_name = getattr(link_sender, 'last_name', None) or ''
                        username = getattr(link_sender, 'username', None)

                        full_name = f"{first_name} {last_name}".strip()
                        username_display = (
                            f"@{username}" if username else "не задан"
                        )

                        text = (
                            f"👤 <b>Информация об отправителе:</b>\n\n"
                            f"<b>User ID:</b> <code>{sender_id}</code>\n"
                            f"<b>Имя:</b> {full_name}\n"
                            f"<b>Ник:</b> {username_display}\n\n"
                            f"Нажмите /start для возврата в главное меню"
                        )

                        await message.answer(
                            text=text,
                            parse_mode=ParseMode.HTML,
                            attachments=[dismiss_keyboard()]
                        )
                        # Удаляем оригинальное пересланное сообщение
                        if event.message and hasattr(event.message, 'delete'):
                            try:
                                await event.message.delete()
                                logger.info(f"Deleted original forwarded message")
                            except Exception as del_err:
                                logger.warning(f"Could not delete original message: {del_err}")
                        return

                    # Ни chat_id, ни sender не найдены
                    await message.answer(
                        text="❌ Не удалось определить информацию "
                             "из пересланного сообщения.\n\n"
                             "Нажмите /start для возврата в главное меню",
                        parse_mode=ParseMode.HTML,
                        attachments=[dismiss_keyboard()]
                    )
                    return

            # === ПРОВЕРКА 3: КАНАЛ/ЧАТ ПО ССЫЛКЕ ИЛИ ID ===
            text = getattr(message.body, 'text', None) or ''
            text = text.strip()

            if text:
                chat_info = None
                search_query = None
                search_by_id = None

                # Определяем тип запроса
                if 'max.ru/' in text or text.startswith('@'):
                    # Извлекаем ник из ссылки
                    search_query = text
                    if 'max.ru/' in text:
                        search_query = text.split('/')[-1].strip()
                    if search_query.startswith('@'):
                        search_query = search_query[1:]
                    logger.info(f"Searching channel by username: {search_query}")
                else:
                    # Пробуем как числовой ID
                    try:
                        search_by_id = int(text)
                        logger.info(f"Searching chat by ID: {search_by_id}")
                    except ValueError:
                        pass

                # Если есть что искать
                if search_query or search_by_id is not None:
                    # ШАГ 1: Пробуем прямые методы API
                    try:
                        if search_query:
                            chat_info = await event.bot.get_chat_by_link(link=search_query)
                        elif search_by_id is not None:
                            chat_info = await event.bot.get_chat_by_id(id=search_by_id)
                    except Exception as e:
                        logger.warning(f"Direct API method failed: {e}")
                        chat_info = None

                    # ШАГ 2: Если не сработало — ищем среди чатов бота
                    if chat_info is None:
                        try:
                            logger.info("Trying to find in bot's chats via get_chats()")
                            chats_result = await _get_cached_chats(event.bot)
                            chats_list = getattr(chats_result, 'chats', []) or []
                            logger.info(f"Got {len(chats_list)} chats from get_chats()")

                            for chat in chats_list:
                                # Проверяем совпадение по ID
                                if search_by_id is not None:
                                    chat_chat_id = getattr(chat, 'chat_id', None)
                                    if chat_chat_id == search_by_id:
                                        chat_info = chat
                                        logger.info(f"Found chat by ID in get_chats()")
                                        break

                                # Проверяем совпадение по нику в link
                                if search_query:
                                    chat_link = getattr(chat, 'link', '') or ''
                                    chat_title = getattr(chat, 'title', '') or ''
                                    chat_chat_id_str = str(getattr(chat, 'chat_id', ''))

                                    # Ник в ссылке канала
                                    if search_query.lower() in chat_link.lower():
                                        chat_info = chat
                                        logger.info(f"Found chat by link match: {chat_link}")
                                        break

                                    # Частичное совпадение по названию
                                    if search_query.lower() in chat_title.lower():
                                        chat_info = chat
                                        logger.info(f"Found chat by title match: {chat_title}")
                                        break

                                    # Проверка если chat_id содержит ник (для некоторых каналов)
                                    if search_query in chat_chat_id_str:
                                        chat_info = chat
                                        logger.info(f"Found chat by chat_id match")
                                        break

                        except Exception as e:
                            logger.error(f"Error in get_chats(): {e}", exc_info=True)

                    # Если нашли — формируем ответ
                    if chat_info:
                        chat_id = getattr(chat_info, 'chat_id', None)
                        title = getattr(chat_info, 'title', 'Без названия')
                        chat_type = getattr(chat_info, 'type', 'N/A')
                        is_public = getattr(chat_info, 'is_public', False)
                        chat_link = getattr(chat_info, 'link', None)
                        participants_count = getattr(chat_info, 'participants_count', 'N/A')
                        description = getattr(chat_info, 'description', None)

                        response_text = f"📣 <b>Информация о канале/чате:</b>\n\n"
                        if chat_id:
                            response_text += f"<b>Chat ID:</b> <code>{chat_id}</code>\n"
                        response_text += f"<b>Название:</b> {title}\n"
                        response_text += f"<b>Тип:</b> {chat_type}\n"
                        if chat_link:
                            response_text += f"<b>Ссылка:</b> {chat_link}\n"
                        response_text += f"<b>Участников:</b> {participants_count}\n"
                        response_text += f"<b>Публичный:</b> {'Да' if is_public else 'Нет'}\n"
                        if description:
                            response_text += f"<b>Описание:</b> {description}\n"
                        response_text += "\nНажмите /start для возврата в главное меню"

                        await message.answer(
                            text=response_text,
                            parse_mode=ParseMode.HTML,
                            attachments=[dismiss_keyboard()]
                        )
                        return

                    # Не нашли — показываем fallback
                    await message.answer(
                        text="❌ Канал или чат не найден.\n\n"
                             "Возможные причины:\n"
                             "• Канал приватный и бот не добавлен\n"
                             "• Ссылка некорректная\n"
                             "• Бот не является участником канала\n\n"
                             "<i>Для приватных каналов добавьте бота администратором — "
                             "информация придёт автоматически.</i>\n\n"
                             "Нажмите /start для возврата в главное меню",
                        parse_mode=ParseMode.HTML,
                        attachments=[dismiss_keyboard()]
                    )
                    return

            # Ничего не подошло — тихо возвращаем управление
            return

        except Exception as e:
            # Логируем ошибку, но НЕ отвечаем пользователю
            logger.error(f"Error in message handler: {e}", exc_info=True)

    logger.info("Message handler registered")
