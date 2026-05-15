# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MaxIDBot is a chatbot for the MAX messenger (max.ru) that retrieves IDs of various entities: users, chats, channels, bots, and stickers. It is a functional analog of Telegram's @IDd_Helper_Bot.

**Platform:** MAX Messenger (business.max.ru) — requires a verified Russian organization to create a bot.

## Development Commands

```bash
pip install -r requirements.txt   # install deps
python bot.py                      # run the bot (long polling)
```

Token must be set in `.env`: `BOT_TOKEN=your_token_here`

Optional env vars: `LOG_LEVEL` (default: `INFO`)

## Deployment

- **Docker:** `Dockerfile` uses `python:3.12-slim`
- **systemd:** `deploy/maxidbot.service` — runs from `/opt/max-id-bot` as user `bot`

## Architecture

```
bot.py              → entry point: Bot + Dispatcher, registers all handlers, starts polling
config.py           → loads BOT_TOKEN from .env, configures logging
handlers/
  start.py          → bot_started, /start, /help
  callbacks.py      → message_callback (inline button clicks)
  messages.py       → message_created (stickers, forwarded messages, channel/chat search by link/ID)
  bot_added.py      → bot_added (bot added to group chat or channel)
keyboards/
  main_menu.py      → InlineKeyboardBuilder (3-row grid) + dismiss_keyboard()
```

**Handler registration pattern:** Each handler module exports a `register_*_handlers(dp)` function called from `bot.py` before `dp.start_polling(bot)`.

### Critical Dispatcher Limitation

In `maxapi`, if multiple handlers are registered on the same event (e.g. `message_created`) and the first handler completes without error (even with a bare `return`), subsequent handlers are **not called**. This is why all `message_created` logic (stickers, forwards, channel search) lives in **one handler** in `messages.py`.

## Key Event Handlers

| Event | Handler File | Trigger |
|-------|-------------|---------|
| `bot_started` | `handlers/start.py` | User clicks "Start" |
| `message_created` + `Command('start')` | `handlers/start.py` | /start command |
| `message_created` + `Command('help')` | `handlers/start.py` | /help command |
| `message_callback` | `handlers/callbacks.py` | Inline button clicks |
| `message_created` | `handlers/messages.py` | Stickers, forwarded messages, channel/chat lookup |
| `bot_added` | `handlers/bot_added.py` | Bot added to group/channel |

## Inline Keyboard

```
┌─────────────────┬─────────────────┐
│ 💬 Чат         │ 📣 Канал        │
│ get_chat_id    │ get_channel_id  │
├─────────────────┼─────────────────┤
│ 👤 Пользователь│ 🤖 Бот          │
│ get_user_id    │ get_bot_id      │
├─────────────────┴─────────────────┤
│ 🎟 Стикер                        │
│ get_sticker_info                  │
└───────────────────────────────────┘
```

`dismiss_keyboard()` — single "Прочитано" button with `payload="dismiss"`, used on info responses to let users dismiss the message.

## Notable Patterns

- **Chats cache** (`messages.py`): TTL-based cache (60s) for `bot.get_chats()` results, used as fallback when direct API lookup fails
- **Anti-spam** (`callbacks.py`): Deduplicates identical callbacks per chat within 2-second window
- **Forwarded message deletion**: Bot deletes the original forwarded message after responding with chat/sender info
- **Channel notification**: On `bot_added` to a channel, bot sends info both to the channel and to the user's private chat
- **Parallel callback+edit** (`callbacks.py`): Uses `asyncio.gather()` to edit message and answer callback simultaneously, with fallback to sequential execution

## MAX API Specifics

- **Library version:** maxapi 0.9.16 (NOT 1.3.0+ — doesn't exist on PyPI)
- **Token auth:** Via `Authorization` header, not query params
- **Callback response:** `event.bot.send_callback(callback_id, notification=...)` — NOT `event.answer()`
- **Chat vs Channel:** Both have `type: "chat"`. Differentiate by `link` field (channels have public links)
- **Sticker attachment:** `attachment.type == "sticker"`, data in `attachment.payload` with `code`, `url`, `width`, `height`
- **Event fields:** `event.from_user.user_id`, `event.chat_id`, `event.callback.payload`

## Documentation Links

- [MAX Bot API](https://dev.max.ru/docs-api)
- [maxapi Python library](https://github.com/max-messenger/max-bot-api-python)
