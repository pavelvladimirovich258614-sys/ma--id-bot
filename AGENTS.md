# MaxIDBot — Agent Guide

This file provides essential information for AI coding agents working with the MaxIDBot project.

---

## Project Overview

**MaxIDBot** is a chatbot for the MAX messenger (max.ru, formerly max.com) that retrieves IDs of various entities: users, chats, channels, bots, and stickers. It is a functional analog of Telegram's @IDd_Helper_Bot.

**Platform Requirements:**
- MAX Messenger requires a verified Russian organization (legal entity or individual entrepreneur) to create bots
- Bot must pass moderation before receiving a token
- Maximum 5 bots per organization
- Bot usernames are auto-generated in format `id{INN}_bot` (cannot be changed)

---

## Technology Stack

| Component | Details |
|-----------|---------|
| Language | Python 3.10+ |
| Main Library | `maxapi` 0.9.16 (aiogram-like syntax) |
| Environment | `python-dotenv` for configuration |
| Runtime Mode | Long polling (development) |

**Important:** The `maxapi` library version 0.9.16 is used. Version 1.3.0+ does not exist on PyPI despite what some documentation might suggest.

---

## Project Structure

```
max-id-bot/
├── bot.py                 # Entry point: Bot/Dispatcher init, handler registration, polling
├── config.py              # Configuration: loads BOT_TOKEN from .env, sets up logging
├── requirements.txt       # Dependencies: maxapi, python-dotenv
├── .env                   # Environment variables (BOT_TOKEN) - gitignored
├── .gitignore             # Standard Python gitignore
├── handlers/              # Event handlers
│   ├── __init__.py        # Package marker
│   ├── start.py           # bot_started event, /start command
│   ├── callbacks.py       # Inline button callbacks (User, Chat, Channel, Bot, Sticker, Harvest)
│   ├── messages.py        # Sticker handler, forwarded messages, channel lookup, harvest flows
│   └── bot_added.py       # Bot added to chat/channel handler
├── keyboards/             # Inline keyboards
│   ├── __init__.py        # Exports main_menu_keyboard
│   └── main_menu.py       # Main menu 2x2 grid + sticker button
├── README.md              # User documentation (Russian)
├── CLAUDE.md              # Detailed API specifics and architecture
├── TZ.md                  # Full technical specification (Russian)
└── PROMPT_*.md            # Development prompts/history
```

---

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot (requires BOT_TOKEN in .env file)
python bot.py

# Environment setup
cp .env.example .env  # Then edit .env with your actual token
```

**Prerequisites:**
1. Create `.env` file with `BOT_TOKEN=your_token_here`
2. Token obtained from business.max.ru → "Чат-боты" → "Интеграция" → "Получить токен"

---

## Architecture Patterns

### Handler Registration Pattern

Each handler module exports a `register_*_handlers(dp)` function:

```python
# handlers/start.py
def register_start_handlers(dp):
    @dp.bot_started()
    async def on_bot_started(event: BotStarted):
        # handler logic
        
    @dp.message_created(Command('start'))
    async def on_start_command(event: MessageCreated):
        # handler logic
```

These are imported and called in `bot.py`:

```python
# bot.py
from handlers.start import register_start_handlers
from handlers.callbacks import register_callback_handlers
from handlers.messages import register_message_handler
from handlers.bot_added import register_bot_added_handler

register_start_handlers(dp)
register_callback_handlers(dp)
register_message_handler(dp)
register_bot_added_handler(dp)
```

### Keyboard Definition Pattern

Keyboards are built using `InlineKeyboardBuilder`:

```python
from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

builder = InlineKeyboardBuilder()
builder.row(
    CallbackButton(text="💬 Chat", payload="get_chat_id"),
    CallbackButton(text="📣 Channel", payload="get_channel_id")
)
```

---

## MAX API Specifics

### Authentication
- Token passed in `Authorization` header (NOT query parameters)
- Old query-param method is deprecated

### Key API Differences from Telegram

| Feature | Telegram | MAX |
|---------|----------|-----|
| Token location | URL param | `Authorization` header |
| Channel type | `type: "channel"` | `type: "chat"` (check `link` field) |
| Sticker ID | `file_id` | `code` + `url` + dimensions |
| Rate limit | Relaxed | 30 RPS |
| Max message length | 4096 chars | 4000 chars |
| Max keyboard buttons | 100 | 210 (30 rows × 7 cols) |

### Event Types Handled

| Event | Handler File | Trigger |
|-------|--------------|---------|
| `bot_started` | `handlers/start.py` | User clicks "Start" button |
| `message_created` + `Command('start')` | `handlers/start.py` | User sends /start |
| `message_callback` | `handlers/callbacks.py` | Inline button click |
| `message_created` (sticker) | `handlers/messages.py` | Sticker attachment received |
| `message_created` (forward) | `handlers/messages.py` | Forwarded message received |
| `bot_added` | `handlers/bot_added.py` | Bot added to chat/channel |

### Callback Response Pattern

**Correct (MAX):**
```python
await event.bot.send_callback(
    callback_id=event.callback.callback_id,
    notification="✅ Готово"
)
```

**Incorrect (Telegram/aiogram style):**
```python
await event.answer()  # Does NOT exist in maxapi
```

### Chat vs Channel Detection

Both have `type: "chat"`. Differentiate by checking the `link` field:

```python
chat = await bot.get_chat_by_id(id=chat_id)
link = getattr(chat, 'link', None)
if link:
    # This is a channel (has public link)
else:
    # This is a regular chat
```

### Sticker Attachment Structure

```python
attachment.type == "sticker"
attachment.payload.code      # Unique sticker code
attachment.payload.url       # Direct image URL
attachment.payload.width     # Width in pixels
attachment.payload.height    # Height in pixels
```

**Note:** Attachment can be either an object or a dictionary - handle both cases.

### Key Event Fields

```python
# Common fields
event.from_user.user_id      # User ID
event.chat_id                # Chat ID (varies by event type)
event.callback.payload       # Callback button payload

# For bot_started
event.bot                    # Bot instance

# For message_created
event.message                # Message object
event.message.body           # Message body
event.message.body.attachments  # List of attachments
```

---

## Code Style Guidelines

- **Language:** Russian for UI text, English for code and comments
- **Docstrings:** Russian, Google-style format
- **String formatting:** f-strings preferred
- **Import order:** stdlib, third-party, local modules
- **Logging:** Use `logging.getLogger(__name__)` in each module

### HTML Formatting in Messages

MAX supports HTML parse mode:
```python
from maxapi.enums.parse_mode import ParseMode

await event.bot.send_message(
    chat_id=chat_id,
    text="<b>Bold</b> and <code>code</code>",
    parse_mode=ParseMode.HTML
)
```

---

## Testing Strategy

**No automated tests** are currently implemented. Manual testing workflow:

1. **Personal chat test:**
   - Start bot → check welcome message
   - Click all 4 buttons → verify responses
   - Send sticker → verify sticker info

2. **Group chat test:**
   - Add bot to group
   - Click "Chat" button → verify chat_id, title, participant count

3. **Channel test:**
   - Add bot as admin to channel
   - Click "Channel" button → verify channel_id, link

---

## Security Considerations

1. **Token Protection:**
   - BOT_TOKEN is stored in `.env` (gitignored)
   - Never commit tokens to version control
   - Token provides full bot access - treat as secret

2. **Input Validation:**
   - Callback payloads are checked against known values
   - Unknown payloads are logged and return error message

3. **Spam Protection:**
   - Duplicate callback detection in callbacks.py (2 second timeout)
   - Same payload from same chat within 2 seconds is ignored

4. **No User Data Storage:**
   - Bot does not persist any user data
   - All information is retrieved in real-time from API

---

## Documentation Links

- [MAX Bot API Documentation](https://dev.max.ru/docs-api)
- [maxapi Python Library](https://github.com/max-messenger/max-botapi-python)
- [MAX Business Portal](https://business.max.ru) (requires registered organization)

---

## Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "BOT_TOKEN not found" | Missing .env file or variable | Create .env with `BOT_TOKEN=your_token` |
| Callback not responding | Using `event.answer()` instead of `event.bot.send_callback()` | Use correct MAX API method |
| Channel detection fails | Checking `type` field instead of `link` | Check `link` field presence |
| Sticker not detected | Attachment structure varies | Handle both object and dict formats |

---

## Lesson Learned

- MAX API для проверки участников канала требует внутренний числовой `chat_id`, например `-72143469522347`, а не публичный biz-ID вида `id752703975446_biz`.
- Публичный `CHANNEL_ID` и `CHANNEL_LINK` нужны для пользовательской ссылки на канал, но endpoint `/chats/{chatId}/members` должен использовать `CHANNEL_CHAT_ID`.
- Рабочая проверка подписки выполняется через `GET https://platform-api2.max.ru/chats/{CHANNEL_CHAT_ID}/members?user_ids={user_id}` с raw-token в заголовке `Authorization`.

---

## Inline Keyboard Layout

Main menu structure (from `keyboards/main_menu.py`):

```
┌─────────────────┬─────────────────┐
│ 💬 Chat         │ 📣 Channel      │  payload: get_chat_id / get_channel_id
├─────────────────┼─────────────────┤
│ 👤 User         │ 🤖 Bot          │  payload: get_user_id / get_bot_id
├─────────────────┴─────────────────┤
│ 🎟 Sticker                         │  payload: get_sticker_info
├─────────────────┴─────────────────┤
│ 🔍 Harvest ID                       │  payload: harvest_menu / harvest_by_link / harvest_by_message / harvest_bot_id
└───────────────────────────────────┘
```

---

*Last updated: 2026-03-18*

---

## Правила внедрения подписки (v1)

### Контекст

- MaxIDBot — бот для мессенджера MAX на Python 3.10+ с библиотекой `maxapi` 0.9.16.
- Бот является аналогом `@IDd_Helper_Bot` и возвращает ID пользователей, ботов, чатов, каналов и стикеров.
- Основная структура проекта: `bot.py`, `config.py`, `handlers/`, `keyboards/`.
- UI и комментарии в коде пишутся на русском языке.
- API base для проверки подписки: `https://platform-api2.max.ru`.
- Авторизация в MAX API выполняется через HTTP-заголовок `Authorization`.
- База данных: SQLite через `aiosqlite`, таблица `users` с полями `user_id`, `usage_count`, `is_subscribed`, `last_check`.
- Для проверки подписки на канал использовать внутренний числовой `CHANNEL_CHAT_ID`, а не публичный `CHANNEL_ID` вида `id..._biz`. Публичный ID подходит для ссылки пользователю, но `GET /chats/{chatId}/members` работает с внутренним chat ID канала.

### Бизнес-правила

1. Любой пользователь получает ровно 1 бесплатный запрос: любая кнопка ID, стикер или пересланное сообщение.
2. Первый запрос переводит `usage_count` из `0` в `1` и не требует проверки подписки.
3. Со второго запроса, когда `usage_count >= 1`, пользователь должен быть подписан на канал `CHANNEL_ID`.
4. Проверка подписки выполняется через `GET https://platform-api2.max.ru/chats/{CHANNEL_CHAT_ID}/members?user_ids={user_id}`.
5. Бот должен быть администратором в канале, чтобы проверять участников.
6. В ответе API нужно искать текущий `user_id` в массиве участников.
7. Если API проверки подписки недоступен, вернул timeout, `403` или `5xx`, пользователь считается подписанным, запрос пропускается, а в лог пишется предупреждение.
8. Результат проверки подписки кэшируется на уровне пользователя на 5 минут через поле `last_check`.
9. Если подписка неактивна, бот отправляет сообщение с inline-кнопкой-ссылкой на канал и прерывает выполнение исходного хендлера.
10. Если пользователь отписался, middleware должен обнаружить это при следующей проверке после истечения кэша и заблокировать доступ.
11. Повторная подписка должна автоматически восстановить доступ при следующем запросе.

### Запреты

- Не ломать существующую логику резолверов в `handlers/callbacks.py`.
- Все изменения в проверке доступа внедрять через middleware или декоратор, а не через переписывание ID-логики.
- Не оборачивать `/start`, `/help` и `bot_started` проверкой подписки.
- Не хардкодить `CHANNEL_ID` и `CHANNEL_LINK` в обработчиках: использовать значения из `config.py` и `.env`.
- Не удалять старый API-резолвер ссылок на каналы.
- Для ссылок вида `max.ru/id\d+_biz` добавить только fallback-regex поверх существующей логики.
- Не использовать двойные кавычки внутри русских комментариев без необходимости.

---

## Admin Panel Rules

1. Все HTTP-запросы к API MAX должны идти через единый адаптер для контроля Rate Limits (30 rps [3]).
2. Рассылки должны выполняться строго в фоновых задачах через Celery, чтобы не блокировать работу бота.
3. Доступ к панели только для `OWNER_ID` из `.env`.
