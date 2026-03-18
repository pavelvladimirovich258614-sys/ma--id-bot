"""
Обработчики события запуска бота, команд /start, /help.
"""
import logging
from maxapi.types import BotStarted, MessageCreated, Command
from maxapi.enums.parse_mode import ParseMode
from keyboards.main_menu import main_menu_keyboard, WELCOME_TEXT

logger = logging.getLogger(__name__)


def register_start_handlers(dp):
    """
    Регистрирует обработчики для bot_started и команд /start, /help.

    Args:
        dp: Dispatcher экземпляр для регистрации обработчиков
    """

    @dp.bot_started()
    async def on_bot_started(event: BotStarted):
        """
        Обработчик события bot_started.
        Срабатывает когда пользователь нажимает кнопку «Старт»
        или открывает диалог.
        """
        try:
            logger.info(f"Bot started by user {event.from_user.user_id}")

            keyboard = main_menu_keyboard()
            await event.bot.send_message(
                chat_id=event.chat_id,
                text=WELCOME_TEXT,
                parse_mode=ParseMode.HTML,
                attachments=[keyboard]
            )
        except Exception as e:
            logger.error(f"Error in bot_started handler: {e}", exc_info=True)

    @dp.message_created(Command('start'))
    async def on_start_command(event: MessageCreated):
        """
        Обработчик команды /start.
        Срабатывает когда пользователь отправляет команду /start.
        """
        # Проверка на None
        if event.message is None:
            return
        if event.message.body is None:
            return

        try:
            logger.info(
                f"Command /start from user {event.from_user.user_id}"
            )

            keyboard = main_menu_keyboard()
            await event.message.answer(
                text=WELCOME_TEXT,
                parse_mode=ParseMode.HTML,
                attachments=[keyboard]
            )
        except Exception as e:
            logger.error(
                f"Error in /start handler: {e}", exc_info=True
            )

    @dp.message_created(Command('help'))
    async def on_help_command(event: MessageCreated):
        """
        Обработчик команды /help.
        Показывает подробную справку о всех функциях бота.
        """
        # Проверка на None
        if event.message is None:
            return
        if event.message.body is None:
            return

        try:
            logger.info(
                f"Command /help from user {event.from_user.user_id}"
            )

            help_text = (
                "ℹ️ <b>Справка по боту</b>\n\n"
                "Я помогаю узнать ID различных сущностей "
                "в мессенджере MAX.\n\n"
                "👤 Нажмите <b>Пользователь</b> — покажу ваш ID.\n"
                "📨 Перешлите сообщение — покажу ID отправителя "
                "или чата-источника.\n"
                "💬 Нажмите <b>Чат</b> — объясню как узнать ID чата.\n"
                "📣 Нажмите <b>Канал</b> — объясню как узнать ID канала.\n"
                "🤖 Нажмите <b>Бот</b> — покажу информацию о боте.\n"
                "🎟 Отправьте стикер — покажу его код и ссылку."
            )
            keyboard = main_menu_keyboard()
            await event.message.answer(
                text=help_text,
                parse_mode=ParseMode.HTML,
                attachments=[keyboard]
            )
        except Exception as e:
            logger.error(
                f"Error in /help handler: {e}", exc_info=True
            )

    logger.info("Start handlers registered")
