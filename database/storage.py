"""
SQLite-хранилище пользователей для проверки подписки.
"""
import os
from typing import Any

import aiosqlite


DB_PATH = os.path.join(
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
            )
        )
        await db.commit()

    return next_user
