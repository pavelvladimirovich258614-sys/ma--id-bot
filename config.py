"""
Конфигурация бота.
Загружает токен из переменной окружения BOT_TOKEN.
"""
import os
import sys
import logging
from dotenv import load_dotenv

# Загрузка переменных окружения из .env
load_dotenv()

# Настройка уровня логирования
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


def _parse_optional_int(value, name):
    """Парсит необязательное целочисленное значение из окружения."""
    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        logger.warning(f"{name} должен быть числом, получено: {value}")
        return None


def _parse_admin_user_ids(value):
    """Парсит список ID администраторов из окружения в множество int."""
    if not value:
        return set()

    ids = set()
    for part in str(value).replace(",", " ").split():
        try:
            ids.add(int(part))
        except ValueError:
            logger.warning(
                "ADMIN_USER_IDS содержит нечисловое значение: %s", part
            )
    return ids


# Загрузка токена из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Настройки проверки подписки на канал
CHANNEL_ID = os.getenv("CHANNEL_ID", "id752703975446_biz")
CHANNEL_CHAT_ID = _parse_optional_int(
    os.getenv("CHANNEL_CHAT_ID", "-72143469522347"),
    "CHANNEL_CHAT_ID"
)
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://max.ru/id752703975446_biz")
SUBSCRIPTION_TEXT = os.getenv(
    "SUBSCRIPTION_TEXT",
    "❌ Извините, вы не подписаны на канал.\n\n"
    "Чтобы пользоваться ботом, пожалуйста, подпишитесь на канал "
    "и после этого нажмите «Проверить подписку»."
)
API_BASE = os.getenv("API_BASE", "https://platform-api2.max.ru")
ADMIN_USER_IDS = _parse_admin_user_ids(os.getenv("ADMIN_USER_IDS", ""))

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN не найден в переменных окружения!")
    print("Создайте файл .env с переменной BOT_TOKEN=ваш_токен")
    sys.exit(1)


# Admin panel constants
BROADCAST_RATE_LIMIT = 10
BROADCAST_MAX_RETRIES = 3
BROADCAST_RETRY_BACKOFF_BASE = 1
BROADCAST_RETRY_BACKOFF_MAX = 60
BROADCAST_PROGRESS_UPDATE_INTERVAL = 5
BROADCAST_PROGRESS_UPDATE_EVERY = 25

BROADCAST_LIVE_ENABLED = os.getenv("BROADCAST_LIVE_ENABLED", "false").lower() == "true"
