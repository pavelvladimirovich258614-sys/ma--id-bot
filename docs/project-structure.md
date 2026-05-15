# Структура проекта MaxIDBot

Источник: локальная документация проекта MaxIDBot [1].

## Назначение

MaxIDBot — бот для мессенджера MAX, который возвращает ID пользователей, ботов, чатов, каналов и стикеров. По назначению он является аналогом Telegram-бота `@IDd_Helper_Bot`.

## Требования

- Python 3.10+.
- Библиотека `maxapi` 0.9.16.
- `python-dotenv` для загрузки переменных окружения.
- Подтвержденная организация на business.max.ru для создания бота.
- Токен бота из кабинета MAX Business.

## Файловая структура

```text
max-id-bot/
├── bot.py
├── config.py
├── requirements.txt
├── handlers/
│   ├── __init__.py
│   ├── start.py
│   ├── callbacks.py
│   ├── messages.py
│   └── bot_added.py
├── keyboards/
│   ├── __init__.py
│   └── main_menu.py
├── README.md
├── CLAUDE.md
├── TZ.md
└── PROMPT_*.md
```

## Основные файлы

`bot.py` — точка входа. Создает bot/dispatcher, регистрирует обработчики и запускает polling.

`config.py` — загружает `.env`, проверяет `BOT_TOKEN` и настраивает логирование.

`requirements.txt` — фиксирует зависимости проекта. Базовые зависимости: `maxapi==0.9.16` и `python-dotenv`.

## Обработчики

`handlers/start.py` — событие запуска бота, команды `/start` и `/help`. Эти обработчики не должны блокироваться подпиской.

`handlers/callbacks.py` — inline-кнопки главного меню: пользователь, бот, чат, канал, стикер. При внедрении подписки нельзя ломать существующую ID-логику и резолверы.

`handlers/messages.py` — обработка стикеров и пересланных сообщений.

`handlers/bot_added.py` — реакция на добавление бота в чат или канал.

## Клавиатуры

`keyboards/main_menu.py` строит основное inline-меню через `InlineKeyboardBuilder`. В меню есть кнопки для получения ID чата, канала, пользователя, бота и информации о стикере.

Для Subscription Gate будет добавлена отдельная клавиатура с link-кнопкой на канал.

## Конфигурация

Секреты и параметры окружения должны идти через `.env` и `config.py`. `BOT_TOKEN`, `CHANNEL_ID`, `CHANNEL_LINK`, `SUBSCRIPTION_TEXT` и `API_BASE` не должны хардкодиться внутри обработчиков.
