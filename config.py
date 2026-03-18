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
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Загрузка токена из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN не найден в переменных окружения!")
    print("Создайте файл .env с переменной BOT_TOKEN=ваш_токен")
    sys.exit(1)
