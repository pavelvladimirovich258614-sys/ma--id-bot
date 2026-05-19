"""Синхронизация подписчиков канала MAX с PostgreSQL."""
import os
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.models.tables import EventLog, User


SYNC_TTL_SECONDS = 300
_last_sync_at = 0.0


@dataclass(frozen=True)
class SubscriptionSyncReport:
    """Краткий отчет синхронизации подписчиков."""

    known_before: int
    real_members: int
    updated_rows: int
    inserted_rows: int
    known_after: int


def _max_api_url(path: str) -> str:
    api_base = os.getenv("API_BASE", "https://platform-api.max.ru").rstrip("/")
    return f"{api_base}{path}"


def _extract_members(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("members", "users", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _extract_next(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("marker", "next_marker", "nextMarker", "cursor", "next_cursor", "nextCursor"):
        value = payload.get(key)
        if value:
            return str(value)
    paging = payload.get("paging")
    if isinstance(paging, dict):
        for key in ("marker", "next_marker", "cursor", "next_cursor"):
            value = paging.get(key)
            if value:
                return str(value)
    return None


def _member_user_id(member: object) -> int | None:
    if isinstance(member, int):
        return member
    if isinstance(member, str) and member.lstrip("-").isdigit():
        return int(member)
    if not isinstance(member, dict):
        return None

    user = member.get("user") or member.get("profile")
    value = (
        member.get("user_id")
        or member.get("id")
        or member.get("userId")
        or (user.get("user_id") if isinstance(user, dict) else None)
        or (user.get("id") if isinstance(user, dict) else None)
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_channel_member_ids() -> set[int]:
    """Получает актуальные user_id участников канала из MAX API."""
    token = os.getenv("BOT_TOKEN")
    channel_chat_id = os.getenv("CHANNEL_CHAT_ID")
    if not token or not channel_chat_id:
        raise RuntimeError("BOT_TOKEN или CHANNEL_CHAT_ID не настроены")

    members: set[int] = set()
    marker: str | None = None
    seen_markers: set[str] = set()

    with httpx.Client(timeout=30.0) as client:
        while True:
            params = {"count": 100}
            if marker:
                params["marker"] = marker
            response = client.get(
                _max_api_url(f"/chats/{channel_chat_id}/members"),
                headers={"Authorization": token},
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
            page_members = _extract_members(payload)

            for member in page_members:
                user_id = _member_user_id(member)
                if user_id is not None:
                    members.add(user_id)

            marker = _extract_next(payload)
            if not marker or marker in seen_markers or not page_members:
                break
            seen_markers.add(marker)

    return members


def sync_subscriptions(session: Session) -> SubscriptionSyncReport:
    """Делает PostgreSQL источником актуальных подписчиков канала."""
    real_member_ids = fetch_channel_member_ids()
    known_before = (
        session.query(func.count(User.user_id))
        .filter(User.is_subscribed.is_(True))
        .scalar()
        or 0
    )
    existing_ids = {
        row[0]
        for row in session.query(User.user_id).all()
    }

    inserted_rows = 0
    for user_id in real_member_ids - existing_ids:
        session.add(User(user_id=user_id, is_subscribed=True))
        inserted_rows += 1
    session.flush()

    if real_member_ids:
        updated_rows = (
            session.execute(
                update(User).values(
                    is_subscribed=User.user_id.in_(real_member_ids)
                )
            ).rowcount
            or 0
        )
    else:
        updated_rows = (
            session.execute(update(User).values(is_subscribed=False)).rowcount
            or 0
        )

    session.add(
        EventLog(
            event_type="subscription_sync",
            details=(
                f"known_before={known_before}; real_members={len(real_member_ids)}; "
                f"updated_rows={updated_rows}; inserted_rows={inserted_rows}"
            ),
        )
    )
    session.commit()

    known_after = (
        session.query(func.count(User.user_id))
        .filter(User.is_subscribed.is_(True))
        .scalar()
        or 0
    )
    return SubscriptionSyncReport(
        known_before=known_before,
        real_members=len(real_member_ids),
        updated_rows=updated_rows,
        inserted_rows=inserted_rows,
        known_after=known_after,
    )


def ensure_recent_subscription_sync(session: Session) -> SubscriptionSyncReport | None:
    """Автоматически актуализирует подписки не чаще одного раза в 5 минут."""
    global _last_sync_at
    now = time.monotonic()
    if now - _last_sync_at < SYNC_TTL_SECONDS:
        return None

    report = sync_subscriptions(session)
    _last_sync_at = now
    return report
