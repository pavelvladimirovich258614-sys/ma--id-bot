"""
Обработчик события добавления бота в чат или канал.
"""
import logging
from maxapi.types import BotAdded
from maxapi.enums.parse_mode import ParseMode

logger = logging.getLogger(__name__)


def register_bot_added_handler(dp):
    """
    Регистрирует обработчик для события bot_added.

    Args:
        dp: Dispatcher экземпляр для регистрации обработчиков
    """

    @dp.bot_added()
    async def on_bot_added(event: BotAdded):
        """
        Обработчик события bot_added.
        Срабатывает когда бота добавляют в групповой чат или канал.
        Для каналов ВСЕГДА отправляет информацию в личку пользователю.
        """
        # Проверка на None для критических полей
        if event.chat_id is None:
            logger.error("Bot added event has no chat_id")
            return
        if event.user is None:
            logger.error("Bot added event has no user")
            return

        chat_id = event.chat_id
        user = event.user
        is_channel = getattr(event, 'is_channel', False)

        logger.info(
            f"Bot added to {'channel' if is_channel else 'chat'} "
            f"{chat_id} by user {user.user_id}"
        )

        # Пытаемся получить информацию о чате (бот как участник может иметь доступ)
        chat_info = None
        try:
            chat_info = await event.bot.get_chat_by_id(id=chat_id)
            logger.info(f"Successfully got chat info for {chat_id}")
        except Exception as e:
            logger.warning(f"Failed to get chat info: {e}")
            chat_info = None

        # Формируем текст сообщения
        if is_channel:
            if chat_info:
                title = getattr(chat_info, 'title', None) or 'Без названия'
                link = getattr(chat_info, 'link', None)
                participants_count = getattr(chat_info, 'participants_count', 'N/A')
                description = getattr(chat_info, 'description', None)
                text = (
                    f"📣 <b>Бот добавлен в канал:</b>\n\n"
                    f"<b>Channel ID:</b> <code>{chat_id}</code>\n"
                    f"<b>Название:</b> {title}\n"
                )
                if link:
                    text += f"<b>Ссылка:</b> {link}\n"
                text += f"<b>Подписчиков:</b> {participants_count}\n"
                if description:
                    text += f"<b>Описание:</b> {description}\n"
                text += "\n<i>Напишите /start боту в личку для главного меню</i>"
            else:
                # Fallback без информации о чате
                text = (
                    f"📣 <b>Бот добавлен в канал.</b>\n\n"
                    f"<b>Channel ID:</b> <code>{chat_id}</code>\n\n"
                    f"<i>Подробная информация о канале недоступна. "
                    f"Возможно, у бота недостаточно прав.</i>\n\n"
                    f"Напишите /start боту в личку для главного меню"
                )
        else:
            # Групповой чат
            if chat_info:
                title = getattr(chat_info, 'title', None) or 'Без названия'
                participants_count = getattr(chat_info, 'participants_count', 'N/A')
                is_public = getattr(chat_info, 'is_public', False)
                link = getattr(chat_info, 'link', None)
                text = (
                    f"💬 <b>Бот добавлен в групповой чат:</b>\n\n"
                    f"<b>Chat ID:</b> <code>{chat_id}</code>\n"
                    f"<b>Название:</b> {title}\n"
                    f"<b>Участников:</b> {participants_count}\n"
                )
                if is_public and link:
                    text += f"<b>Ссылка:</b> {link}\n"
                text += "\n<i>Чат успешно подключён!</i>\n\n"
                text += "<i>Напишите /start боту в личку для главного меню</i>"
            else:
                text = (
                    f"💬 <b>Бот добавлен в групповой чат.</b>\n\n"
                    f"<b>Chat ID:</b> <code>{chat_id}</code>\n\n"
                    f"<i>Подробная информация о чате недоступна.</i>\n\n"
                    f"Напишите /start боту в личку для главного меню"
                )

        # Сначала пытаемся отправить в канал/чат (если есть права)
        sent_to_chat = False
        try:
            await event.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Message sent to chat/channel {chat_id}")
            sent_to_chat = True
        except Exception as e:
            logger.warning(f"Failed to send message to chat {chat_id}: {e}")

        # ДЛЯ КАНАЛОВ: ВСЕГДА отправляем информацию в личку пользователю
        if is_channel:
            try:
                # Если уже отправили в канал — короткое подтверждение
                if sent_to_chat:
                    confirm_text = (
                        f"📣 Информация о канале отправлена в сам канал.\n\n"
                        f"<b>Channel ID:</b> <code>{chat_id}</code>\n\n"
                        f"Напишите /start для главного меню"
                    )
                else:
                    # Если не удалось отправить в канал — полная информация
                    confirm_text = text

                await event.bot.send_message(
                    user_id=user.user_id,
                    text=confirm_text,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Channel info sent to user's private chat (user_id={user.user_id})")
            except Exception as e:
                logger.error(f"Failed to send channel info to user: {e}", exc_info=True)

        # ДЛЯ ГРУПП: если не удалось отправить в чат — отправляем в личку
        elif not sent_to_chat:
            try:
                await event.bot.send_message(
                    user_id=user.user_id,
                    text=text,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Message sent to user's private chat (user_id={user.user_id})")
            except Exception as e:
                logger.error(f"Failed to send message to user: {e}", exc_info=True)

    logger.info("Bot added handler registered")
