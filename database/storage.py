"""
SQLite-хранилище пользователей для проверки подписки.
"""
import os
from typing import Any

import aiosqlite


DB_PATH = os.environ.get("MAXIDBOT_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "users.sqlite3"
)

DEFAULT_USER = {
    "usage_count": 0,
    "is_subscribed": 0,
    "last_check": None,
    "subscription_source": "unknown",
}


async def init_db() -> None:
    """Создает таблицу пользователей, если она еще не существует."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                usage_count INTEGER DEFAULT 0,
                is_subscribed INTEGER DEFAULT 0,
                last_check TEXT,
                subscription_source TEXT DEFAULT 'unknown'
            )
            """
        )
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "subscription_source" not in columns:
            await db.execute(
                """
                ALTER TABLE users
                ADD COLUMN subscription_source TEXT DEFAULT 'unknown'
                """
            )
        await db.commit()


async def get_user(user_id: int) -> dict[str, Any]:
    """
    Возвращает данные пользователя или значения по умолчанию.

    Args:
        user_id: ID пользователя MAX.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                user_id,
                usage_count,
                is_subscribed,
                last_check,
                subscription_source
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )
        row = await cursor.fetchone()

    if row is None:
        return {"user_id": user_id, **DEFAULT_USER}

    return dict(row)


async def update_user(user_id: int, **fields: Any) -> dict[str, Any]:
    """
    Обновляет или создает пользователя через UPSERT.

    Args:
        user_id: ID пользователя MAX.
        **fields: Поля `usage_count`, `is_subscribed`, `last_check`.
    """
    current_user = await get_user(user_id)
    next_user = {
        "user_id": user_id,
        "usage_count": fields.get(
            "usage_count",
            current_user["usage_count"]
        ),
        "is_subscribed": fields.get(
            "is_subscribed",
            current_user["is_subscribed"]
        ),
        "last_check": fields.get("last_check", current_user["last_check"]),
        "subscription_source": fields.get(
            "subscription_source",
            current_user["subscription_source"]
        ),
    }

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (
                user_id,
                usage_count,
                is_subscribed,
                last_check,
                subscription_source
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                usage_count = excluded.usage_count,
                is_subscribed = excluded.is_subscribed,
                last_check = excluded.last_check,
                subscription_source = excluded.subscription_source
            """,
            (
                next_user["user_id"],
                next_user["usage_count"],
                next_user["is_subscribed"],
                next_user["last_check"],
                next_user["subscription_source"],
            ),
        )
        await db.commit()

    return next_user


def init_public_link_cache() -> None:
    """Создает таблицу кэша публичных ссылок MAX."""
    import sqlite3

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS known_public_max_links (
                normalized_link TEXT PRIMARY KEY,
                raw_channel_id INTEGER NOT NULL,
                bot_chat_id INTEGER NOT NULL,
                title TEXT,
                participants_count INTEGER,
                source TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_cached_public_link(normalized_link: str) -> dict[str, Any] | None:
    """Возвращает кэшированную запись публичной ссылки."""
    import sqlite3

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM known_public_max_links WHERE normalized_link = ?",
            (normalized_link,),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def upsert_public_link_cache(record: dict[str, Any]) -> None:
    """Сохраняет или обновляет кэш публичной ссылки."""
    import sqlite3

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO known_public_max_links (
                normalized_link,
                raw_channel_id,
                bot_chat_id,
                title,
                participants_count,
                source,
                first_seen_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_link) DO UPDATE SET
                raw_channel_id = excluded.raw_channel_id,
                bot_chat_id = excluded.bot_chat_id,
                title = excluded.title,
                participants_count = excluded.participants_count,
                last_seen_at = excluded.last_seen_at
            """,
            (
                record["normalized_link"],
                record["raw_channel_id"],
                record["bot_chat_id"],
                record.get("title"),
                record.get("participants_count"),
                record["source"],
                record["first_seen_at"],
                record["last_seen_at"],
            ),
        )
        conn.commit()
