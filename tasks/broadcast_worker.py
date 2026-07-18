"""
Фоновая рассылка через один async-task без Celery/Redis/PostgreSQL.
"""
import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime
from typing import Any

import httpx
from maxapi.enums.parse_mode import TextFormat

from config import API_BASE, BOT_TOKEN, BROADCAST_LIVE_ENABLED
from database.admin_storage import (
    add_broadcast_recipients,
    get_broadcast,
    get_broadcast_recipients,
    get_bot_users,
    update_broadcast,
    update_recipient_status,
)

logger = logging.getLogger(__name__)

# Ограничение MAX API — 30 RPS на бота. Берём консервативный предел <= 4 сообщ/сек,
# чтобы оставить запас под обычные ответы бота во время рассылки.
BROADCAST_RATE_LIMIT = 4
BROADCAST_MAX_RETRIES = 3
BROADCAST_RETRY_BACKOFF_BASE = 1
BROADCAST_RETRY_BACKOFF_MAX = 60
# Ограниченное время одной отправки, чтобы рассылка не зависала навечно.
BROADCAST_SEND_TIMEOUT = 15
BROADCAST_PROGRESS_UPDATE_INTERVAL = 5
BROADCAST_PROGRESS_UPDATE_EVERY = 25


class BroadcastWorker:
    """Управляет одной активной рассылкой."""

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._stop_flags: dict[int, bool] = {}

    def is_running(self, broadcast_id: int) -> bool:
        task = self._tasks.get(broadcast_id)
        return task is not None and not task.done()

    def start(self, broadcast_id: int, bot: Any) -> None:
        if self.is_running(broadcast_id):
            raise RuntimeError("Рассылка уже запущена")

        self._stop_flags[broadcast_id] = False
        task = asyncio.create_task(self._run(broadcast_id, bot))
        self._tasks[broadcast_id] = task

    def stop(self, broadcast_id: int) -> None:
        self._stop_flags[broadcast_id] = True
        task = self._tasks.get(broadcast_id)
        if task and not task.done():
            task.cancel()

    async def _run(self, broadcast_id: int, bot: Any) -> None:
        try:
            broadcast = get_broadcast(broadcast_id)
            if broadcast is None:
                logger.error("Рассылка не найдена: %s", broadcast_id)
                return

            recipients = get_broadcast_recipients(broadcast_id)
            if not recipients:
                recipients = [{"user_id": uid} for uid in get_bot_users()]
                add_broadcast_recipients(broadcast_id, [r["user_id"] for r in recipients])

            total = len(recipients)
            update_broadcast(
                broadcast_id,
                status="running",
                total=total,
                started_at=datetime.utcnow().isoformat(),
            )

            sent = 0
            failed = 0
            last_progress_update = time.time()
            last_progress_count = 0

            attachment = await self._build_attachment(broadcast)

            for index, recipient in enumerate(recipients, start=1):
                if self._stop_flags.get(broadcast_id):
                    update_broadcast(broadcast_id, status="interrupted")
                    return

                user_id = recipient["user_id"]
                success = await self._send_with_retries(
                    broadcast_id=broadcast_id,
                    bot=bot,
                    user_id=user_id,
                    broadcast=broadcast,
                    attachment=attachment,
                )

                if success:
                    sent += 1
                    update_recipient_status(broadcast_id, user_id, status="sent")
                else:
                    failed += 1
                    update_recipient_status(broadcast_id, user_id, status="failed")

                update_broadcast(
                    broadcast_id,
                    sent=sent,
                    failed=failed,
                )

                if (
                    time.time() - last_progress_update >= BROADCAST_PROGRESS_UPDATE_INTERVAL
                    or (index - last_progress_count) >= BROADCAST_PROGRESS_UPDATE_EVERY
                ):
                    last_progress_update = time.time()
                    last_progress_count = index

                await asyncio.sleep(1.0 / BROADCAST_RATE_LIMIT)

            status = "completed" if not self._stop_flags.get(broadcast_id) else "interrupted"
            update_broadcast(
                broadcast_id,
                status=status,
                finished_at=datetime.utcnow().isoformat(),
            )

        except asyncio.CancelledError:
            update_broadcast(
                broadcast_id,
                status="interrupted",
                finished_at=datetime.utcnow().isoformat(),
            )
        except Exception as exc:
            # Не логируем полный текст исключения: в нём может быть токен/секретный URL.
            logger.error("Ошибка рассылки %s (код %s)", broadcast_id, self._extract_status_code(exc))
            update_broadcast(
                broadcast_id,
                status="interrupted",
                finished_at=datetime.utcnow().isoformat(),
            )
        finally:
            self._tasks.pop(broadcast_id, None)
            self._stop_flags.pop(broadcast_id, None)

    async def _build_attachment(self, broadcast: dict[str, Any]) -> list[dict[str, Any]] | None:
        image_file_id = broadcast.get("image_file_id")
        if not image_file_id:
            return None

        try:
            payload = json.loads(image_file_id)
            if not isinstance(payload, dict):
                payload = {"token": str(image_file_id)}
        except json.JSONDecodeError:
            payload = {"token": str(image_file_id)}

        return [
            {
                "type": broadcast.get("image_content_type", "image").split("/")[0],
                "payload": payload,
            }
        ]

    async def _send_with_retries(
        self,
        *,
        broadcast_id: int,
        bot: Any,
        user_id: int,
        broadcast: dict[str, Any],
        attachment: list[dict[str, Any]] | None,
    ) -> bool:
        text = broadcast["text"]
        text_format = broadcast.get("format", "markdown")
        button_text = broadcast.get("button_text")
        button_url = broadcast.get("button_url")

        for attempt in range(1, BROADCAST_MAX_RETRIES + 1):
            try:
                await self._send_message(
                    bot=bot,
                    user_id=user_id,
                    text=text,
                    text_format=text_format,
                    attachment=attachment,
                    button_text=button_text,
                    button_url=button_url,
                )
                return True
            except asyncio.TimeoutError:
                # Истек BROADCAST_SEND_TIMEOUT — повторяем с backoff, не фейлим сразу.
                status_code = None
                error_text = "timeout"
            except RuntimeError as exc:
                error_text = str(exc)
                if "401" in error_text or "403" in error_text:
                    logger.error("Системная ошибка рассылки (401/403), остановка")
                    update_broadcast(broadcast_id, status="interrupted")
                    raise
                update_recipient_status(
                    broadcast_id,
                    user_id,
                    status="failed",
                    attempts=attempt,
                    error_code="runtime",
                    error_text=error_text,
                )
                return False
            except Exception as exc:
                error_text = str(exc)
                status_code = self._extract_status_code(exc)
                if status_code in (401, 403):
                    logger.error("Системная ошибка рассылки (401/403), остановка")
                    update_broadcast(broadcast_id, status="interrupted")
                    raise
                if status_code in (404, 422):
                    update_recipient_status(
                        broadcast_id,
                        user_id,
                        status="skipped",
                        attempts=attempt,
                        error_code=str(status_code),
                        error_text=error_text,
                    )
                    return False

                update_recipient_status(
                    broadcast_id,
                    user_id,
                    status="pending",
                    attempts=attempt,
                    error_code=str(status_code) if status_code else "error",
                    error_text=error_text,
                )
                # 429 (Too Many Requests): уважаем Retry-After, иначе экспоненциальный backoff.
                if status_code == 429:
                    retry_after = self._extract_retry_after(exc)
                    delay = retry_after if retry_after is not None else min(
                        BROADCAST_RETRY_BACKOFF_BASE * (2 ** (attempt - 1)),
                        BROADCAST_RETRY_BACKOFF_MAX,
                    )
                    await asyncio.sleep(delay)
                    continue
                await asyncio.sleep(min(
                    BROADCAST_RETRY_BACKOFF_BASE * (2 ** (attempt - 1)),
                    BROADCAST_RETRY_BACKOFF_MAX,
                ))

        return False

    async def _send_message(
        self,
        *,
        bot: Any,
        user_id: int,
        text: str,
        text_format: str,
        attachment: list[dict[str, Any]] | None,
        button_text: str | None,
        button_url: str | None,
    ) -> None:
        attachments = []
        if attachment:
            attachments.extend(attachment)

        inline_keyboard = None
        if button_text and button_url:
            from maxapi.types import CallbackButton, LinkButton
            from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
            builder = InlineKeyboardBuilder()
            builder.row(LinkButton(text=button_text, url=button_url))
            inline_keyboard = builder.as_markup()

        if inline_keyboard:
            attachments.append(inline_keyboard)

        format_mode = TextFormat.MARKDOWN if text_format == "markdown" else None

        # MAX API принимает user_id как параметр личного диалога (см. maxapi
        # send_message: elif self.user_id: params["user_id"] = self.user_id).
        # users-таблица хранит именно user_id, поэтому шлём по user_id.
        await asyncio.wait_for(
            bot.send_message(
                user_id=user_id,
                text=text,
                attachments=attachments if attachments else None,
                format=format_mode,
            ),
            timeout=BROADCAST_SEND_TIMEOUT,
        )

    def _extract_status_code(self, exc: BaseException) -> int | None:
        status_code = getattr(exc, "status_code", None)
        if status_code is not None:
            return int(status_code)

        response = getattr(exc, "response", None)
        if response is not None:
            return int(getattr(response, "status_code", 0) or 0)

        text = str(exc)
        for part in text.split():
            if part.isdigit():
                return int(part)
        return None

    def _extract_retry_after(self, exc: BaseException) -> int | None:
        """Извлекает Retry-After (сек) из ответа 429, если он есть."""
        response = getattr(exc, "response", None)
        if response is None:
            return None
        headers = getattr(response, "headers", None)
        if not headers:
            return None
        raw = None
        if isinstance(headers, dict):
            raw = headers.get("Retry-After") or headers.get("retry-after")
        else:
            raw = getattr(headers, "get", lambda *_: None)("Retry-After")
        if raw is None:
            return None
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return None


worker = BroadcastWorker()


async def start_broadcast(broadcast_id: int, bot: Any) -> None:
    """Запускает рассылку в фоне."""
    if not BROADCAST_LIVE_ENABLED:
        raise RuntimeError("Рассылки отключены (BROADCAST_LIVE_ENABLED=false)")
    worker.start(broadcast_id, bot)


def stop_broadcast(broadcast_id: int) -> None:
    """Останавливает рассылку."""
    worker.stop(broadcast_id)


def mark_running_as_interrupted() -> int:
    """При старте бота переводит рассылки в статусе running в interrupted.

    Защита от «зомби»-рассылок после падения/перезапуска процесса: в прошлой
    жизни воркер уже не работает, поэтому running считается прерванным.
    Возвращает число изменённых записей.
    """
    from database.admin_storage import DB_PATH

    updated = 0
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute(
                "UPDATE broadcasts SET status='interrupted', "
                "finished_at=datetime('now') WHERE status='running'"
            )
            updated = cur.rowcount
            conn.commit()
    except Exception as exc:  # pragma: no cover - защита запуска
        logger.error("Не удалось восстановить статусы рассылок: %s", type(exc).__name__)
    return updated
