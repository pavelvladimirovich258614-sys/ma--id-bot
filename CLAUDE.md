# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MaxIDBot is a chatbot for the MAX messenger (max.ru) that retrieves IDs of various entities: users, chats, channels, bots, and stickers. It is a functional analog of Telegram's @IDd_Helper_Bot.

**Platform:** MAX Messenger (business.max.ru) - requires a verified Russian organization to create a bot.

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python bot.py

# The bot uses long polling mode by default
# Token must be set in .env file: BOT_TOKEN=your_token_here
```

## Architecture

The project uses the `maxapi` library (aiogram-like syntax) with a modular handler registration pattern:

```
bot.py (entry point)
  ├── Bot(token) + Dispatcher()
  ├── registers handlers via register_*_handlers(dp)
  └── dp.start_polling(bot)

handlers/
  ├── start.py      → bot_started event, /start command
  ├── callbacks.py  → message_callback (4 inline buttons)
  └── stickers.py   → message_created (sticker attachments)

keyboards/
  └── main_menu.py  → InlineKeyboardBuilder with 2×2 callback grid
```

**Handler Registration Pattern:** Each handler module exports a `register_*_handlers(dp)` function that registers decorators with the dispatcher. This is called from `bot.py` before starting polling.

## MAX API Specifics

- **Token authentication:** Via `Authorization` header, not query params
- **Library version:** maxapi 0.9.16 (NOT 1.3.0+ - doesn't exist on PyPI)
- **Callback response:** Use `event.bot.send_callback(callback_id, notification=...)` NOT `event.answer()`
- **Chat vs Channel:** Both have `type: "chat"`. Differentiate by checking `link` field (channels have public links)
- **Sticker attachment:** Structure is `attachment.type == "sticker"`, data in `attachment.payload` with `code`, `url`, `width`, `height`
- **Event fields:** `event.from_user.user_id`, `event.chat_id` (varies by event type), `event.callback.payload`

## Key Event Handlers

| Event | Handler | Payload/Trigger |
|-------|---------|-----------------|
| `bot_started` | handlers/start.py | User clicks "Start" button |
| `message_created` + Command('start') | handlers/start.py | /start command |
| `message_callback` | handlers/callbacks.py | Inline button clicks |
| `message_created` | handlers/stickers.py | Sticker attachments |

## Inline Keyboard Structure

```
┌─────────────────┬─────────────────┐
│ 💬 Chat        │ 📣 Channel     │
│ get_chat_id    │ get_channel_id  │
├─────────────────┼─────────────────┤
│ 👤 User        │ 🤖 Bot          │
│ get_user_id    │ get_bot_id      │
└─────────────────┴─────────────────┘
```

All buttons use `CallbackButton(text, payload)` with InlineKeyboardBuilder.

## Documentation Links

- [MAX Bot API](https://dev.max.ru/docs-api)
- [maxapi Python library](https://github.com/max-messenger/max-botapi-python)
- Full technical specification: `TZ.md`
