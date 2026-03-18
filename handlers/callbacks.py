"""
Обработчики нажатий на inline-кнопки (callback).
"""
import asyncio
import logging
import time
from maxapi.types import MessageCallback
from maxapi.enums.parse_mode import ParseMode
from keyboards.main_menu import main_menu_keyboard

logger = logging.getLogger(__name__)

# Защита от спама: храним последний callback для каждого чата
_last_callback = {}
CALLBACK_DUPLICATE_TIMEOUT = 2  # секунды


def register_callback_handlers(dp):
    """
    Регистрирует обработчики для callback кнопок.

    Args:
        dp: Dispatcher экземпляр для регистрации обработчиков
    """

    @dp.message_callback()
    async def on_callback(event: MessageCallback):
        """
        Обработчик всех callback событий.
        Обрабатывает нажатия на кнопки главного меню.
        Редактирует текущее сообщение вместо отправки нового.
        """
        payload = None
        try:
            payload = event.callback.payload
            user = event.callback.user
            chat_id = getattr(event.message, 'recipient', None)
            if chat_id:
                chat_id = getattr(chat_id, 'chat_id', None)
            if not chat_id:
                chat_id = getattr(event, 'chat_id', None)

            logger.info(
                f"Callback received: payload={payload}, "
                f"user={user.user_id}"
            )

            # Проверка на спам (дубликаты)
            is_duplicate = False
            if chat_id:
                current_time = time.time()
                last_data = _last_callback.get(chat_id)
                if last_data:
                    last_payload, last_time = last_data
                    if last_payload == payload and (current_time - last_time) < CALLBACK_DUPLICATE_TIMEOUT:
                        is_duplicate = True
                        logger.info(f"Duplicate callback detected for chat {chat_id}, payload={payload}")
                # Обновляем время последнего callback
                _last_callback[chat_id] = (payload, current_time)

            # === Обработка payload dismiss (удаление сообщения) ===
            if payload == "dismiss":
                try:
                    await event.message.delete()
                    logger.info(f"Message deleted by user {user.user_id}")
                    await event.bot.send_callback(
                        callback_id=event.callback.callback_id,
                        notification="Удалено"
                    )
                    return
                except Exception as delete_err:
                    logger.error(
                        f"Failed to delete message: {delete_err}", exc_info=True
                    )
                    await event.bot.send_callback(
                        callback_id=event.callback.callback_id,
                        notification="❌ Не удалось удалить"
                    )
                    return

            text = None

            # === Кнопка «Пользователь» ===
            if payload == "get_user_id":
                try:
                    first_name = getattr(user, 'first_name', '') or ''
                    last_name = getattr(user, 'last_name', None) or ''
                    username = getattr(user, 'username', None)

                    full_name = f"{first_name} {last_name}".strip()
                    username_display = (
                        f"@{username}" if username else "не задан"
                    )

                    text = (
                        f"👤 <b>Информация о вас:</b>\n\n"
                        f"<b>User ID:</b> <code>{user.user_id}</code>\n"
                        f"<b>Имя:</b> {full_name}\n"
                        f"<b>Ник:</b> {username_display}\n\n"
                        f"<i>Чтобы узнать ID другого пользователя — "
                        f"перешлите мне любое его сообщение.</i>\n\n"
                        f"Нажмите /start для возврата в главное меню"
                    )
                except Exception as e:
                    logger.error(
                        f"Error processing get_user_id: {e}", exc_info=True
                    )
                    text = "❌ Не удалось получить информацию о пользователе\n\nНажмите /start для возврата в главное меню"

            # === Кнопка «Бот» ===
            elif payload == "get_bot_id":
                try:
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
                        f"🤖 <b>Информация о боте:</b>\n\n"
                        f"<b>Bot ID:</b> <code>{bot_id}</code>\n"
                        f"<b>Имя:</b> {bot_name}\n"
                        f"<b>Ник:</b> {username_display}\n"
                        f"<b>Описание:</b> {desc_display}\n\n"
                        f"Нажмите /start для возврата в главное меню"
                    )
                except Exception as e:
                    logger.error(
                        f"Error processing get_bot_id: {e}", exc_info=True
                    )
                    text = "❌ Не удалось получить информацию о боте\n\nНажмите /start для возврата в главное меню"

            # === Кнопка «Чат» ===
            elif payload == "get_chat_id":
                text = (
                    "💬 <b>Получить ID группового чата</b>\n\n"
                    "Есть два способа:\n\n"
                    "1️⃣ <b>Пересылка сообщения:</b>\n"
                    "Перешлите мне любое сообщение из нужного чата, "
                    "и я покажу его ID.\n\n"
                    "2️⃣ <b>Добавление бота:</b>\n"
                    "Добавьте меня в групповой чат — я автоматически "
                    "отправлю ID чата при добавлении.\n\n"
                    "Нажмите /start для возврата в главное меню"
                )

            # === Кнопка «Канал» ===
            elif payload == "get_channel_id":
                text = (
                    "📣 <b>Получить ID канала</b>\n\n"
                    "Отправьте мне ссылку на канал (например "
                    "https://max.ru/channel_name или @channel_name). "
                    "Также можно отправить числовой ID канала.\n\n"
                    "<i>Для приватных каналов — добавьте бота администратором, "
                    "и я автоматически пришлю ID.</i>\n\n"
                    "Нажмите /start для возврата в главное меню"
                )

            # === Кнопка «Стикер» ===
            elif payload == "get_sticker_info":
                text = (
                    "🎟 <b>Получить информацию о стикере</b>\n\n"
                    "Просто отправьте мне любой стикер, "
                    "и я покажу его код, прямую ссылку и размеры!\n\n"
                    "Нажмите /start для возврата в главное меню"
                )

            # === Неизвестный payload ===
            else:
                logger.warning(f"Unknown callback payload: {payload}")
                text = "❌ Неизвестная команда\n\nНажмите /start для возврата в главное меню"

            # При дубликате — только отвечаем на callback, не редактируем сообщение
            if is_duplicate:
                logger.info(f"Skipping message edit due to duplicate detection")
                try:
                    await event.bot.send_callback(
                        callback_id=event.callback.callback_id,
                        notification="✅ Готово"
                    )
                except Exception as cb_err:
                    logger.error(f"Failed to answer callback: {cb_err}", exc_info=True)
                return

            # Параллельно отвечаем на callback и редактируем сообщение
            if text and event.message:
                try:
                    results = await asyncio.gather(
                        event.message.edit(
                            text=text,
                            attachments=[main_menu_keyboard()],
                            parse_mode=ParseMode.HTML
                        ),
                        event.bot.send_callback(
                            callback_id=event.callback.callback_id,
                            notification="✅ Готово"
                        ),
                        return_exceptions=True
                    )
                    
                    # Проверяем результат edit
                    edit_result = results[0]
                    if isinstance(edit_result, Exception):
                        logger.error(
                            f"Failed to edit message: {edit_result}", exc_info=True
                        )
                        # Fallback: если не удалось редактировать, отправляем новое
                        try:
                            if event.message.recipient:
                                await event.bot.send_message(
                                    chat_id=event.message.recipient.chat_id,
                                    text=text,
                                    parse_mode=ParseMode.HTML,
                                    attachments=[main_menu_keyboard()]
                                )
                        except Exception as send_err:
                            logger.error(
                                f"Failed to send fallback message: {send_err}"
                            )
                    else:
                        logger.info(f"Message edited successfully")
                    
                    # Проверяем результат send_callback
                    callback_result = results[1]
                    if isinstance(callback_result, Exception):
                        logger.error(
                            f"Failed to answer callback: {callback_result}", exc_info=True
                        )
                        
                except Exception as gather_err:
                    logger.error(
                        f"Error in gather: {gather_err}", exc_info=True
                    )
                    # Fallback на последовательное выполнение
                    try:
                        await event.bot.send_callback(
                            callback_id=event.callback.callback_id,
                            notification="✅ Готово"
                        )
                    except Exception as cb_err:
                        logger.error(
                            f"Failed to answer callback in fallback: {cb_err}", exc_info=True
                        )
                    
                    if event.message.recipient:
                        try:
                            await event.bot.send_message(
                                chat_id=event.message.recipient.chat_id,
                                text=text,
                                parse_mode=ParseMode.HTML,
                                attachments=[main_menu_keyboard()]
                            )
                        except Exception as send_err:
                            logger.error(
                                f"Failed to send message in fallback: {send_err}"
                            )

        except Exception as e:
            logger.error(
                f"Error in callback handler: {e}", exc_info=True
            )
            # Пытаемся ответить на callback, чтобы кнопка не зависала
            try:
                await event.bot.send_callback(
                    callback_id=event.callback.callback_id,
                    notification="Ошибка"
                )
            except Exception:
                pass

    logger.info("Callback handlers registered")
