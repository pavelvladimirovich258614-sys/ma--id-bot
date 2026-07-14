Теперь у меня есть вся необходимая информация для составления полного технического задания. Вот оно:

---

# Техническое задание (ТЗ)
## Бот «MyMaxIDBot» — аналог Telegram-бота @IDd_Helper_Bot для мессенджера MAX

---

## 1. Общее описание проекта

Необходимо разработать чат-бота для мессенджера MAX, который является функциональным аналогом Telegram-бота **MyTelegramIDBot** (@IDd_Helper_Bot). Бот предназначен для быстрого определения ID различных сущностей в мессенджере MAX: пользователей, чатов (групп), каналов, ботов и стикеров.

---
Документация https://dev.max.ru/docs/maxbusiness/selectionservices
## 2. Платформа и технологический стек

### 2.1 Платформа
Мессенджер **MAX** (max.ru). API-домен: `platform-api2.max.ru`.

### 2.2 Рекомендуемый стек

**Вариант A — Python (рекомендуется):**
- Язык: Python 3.10+
- Библиотека: `maxapi` (pip install maxapi) — неофициальная, но зрелая библиотека, стилистически близкая к aiogram
- Альтернатива: прямые HTTP-запросы к `platform-api2.max.ru`
- Режим работы: Long Polling (для разработки/тестирования), Webhook (для продакшена)

**Вариант B — JavaScript/TypeScript:**
- Библиотека: `@maxhub/max-bot-api` (npm install @maxhub/max-bot-api) — официальная
- Node.js 18+

### 2.3 Авторизация
Токен бота передаётся в заголовке `Authorization: <token>` (передача через query-параметры больше не поддерживается).

### 2.4 Предварительные условия
- Зарегистрированная и верифицированная организация (юрлицо или ИП, резидент РФ) на платформе MAX для партнёров (business.max.ru)
- Созданный и прошедший модерацию бот
- Полученный токен бота (раздел «Чат-боты» → «Интеграция» → «Получить токен»)
- В настройках бота **разрешено** добавление в групповые чаты и каналы (иначе бот не сможет выдавать ID чатов и каналов)

---

## 3. Функциональные требования

### 3.1 Стартовый экран (приветственное сообщение)

При нажатии пользователем кнопки «Старт» или отправке команды `/start` бот должен отправить приветственное сообщение с описанием своих возможностей и inline-клавиатурой с 4 кнопками, расположенными в сетке 2×2:

**Текст сообщения (с форматированием Markdown):**
```
👆 Используйте меню ниже:

• 💬 **Chat** — получить ID группы
• 📣 **Channel** — получить ID канала
• 👤 **User** — получить ID пользователя
• 🤖 **Bot** — получить ID бота

🎟 Получить ID стикера — просто отправьте стикер боту.
```

**Inline-клавиатура:**

| 💬 Chat | 📣 Channel |
|---------|-----------|
| 👤 User | 🤖 Bot    |

Все четыре кнопки — типа `callback`, с payload: `get_chat_id`, `get_channel_id`, `get_user_id`, `get_bot_id`.

### 3.2 Функция «User» — Получение ID пользователя

При нажатии кнопки **👤 User**:
- Бот извлекает `user_id` из контекста события `message_callback` (поле `user` объекта Update содержит `user_id`)
- Бот отвечает сообщением:
```
👤 Ваш User ID: {user_id}
Имя: {first_name} {last_name}
Ник: @{username}
```

**Используемые данные:** поле `user` из объекта `MessageCallbackUpdate`, содержащее `user_id`, `first_name`, `last_name`, `username`.

### 3.3 Функция «Chat» — Получение ID группового чата

При нажатии кнопки **💬 Chat**:
- Если бот находится в **личном диалоге** (1-на-1), отвечает сообщением:
```
ℹ️ Добавьте бота в групповой чат, чтобы узнать Chat ID.
Chat ID текущего диалога: {chat_id}
```
- Если бот находится в **групповом чате**, отвечает:
```
💬 Chat ID: {chat_id}
Название: {title}
Участников: {participants_count}
```

**Реализация:** ID чата извлекается из контекста события `message_callback`. Дополнительная информация получается через API-запрос `GET /chats/{chatId}`, который возвращает объект Chat с полями: `chat_id`, `type`, `title`, `participants_count`, `owner_id`, `is_public`, `link`, `description`.

### 3.4 Функция «Channel» — Получение ID канала

При нажатии кнопки **📣 Channel**:
- Если бот находится в **канале** (бот должен быть назначен администратором), отвечает:
```
📣 Channel ID: {chat_id}
Название: {title}
Ссылка: {link}
```
- Если бот не в канале, отвечает:
```
ℹ️ Добавьте бота администратором в канал, чтобы узнать Channel ID.
```

**Реализация:** При добавлении бота в канал бот получает обновление `bot_added`. Информация о канале получается через `GET /chats/{chatId}`. Бот должен хранить в оперативной памяти (или в БД) маппинг `chat_id → тип (chat/channel)`, чтобы при нажатии кнопки из канала корректно определять тип.

**Важное ограничение:** В API MAX групповые чаты и каналы оба имеют `type: "chat"`. Различить их можно по наличию поля `is_public` (каналы обычно публичные) и поля `link` (у каналов есть публичная ссылка). Альтернативная стратегия — инструкция пользователю переслать сообщение из канала боту, и бот по полю `link` в пересылке определяет ID.

### 3.5 Функция «Bot» — Получение ID бота

При нажатии кнопки **🤖 Bot**:
- Бот выполняет API-запрос `GET /me` и отвечает:
```
🤖 Bot ID: {user_id}
Имя: {first_name}
Ник: @{username}
Описание: {description}
```

**API-запрос:**
```
GET https://platform-api2.max.ru/me
Authorization: <token>
```
**Ответ:** объект User с `user_id`, `first_name`, `username`, `is_bot: true`, `description`, `avatar_url`.

### 3.6 Функция «Sticker» — Получение ID стикера

Когда пользователь отправляет стикер боту:
- Бот обрабатывает событие `message_created`
- Из объекта `message.body.attachments` бот находит вложение с `type: "sticker"`
- Из вложения извлекается: `code` (уникальный код стикера), `url` (ссылка на изображение стикера), `width`, `height`
- Бот отвечает:
```
🎟 Информация о стикере:
Код: {code}
Ссылка: {url}
Размер: {width}×{height}

Для использования в разработке:
• Код стикера: {code}
• Прямая ссылка: {url}
```

**Структура StickerAttachment (из Dart SDK / JS SDK):**
```json
{
  "type": "sticker",
  "payload": {
    "code": "stickerCode",
    "url": "https://...",
    "width": 512,
    "height": 512
  }
}
```

---

## 4. Обработка событий (Update Types)

Бот должен подписываться на следующие типы обновлений:

| Тип обновления | Назначение |
|---|---|
| `bot_started` | Пользователь нажал кнопку «Старт» / открыл диалог с ботом |
| `message_created` | Новое сообщение (для обработки стикеров и команды /start) |
| `message_callback` | Нажатие на inline-кнопку (Chat, Channel, User, Bot) |
| `bot_added` | Бот добавлен в чат/канал (для определения контекста) |
| `bot_removed` | Бот удалён из чата/канала |

---

## 5. Архитектура бота

### 5.1 Модульная структура (Python, maxapi)

```
max-id-bot/
├── bot.py              # Точка входа, инициализация Bot и Dispatcher
├── handlers/
│   ├── __init__.py
│   ├── start.py        # Обработчики /start и bot_started
│   ├── callbacks.py    # Обработчики нажатий на inline-кнопки
│   ├── stickers.py     # Обработчик входящих стикеров
│   └── groups.py       # Обработчик событий добавления/удаления бота
├── keyboards/
│   ├── __init__.py
│   └── main_menu.py    # Определение inline-клавиатуры главного меню
├── services/
│   ├── __init__.py
│   └── api_client.py   # Обёртка над API-запросами GET /me, GET /chats/{id}
├── config.py           # Конфигурация (токен из .env)
├── .env                # BOT_TOKEN=AAH...
├── requirements.txt    # maxapi
└── README.md
```

### 5.2 Схема обработки событий

```
Пользователь
    │
    ├── Нажал "Старт" ──→ bot_started ──→ Отправить приветствие + inline-клавиатуру
    │
    ├── Отправил /start ──→ message_created (Command) ──→ Приветствие + клавиатура
    │
    ├── Нажал кнопку "User" ──→ message_callback (payload="get_user_id")
    │                              └──→ Извлечь user.user_id ──→ Ответить
    │
    ├── Нажал кнопку "Chat" ──→ message_callback (payload="get_chat_id")
    │                              └──→ GET /chats/{chatId} ──→ Ответить
    │
    ├── Нажал кнопку "Channel" ──→ message_callback (payload="get_channel_id")
    │                                 └──→ GET /chats/{chatId} ──→ Ответить
    │
    ├── Нажал кнопку "Bot" ──→ message_callback (payload="get_bot_id")
    │                             └──→ GET /me ──→ Ответить
    │
    └── Отправил стикер ──→ message_created (attachment.type == "sticker")
                              └──→ Извлечь code, url ──→ Ответить
```

---

## 6. Примерный код реализации (Python, maxapi)

### 6.1 bot.py — Главный файл

```python
import asyncio
import logging
import os

from maxapi import Bot, Dispatcher
from maxapi.types import (
    BotStarted, MessageCreated, MessageCallback, Command
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
bot = Bot(BOT_TOKEN)
dp = Dispatcher()


# --- Inline-клавиатура главного меню ---
MAIN_KEYBOARD = {
    "type": "inline_keyboard",
    "payload": {
        "buttons": [
            [
                {"type": "callback", "text": "💬 Chat", "payload": "get_chat_id"},
                {"type": "callback", "text": "📣 Channel", "payload": "get_channel_id"}
            ],
            [
                {"type": "callback", "text": "👤 User", "payload": "get_user_id"},
                {"type": "callback", "text": "🤖 Bot", "payload": "get_bot_id"}
            ]
        ]
    }
}

WELCOME_TEXT = (
    "👆 Используйте меню ниже:\n\n"
    "• 💬 Chat — получить ID группы\n"
    "• 📣 Channel — получить ID канала\n"
    "• 👤 User — получить ID пользователя\n"
    "• 🤖 Bot — получить ID бота\n\n"
    "🎟 Получить ID стикера — просто отправьте стикер боту."
)


# --- Обработчик запуска бота ---
@dp.bot_started()
async def on_bot_started(event: BotStarted):
    await event.bot.send_message(
        chat_id=event.chat_id,
        text=WELCOME_TEXT,
        attachments=[MAIN_KEYBOARD]
    )


# --- Обработчик команды /start ---
@dp.message_created(Command('start'))
async def on_start_command(event: MessageCreated):
    await event.message.answer(
        text=WELCOME_TEXT,
        attachments=[MAIN_KEYBOARD]
    )


# --- Обработчик нажатий на кнопки ---
@dp.message_callback()
async def on_callback(event: MessageCallback):
    payload = event.payload
    user = event.user
    chat_id = event.chat_id
    callback_id = event.callback_id

    if payload == "get_user_id":
        text = (
            f"👤 Ваш User ID: {user.user_id}\n"
            f"Имя: {user.first_name or ''} {getattr(user, 'last_name', '') or ''}\n"
            f"Ник: @{user.username or 'не задан'}"
        )

    elif payload == "get_chat_id":
        # Получаем информацию о чате через API
        try:
            chat_info = await event.bot.get_chat(chat_id)
            text = (
                f"💬 Chat ID: {chat_id}\n"
                f"Название: {getattr(chat_info, 'title', 'Личный диалог') or 'Личный диалог'}\n"
                f"Участников: {getattr(chat_info, 'participants_count', 'N/A')}"
            )
        except Exception:
            text = f"💬 Chat ID: {chat_id}"

    elif payload == "get_channel_id":
        try:
            chat_info = await event.bot.get_chat(chat_id)
            link = getattr(chat_info, 'link', None)
            if link:
                text = (
                    f"📣 Channel ID: {chat_id}\n"
                    f"Название: {chat_info.title}\n"
                    f"Ссылка: {link}"
                )
            else:
                text = (
                    f"ℹ️ Текущий чат не является каналом.\n"
                    f"Chat ID: {chat_id}\n\n"
                    f"Добавьте бота администратором в канал, "
                    f"чтобы узнать Channel ID."
                )
        except Exception:
            text = (
                "ℹ️ Добавьте бота администратором в канал, "
                "чтобы узнать Channel ID."
            )

    elif payload == "get_bot_id":
        bot_info = await event.bot.get_me()
        text = (
            f"🤖 Bot ID: {bot_info.user_id}\n"
            f"Имя: {bot_info.first_name or bot_info.name}\n"
            f"Ник: @{bot_info.username or 'не задан'}\n"
            f"Описание: {getattr(bot_info, 'description', '') or 'отсутствует'}"
        )

    else:
        text = "Неизвестная команда"

    # Отправляем ответ на callback
    await event.bot.send_answer(
        callback_id=callback_id,
        notification=text
    )
    # Также отправляем сообщение в чат
    await event.bot.send_message(
        chat_id=chat_id,
        text=text
    )


# --- Обработчик стикеров ---
@dp.message_created()
async def on_sticker(event: MessageCreated):
    message = event.message
    if not message or not message.body:
        return

    attachments = getattr(message.body, 'attachments', None) or []
    for att in attachments:
        if getattr(att, 'type', '') == 'sticker':
            code = getattr(att, 'code', None) or getattr(
                getattr(att, 'payload', None), 'code', 'N/A'
            )
            url = getattr(att, 'url', None) or getattr(
                getattr(att, 'payload', None), 'url', 'N/A'
            )
            width = getattr(att, 'width', '?')
            height = getattr(att, 'height', '?')

            text = (
                f"🎟 Информация о стикере:\n\n"
                f"Код (code): {code}\n"
                f"Ссылка: {url}\n"
                f"Размер: {width}×{height}\n\n"
                f"Для использования в разработке:\n"
                f"• Код стикера: {code}\n"
                f"• Прямая ссылка: {url}"
            )
            await message.answer(text)
            return


async def main():
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
```

> **Примечание:** Точные имена методов и атрибутов могут отличаться в зависимости от версии библиотеки `maxapi`. Перед запуском необходимо сверить с актуальной документацией модуля на GitHub. Код выше является архитектурным ориентиром.

---

## 7. Используемые API-эндпоинты

| Метод | Эндпоинт | Назначение |
|---|---|---|
| GET | `/me` | Получение информации о боте (user_id, name, username, description) |
| GET | `/chats/{chatId}` | Получение информации о чате/канале (chat_id, title, participants_count, link, is_public) |
| GET | `/chats` | Получение списка всех чатов бота |
| POST | `/messages` | Отправка сообщений (с текстом, вложениями, inline-клавиатурой) |
| POST | `/answers?callback_id={id}` | Ответ на нажатие callback-кнопки (уведомление или обновление сообщения) |
| GET | `/updates` | Long Polling — получение обновлений (для разработки) |
| POST | `/subscriptions` | Настройка Webhook (для продакшена) |

---

## 8. Особенности и ограничения платформы MAX

### 8.1 Отличия от Telegram Bot API

| Параметр | Telegram | MAX |
|---|---|---|
| Создание бота | Через @BotFather (бесплатно, любой пользователь) | Через платформу business.max.ru (только юрлица/ИП, модерация) |
| Токен | Передаётся в URL | Передаётся в заголовке `Authorization` |
| Стикеры | file_id + file_unique_id + set_name | code + url + width + height |
| Каналы | Отдельный тип chat (type: "channel") | Тот же тип "chat", отличается по is_public и link |
| Лимит запросов | Без жёстких лимитов для большинства ботов | 30 RPS |
| Inline-клавиатура | До 100 кнопок | До 210 кнопок (30 рядов × 7 кнопок) |
| Форматирование | Markdown / HTML | Markdown / HTML (аналогично) |
| Макс. длина сообщения | 4096 символов | 4000 символов |

### 8.2 Ключевые ограничения

- Бот может быть создан только юрлицом/ИП (резидент РФ)
- Необходима модерация бота перед публикацией
- Максимум 5 ботов на организацию
- Ник бота генерируется автоматически по шаблону `idИНН_bot` — изменить нельзя
- Для получения событий из групповых чатов и каналов бот должен быть **администратором**
- Long Polling — только для разработки, на продакшене — исключительно Webhook (порт 443, HTTPS)

### 8.3 Работа со стикерами

В MAX стикер — это вложение (attachment) типа `"sticker"` со следующими полями: `code` (уникальный код стикера, аналог file_id в Telegram), `url` (прямая ссылка на изображение), `width` и `height` (размеры в пикселях). Для отправки стикера ботом используется `StickerAttachment` с параметром `code`.

---

## 9. Этапы реализации

| Этап | Описание | Оценка |
|---|---|---|
| 1. Регистрация | Создать организацию на business.max.ru, пройти верификацию | 1–3 дня |
| 2. Создание бота | Заполнить карточку бота, пройти модерацию | 1–2 дня |
| 3. Настройка окружения | Установить Python 3.10+, pip install maxapi, настроить .env | 30 минут |
| 4. Базовый функционал | Обработчик /start, приветственное сообщение, inline-клавиатура | 2–3 часа |
| 5. Обработка кнопок | User ID, Bot ID, Chat ID, Channel ID | 3–4 часа |
| 6. Обработка стикеров | Парсинг StickerAttachment, вывод code/url | 1–2 часа |
| 7. Тестирование | Тесты в личном диалоге, групповом чате, канале | 2–3 часа |
| 8. Деплой | Переход на Webhook, настройка HTTPS, запуск на сервере | 2–4 часа |

**Итого (разработка без учёта регистрации): ~1–2 рабочих дня.**

---

## 10. Тестирование

### 10.1 Тест-кейсы

1. **Личный диалог:** Запустить бота → проверить приветствие → нажать каждую из 4 кнопок → убедиться в корректности ответов
2. **User ID:** Нажать "User" → проверить, что возвращается правильный user_id текущего пользователя
3. **Bot ID:** Нажать "Bot" → проверить, что возвращается ID и имя самого бота
4. **Групповой чат:** Добавить бота в группу → нажать "Chat" → проверить chat_id, название, число участников
5. **Канал:** Добавить бота администратором в канал → нажать "Channel" → проверить channel_id, ссылку
6. **Стикер:** Отправить боту стикер → проверить вывод code, url, размеров
7. **Повторный /start:** Убедиться, что клавиатура генерируется заново
8. **Нагрузочное:** Проверить, что бот не превышает 30 RPS

---

## 11. Резюме

Данное ТЗ полностью описывает процесс создания бота-аналога Telegram @IDd_Helper_Bot для мессенджера MAX. Бот реализует все заявленные функции: выдача ID пользователя, чата, канала, бота и информации о стикерах. Рекомендуемый стек — Python + maxapi, так как эта связка обеспечивает максимально быструю разработку при знакомом (aiogram-подобном) синтаксисе. Ключевой момент — предварительная регистрация организации и модерация бота на платформе MAX для партнёров, что может занять до 3–5 рабочих дней.