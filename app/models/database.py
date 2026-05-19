"""Подключение SQLAlchemy к PostgreSQL."""
import os
from collections.abc import Generator
from urllib.parse import quote_plus

from sqlalchemy import create_engine
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
