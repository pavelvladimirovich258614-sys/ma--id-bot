"""Подключение SQLAlchemy к PostgreSQL."""
import os
from collections.abc import Generator
from urllib.parse import quote_plus

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Базовый класс моделей админ-панели."""


def get_database_url() -> str:
    """Собирает URL PostgreSQL из переменных окружения."""
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    user = os.getenv("POSTGRES_USER", "maxidbot")
    password = quote_plus(os.getenv("POSTGRES_PASSWORD", "maxidbot"))
    db_name = os.getenv("POSTGRES_DB", "maxidbot")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"


engine = create_engine(get_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Generator[Session, None, None]:
    """Создает SQLAlchemy session для FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_models() -> None:
    """Создает таблицы первой фазы."""
    from app.models import tables  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_broadcast_media_columns()


def _ensure_broadcast_media_columns() -> None:
    """Добавляет новые колонки рассылок в уже развернутых базах."""
    inspector = inspect(engine)
    if not inspector.has_table("broadcasts"):
        return

    columns = {column["name"] for column in inspector.get_columns("broadcasts")}
    statements = []
    if "media_type" not in columns:
        statements.append("ALTER TABLE broadcasts ADD COLUMN media_type VARCHAR(30)")
    if "media_file_id" not in columns:
        statements.append("ALTER TABLE broadcasts ADD COLUMN media_file_id VARCHAR(255)")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
