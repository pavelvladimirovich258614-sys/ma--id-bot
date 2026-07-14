"""Celery-задачи массовых рассылок через MAX API."""
import json
import os
import random
import time
from typing import Iterable

import httpx
from celery import Celery, chord, group
from sqlalchemy import update

from app.models.database import SessionLocal
from app.models.tables import Broadcast, EventLog


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MAX_RPS_RATE_LIMIT = "30/s"

celery_app = Celery(
    "maxidbot_admin",
    broker=REDIS_URL,
    backend=REDIS_URL,
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    result_expires=86400,
    task_routes={"app.tasks.broadcast.*": {"queue": "broadcasts"}},
)


def _max_api_url(path: str) -> str:
    """Возвращает абсолютный URL MAX API."""
    api_base = os.getenv("API_BASE", "https://platform-api2.max.ru").rstrip("/")
    return f"{api_base}{path}"


def _media_attachment(media_type: str, media_file_id: str) -> dict:
    """Формирует вложение MAX для ранее загруженного медиа."""
    try:
        payload = json.loads(media_file_id)
        if not isinstance(payload, dict):
            payload = {"token": str(media_file_id)}
    except json.JSONDecodeError:
        payload = {"token": media_file_id}

    return {
        "type": media_type,
        "payload": payload,
    }


def _upload_type_from_content_type(content_type: str | None) -> str:
    """Определяет тип загрузки MAX API по MIME type."""
    if content_type and content_type.startswith("image/"):
        return "image"
    if content_type and content_type.startswith("video/"):
        return "video"
    if content_type and content_type.startswith("audio/"):
        return "audio"
    return "file"


def upload_media_to_max(
    filename: str,
    content: bytes,
    content_type: str | None,
) -> str:
    """Загружает медиа в MAX API и возвращает token/payload для сообщения."""
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не настроен")

    upload_type = _upload_type_from_content_type(content_type)
    upload_request = httpx.post(
        _max_api_url("/uploads"),
        headers={"Authorization": token},
        params={"type": upload_type},
        timeout=15.0,
    )
    upload_request.raise_for_status()
    upload_meta = upload_request.json()
    upload_url = upload_meta.get("url")
    if not upload_url:
        raise RuntimeError("MAX API не вернул URL для загрузки медиа")

    upload_response = httpx.post(
        upload_url,
        files={"data": (filename, content, content_type or "application/octet-stream")},
        timeout=60.0,
    )
    upload_response.raise_for_status()
    payload = upload_response.json()

    attachment_token = payload.get("token") or upload_meta.get("token")
    if attachment_token:
        return str(attachment_token)

    if payload:
        return json.dumps(payload, ensure_ascii=False)

    raise RuntimeError("MAX API не вернул payload/token после загрузки медиа")


def _response_contains_attachment_not_ready(response: httpx.Response) -> bool:
    """Проверяет временную ошибку обработки загруженного файла."""
    try:
        payload = response.json()
    except ValueError:
        return False
    return payload.get("code") == "attachment.not.ready"


def _raise_for_status_with_body(response: httpx.Response) -> None:
    """Добавляет тело ответа MAX API в ошибку доставки."""
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        body = response.text[:500]
        raise RuntimeError(
            f"MAX API вернул HTTP {response.status_code}: {body}"
        ) from error


def _send_message_to_max(
    user_id: int,
    text: str,
    media_type: str | None = None,
    media_file_id: str | None = None,
) -> None:
    """Отправляет сообщение пользователю через единый MAX API adapter."""
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не настроен")

    params = {"user_id": user_id}
    payload = {"text": text}
    if media_type and media_file_id:
        payload["attachments"] = [_media_attachment(media_type, media_file_id)]

    for attempt in range(4):
        response = httpx.post(
            _max_api_url("/messages"),
            headers={"Authorization": token},
            params=params,
            json=payload,
            timeout=15.0,
        )
        if response.status_code < 400:
            return
        if (
            media_type
            and media_file_id
            and _response_contains_attachment_not_ready(response)
            and attempt < 3
        ):
            time.sleep(2 ** attempt)
            continue
        _raise_for_status_with_body(response)


def _log_delivery_error(
    user_id: int,
    broadcast_id: int | None,
    error: Exception,
) -> None:
    """Пишет ошибку доставки в events_log."""
    with SessionLocal() as session:
        session.add(
            EventLog(
                user_id=user_id,
                event_type="broadcast_delivery_failed",
                details=(
                    f"broadcast_id={broadcast_id}; "
                    f"error={type(error).__name__}: {error}"
                ),
            )
        )
        session.commit()


def _increment_sent_count(broadcast_id: int | None) -> None:
    """Атомарно увеличивает счетчик доставленных сообщений."""
    if broadcast_id is None:
        return

    with SessionLocal() as session:
        session.execute(
            update(Broadcast)
            .where(Broadcast.id == broadcast_id)
            .values(sent_count=Broadcast.sent_count + 1)
        )
        session.commit()


@celery_app.task(
    bind=True,
    name="app.tasks.broadcast.send_broadcast_task",
    rate_limit=MAX_RPS_RATE_LIMIT,
    autoretry_for=(httpx.TimeoutException, httpx.TransportError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def send_broadcast_task(
    self,
    user_id: int,
    text: str,
    broadcast_id: int | None = None,
    media_type: str | None = None,
    media_file_id: str | None = None,
) -> dict[str, int | bool | str | None]:
    """Отправляет одно сообщение рассылки пользователю MAX."""
    time.sleep(random.uniform(0.05, 0.1))

    try:
        _send_message_to_max(
            user_id=user_id,
            text=text,
            media_type=media_type,
            media_file_id=media_file_id,
        )
    except Exception as error:
        _log_delivery_error(
            user_id=user_id,
            broadcast_id=broadcast_id,
            error=error,
        )
        return {
            "user_id": user_id,
            "broadcast_id": broadcast_id,
            "delivered": False,
            "error": str(error),
        }

    _increment_sent_count(broadcast_id)
    return {
        "user_id": user_id,
        "broadcast_id": broadcast_id,
        "delivered": True,
        "error": None,
    }


@celery_app.task(name="app.tasks.broadcast.finalize_broadcast_task")
def finalize_broadcast_task(
    results: list[dict[str, int | bool | str | None]],
    broadcast_id: int,
) -> dict[str, int | str]:
    """Фиксирует финальный статус рассылки после выполнения группы задач."""
    delivered_count = sum(1 for result in results if result.get("delivered"))
    status = "completed"

    with SessionLocal() as session:
        session.execute(
            update(Broadcast)
            .where(Broadcast.id == broadcast_id)
            .values(status=status, sent_count=delivered_count)
        )
        session.commit()

    return {
        "broadcast_id": broadcast_id,
        "status": status,
        "sent_count": delivered_count,
        "total_count": len(results),
    }


def enqueue_broadcast(
    broadcast_id: int,
    user_ids: Iterable[int],
    text: str,
    media_type: str | None = None,
    media_file_id: str | None = None,
) -> str:
    """Ставит рассылку в Redis-backed Celery очередь и сразу возвращает task id."""
    delivery_tasks = group(
        send_broadcast_task.s(
            user_id=int(user_id),
            text=text,
            broadcast_id=broadcast_id,
            media_type=media_type,
            media_file_id=media_file_id,
        )
        for user_id in user_ids
    )
    result = chord(delivery_tasks)(
        finalize_broadcast_task.s(broadcast_id=broadcast_id)
    )
    return result.id
