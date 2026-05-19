"""Перенос пользователей из SQLite в PostgreSQL для админ-панели."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models.database import SessionLocal, init_models
from app.models.tables import User


ROOT_DIR = Path(__file__).resolve().parent
SQLITE_PATH = ROOT_DIR / "users.sqlite3"


def _parse_sqlite_datetime(value: str | None) -> datetime | None:
    """Парсит дату из SQLite, если она была сохранена подписочным модулем."""
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def load_sqlite_users() -> list[sqlite3.Row]:
    """Загружает пользователей из текущей SQLite-базы."""
    if not SQLITE_PATH.exists():
        raise FileNotFoundError(f"SQLite база не найдена: {SQLITE_PATH}")

    with sqlite3.connect(SQLITE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(
            """
            SELECT user_id, is_subscribed, last_check
            FROM users
            """
        )
        return cursor.fetchall()


def migrate_users() -> int:
    """Выполняет idempotent-перенос пользователей в PostgreSQL."""
    init_models()
    rows = load_sqlite_users()
    migrated_count = 0

    with SessionLocal() as session:
        for row in rows:
            user = session.get(User, int(row["user_id"]))
            if user is None:
                user = User(user_id=int(row["user_id"]))
                session.add(user)

            user.is_subscribed = bool(row["is_subscribed"])
            user.last_activity = _parse_sqlite_datetime(row["last_check"])
            migrated_count += 1

        session.commit()

    return migrated_count


if __name__ == "__main__":
    count = migrate_users()
    print(f"Перенесено пользователей: {count}")
