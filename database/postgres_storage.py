"""
Синхронизация состояния пользователя с PostgreSQL админ-панели.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import psycopg2
from psycopg2.extras import RealDictCursor


logger = logging.getLogger(__name__)
ALLOWED_DISCOVERED_ENTITY_TYPES = {"user", "chat", "bot"}


def _database_url() -> str | None:
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    db_name = os.getenv("POSTGRES_DB")
    if not db_name:
        return None

    user = os.getenv("POSTGRES_USER", "maxadmin")
    password = quote_plus(os.getenv("POSTGRES_PASSWORD", "maxadmin_pass"))
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def _connect():
    url = _database_url()
    if not url:
        return None
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


def _get_admin_user_state_sync(user_id: int) -> dict[str, Any] | None:
    connection = _connect()
    if connection is None:
        return None

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT user_id, is_subscribed, is_banned
                    FROM users
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None
    finally:
        connection.close()


def _ensure_discovered_entities_table_sync(connection) -> None:
    """Создает таблицу найденных объектов, если она отсутствует."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS discovered_entities (
                id SERIAL PRIMARY KEY,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                discovered_by_user_id BIGINT NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def _save_discovered_entity_sync(
    *,
    entity_id: str,
    entity_type: str,
    discovered_by_user_id: int,
) -> None:
    connection = _connect()
    if connection is None:
        return

    normalized_type = entity_type.strip().lower()
    if normalized_type not in ALLOWED_DISCOVERED_ENTITY_TYPES:
        raise ValueError(f"Unsupported discovered entity type: {entity_type}")

    try:
        with connection:
            _ensure_discovered_entities_table_sync(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO discovered_entities (
                        entity_id,
                        entity_type,
                        discovered_by_user_id
                    )
                    VALUES (%s, %s, %s)
                    """,
                    (
                        str(entity_id),
                        normalized_type,
                        int(discovered_by_user_id),
                    ),
                )
    finally:
        connection.close()


def _upsert_admin_user_sync(
    user_id: int,
    *,
    is_subscribed: bool | None = None,
    last_activity: datetime | None = None,
) -> None:
    connection = _connect()
    if connection is None:
        return

    last_activity = last_activity or datetime.now(timezone.utc)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        user_id,
                        is_subscribed,
                        is_banned,
                        last_activity
                    )
                    VALUES (%s, COALESCE(%s, false), false, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        is_subscribed = COALESCE(%s, users.is_subscribed),
                        last_activity = EXCLUDED.last_activity
                    """,
                    (user_id, is_subscribed, last_activity, is_subscribed),
                )
    finally:
        connection.close()


async def get_admin_user_state(user_id: int) -> dict[str, Any] | None:
    """Возвращает состояние пользователя из PostgreSQL или None."""
    try:
        return await asyncio.to_thread(_get_admin_user_state_sync, user_id)
    except Exception:
        logger.exception("Не удалось прочитать пользователя из PostgreSQL")
        return None


async def upsert_admin_user(
    user_id: int,
    *,
    is_subscribed: bool | None = None,
) -> None:
    """Создает или обновляет пользователя в PostgreSQL без блокировки polling."""
    try:
        await asyncio.to_thread(
            _upsert_admin_user_sync,
            user_id,
            is_subscribed=is_subscribed,
        )
    except Exception:
        logger.exception("Не удалось синхронизировать пользователя с PostgreSQL")


async def save_discovered_entity(
    *,
    entity_id: str,
    entity_type: str,
    discovered_by_user_id: int,
) -> None:
    """Сохраняет найденный объект ID-Harvester в PostgreSQL."""
    try:
        await asyncio.to_thread(
            _save_discovered_entity_sync,
            entity_id=entity_id,
            entity_type=entity_type,
            discovered_by_user_id=discovered_by_user_id,
        )
    except Exception:
        logger.exception("Не удалось сохранить найденный объект в PostgreSQL")
