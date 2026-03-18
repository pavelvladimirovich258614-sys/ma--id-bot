"""
Точка входа в приложение.
Инициализирует Bot и Dispatcher, подключает обработчики и запускает polling.
"""
import asyncio
import logging
import signal
import sys
from maxapi import Bot, Dispatcher
from maxapi.enums.parse_mode import ParseMode
from maxapi.types import BotCommand

from config import BOT_TOKEN
from handlers.start import register_start_handlers
from handlers.callbacks import register_callback_handlers
from handlers.messages import register_message_handler
from handlers.bot_added import register_bot_added_handler

logger = logging.getLogger(__name__)

# Глобальная переменная для хранения экземпляра бота
_bot = None


def shutdown_handler(signum, frame):
    """Обработчик сигналов SIGINT и SIGTERM для graceful shutdown."""
    logger.info("Shutting down...")
    sys.exit(0)


async def main():
    """Главная функция для запуска бота."""
    global _bot
    
    # Инициализация бота с токеном и HTML parse mode
    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    _bot = bot
    dp = Dispatcher()

    # Регистрация обработчиков
    # 1) bot_started, /start, /help (command handlers)
    register_start_handlers(dp)
    # 2) callback кнопки (message_callback)
    register_callback_handlers(dp)
    # 3) стикеры и пересланные сообщения (message_created)
    register_message_handler(dp)
    # 4) добавление бота в чат/канал (bot_added)
    register_bot_added_handler(dp)

    # Установка команд бота
    try:
        await bot.set_my_commands(
            BotCommand(name='start', description='Главное меню'),
            BotCommand(name='help', description='Помощь')
        )
    except Exception as e:
        logger.warning(f"Не удалось установить команды бота: {e}")

    logger.info("Bot initialized, starting polling...")

    # Запуск polling
    await dp.start_polling(bot)


if __name__ == '__main__':
    # Настройка обработчиков сигналов для graceful shutdown
    try:
        # Для Unix-систем: используем asyncio.add_signal_handler
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(asyncio.to_thread(shutdown_handler, None, None)))
    except (NotImplementedError, AttributeError):
        # Для Windows: используем стандартный signal.signal
        signal.signal(signal.SIGINT, shutdown_handler)
        # SIGTERM может отсутствовать на Windows
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, shutdown_handler)
    
    asyncio.run(main())
