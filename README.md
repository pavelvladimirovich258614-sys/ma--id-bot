# MaxIDBot

Бот для мессенджера MAX, выдающий ID различных сущностей: пользователей, чатов, каналов, ботов и стикеров. Аналог Telegram-бота @IDd_Helper_Bot.

## Функции

- 👤 **Пользователь** — получение вашего User ID, имени и никнейма
- 💬 **Чат** — инструкция по получению ID группового чата (пересылка или добавление бота)
- 📣 **Канал** — получение ID канала по ссылке (например `https://max.ru/channel_name` или `@channel_name`)
- 🤖 **Бот** — получение ID бота, имени и описания
- 🎟 **Стикер** — получение кода стикера, прямой ссылки на изображение и размеров
- 📨 **Пересылка сообщений** — при пересылке сообщения бот покажет ID чата-источника или отправителя
- 🔔 **Добавление в чат/канал** — бот автоматически отправит ID при добавлении

## Команды меню

- `/start` — начать работу с ботом, показать главное меню
- `/help` — получить справку о функциях бота

## Установка

1. Клонируйте репозиторий:
```bash
git clone <repository_url>
cd max-id-bot
```

2. Создайте виртуальное окружение:
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Настройте токен бота:
```bash
# Создайте файл .env и добавьте токен
BOT_TOKEN=ваш_токен
CHANNEL_ID=id752703975446_biz
CHANNEL_LINK=https://max.ru/id752703975446_biz
SUBSCRIPTION_TEXT=Чтобы продолжить пользоваться ботом, подпишитесь на канал:
API_BASE=https://platform-api.max.ru
```

Токен можно получить на [business.max.ru](https://business.max.ru) в разделе «Чат-боты» → «Интеграция» → «Получить токен».

Для проверки подписки бот должен быть администратором канала `CHANNEL_ID`.
Первый запрос пользователя бесплатный, со второго запроса бот проверяет
подписку через MAX API и показывает кнопку перехода на канал, если
подписки нет.

## Запуск

```bash
python bot.py
```

## Структура проекта

```
max-id-bot/
├── bot.py              # Точка входа: инициализация, регистрация обработчиков, polling
├── config.py           # Конфигурация: загрузка BOT_TOKEN из .env, логирование
├── handlers/
│   ├── __init__.py     # Пакет обработчиков
│   ├── start.py        # Обработчики bot_started, /start и /help
│   ├── callbacks.py    # Обработчики inline-кнопок (Пользователь, Бот, Чат, Канал, Стикер)
│   ├── messages.py     # Обработчик стикеров и пересланных сообщений
│   └── bot_added.py    # Обработчик добавления бота в чат/канал
├── database/
│   ├── __init__.py     # Пакет SQLite-хранилища
│   └── storage.py      # Таблица users и операции init/get/update
├── middleware/
│   ├── __init__.py     # Пакет middleware
│   └── subscription.py # Проверка подписки и кэш 5 минут
├── keyboards/
│   ├── __init__.py     # Экспорт main_menu_keyboard
│   ├── main_menu.py    # Inline-клавиатура главного меню (2×2 + стикер)
│   └── subscription.py # Кнопка-ссылка на канал
├── requirements.txt    # Зависимости: maxapi, python-dotenv, httpx, aiosqlite
├── .env                # Токен бота (создаётся пользователем, не в Git)
├── .gitignore          # Исключения для Git
└── README.md           # Документация
```

## Требования

- Python 3.10+
- Библиотека `maxapi` 0.9.16
- Зарегистрированная организация на [business.max.ru](https://business.max.ru)
- Созданный и прошедший модерацию бот

## Документация

- [MAX Bot API](https://dev.max.ru/docs-api)
- [maxapi Python библиотека](https://github.com/max-messenger/max-botapi-python)
