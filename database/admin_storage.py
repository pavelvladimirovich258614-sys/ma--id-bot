"""
Хранилище админ-панели: рассылки и получатели.
"""
import json
import os
import sqlite3
from datetime import datetime
from typing import Any

DB_PATH = os.environ.get("MAXIDBOT_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "users.sqlite3")


def init_admin_db() -> None:
    """Создает таблицы рассылок, если они еще не существуют."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                format TEXT NOT NULL DEFAULT  markdown,
                image_file_id TEXT,
                image_content_type TEXT,
                button_text TEXT,
                button_url TEXT,
                status TEXT NOT NULL DEFAULT draft,
                total INTEGER NOT NULL DEFAULT 0,
                sent INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                finished_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS broadcast_recipients (
                broadcast_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT pending,
                attempts INTEGER NOT NULL DEFAULT 0,
                error_code TEXT,
                error_text TEXT,
                sent_at TEXT,
                PRIMARY KEY (broadcast_id, user_id),
                FOREIGN KEY (broadcast_id) REFERENCES broadcasts(id)
            )
            """
        )
        conn.commit()


def create_broadcast(
    admin_user_id: int,
    text: str,
    format: str = "markdown",
    image_file_id: str | None = None,
    image_content_type: str | None = None,
    button_text: str | None = None,
    button_url: str | None = None,
) -> dict[str, Any]:
    """Создает запись рассылки и возвращает ее идентификатор."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT INTO broadcasts (
                admin_user_id, text, format, image_file_id,
                image_content_type, button_text, button_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                admin_user_id,
                text,
                format,
                image_file_id,
                image_content_type,
                button_text,
                button_url,
            ),
        )
        conn.commit()
        broadcast_id = cursor.lastrowid

    return get_broadcast(broadcast_id)


def get_broadcast(broadcast_id: int) -> dict[str, Any] | None:
    """Возвращает рассылку по идентификатору."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM broadcasts WHERE id = ?",
            (broadcast_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def update_broadcast(broadcast_id: int, **fields: Any) -> None:
    """Обновляет поля рассылки."""
    if not fields:
        return

    set_clause = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values())
    values.append(broadcast_id)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"UPDATE broadcasts SET {set_clause} WHERE id = ?", values)
        conn.commit()


def add_broadcast_recipients(broadcast_id: int, user_ids: list[int]) -> None:
    """Добавляет получателей рассылки."""
    if not user_ids:
        return

    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO broadcast_recipients (broadcast_id, user_id)
            VALUES (?, ?)
            """,
            [(broadcast_id, user_id) for user_id in user_ids],
        )
        conn.commit()


def get_broadcast_recipients(broadcast_id: int) -> list[dict[str, Any]]:
    """Возвращает список получателей рассылки."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM broadcast_recipients WHERE broadcast_id = ?",
            (broadcast_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def get_pending_recipients(broadcast_id: int) -> list[int]:
    """Возвращает user_id получателей со статусом pending."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT user_id FROM broadcast_recipients WHERE broadcast_id = ? AND status = pending",
            (broadcast_id,),
        ).fetchall()

    return [row[0] for row in rows]


def update_recipient_status(
    broadcast_id: int,
    user_id: int,
    status: str,
    attempts: int | None = None,
    error_code: str | None = None,
    error_text: str | None = None,
) -> None:
    """Обновляет статус получателя."""
    fields = {"status": status}
    if attempts is not None:
        fields["attempts"] = attempts
    if error_code is not None:
        fields["error_code"] = error_code
    if error_text is not None:
        fields["error_text"] = error_text
    if status == "sent":
        fields["sent_at"] = datetime.utcnow().isoformat()

    set_clause = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values())
    values.extend([broadcast_id, user_id])

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            f"UPDATE broadcast_recipients SET {set_clause} WHERE broadcast_id = ? AND user_id = ?",
            values,
        )
        conn.commit()


def get_bot_users() -> list[int]:
    """Возвращает уникальные user_id пользователей из таблицы users."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()

    user_ids = [row[0] for row in rows]
    unique_sorted = sorted(set(user_ids))
    return [uid for uid in unique_sorted if isinstance(uid, int) and uid > 0]


def count_bot_users() -> int:
    """Возвращает количество уникальных пользователей бота."""
    return len(get_bot_users())
