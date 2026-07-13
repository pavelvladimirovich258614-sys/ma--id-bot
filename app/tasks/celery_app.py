"""Общий entrypoint Celery для фоновых задач MaxIDBot."""
from app.tasks.broadcast import celery_app

__all__ = ["celery_app"]
