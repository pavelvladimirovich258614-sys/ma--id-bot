"""FastAPI backend первой фазы админ-панели."""
import hashlib
import hmac
import os
import secrets
import subprocess
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.models.database import get_session, init_models
from app.models.tables import Broadcast, DiscoveredEntity, EventLog, User
from app.services.subscription_sync import ensure_recent_subscription_sync, sync_subscriptions
from app.tasks.broadcast import enqueue_broadcast, upload_media_to_max


OWNER_HEADER = "X-Owner-Id"
OWNER_COOKIE = "owner_id"
SESSION_COOKIE = "admin_refresh_token"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 180
templates = Jinja2Templates(directory="app/templates")


class BroadcastSendRequest(BaseModel):
    """Запрос на запуск массовой рассылки."""

    text: str = Field(min_length=1, max_length=4000)
    media_type: str | None = None
    media_file_id: str | None = None


class OwnerOnlyMiddleware(BaseHTTPMiddleware):
    """Ограничивает доступ к панели владельцем или доверенной сессией."""

    async def dispatch(self, request: Request, call_next):
        if _is_public_path(request.url.path):
            return await call_next(request)

        if not _has_any_auth_config():
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "Доступ к админ-панели не настроен"},
            )

        if not _is_authorized_request(request):
            if _wants_html(request):
                next_url = quote(str(request.url.path))
                if request.url.query:
                    next_url = quote(f"{request.url.path}?{request.url.query}")
                return RedirectResponse(
                    url=f"/login?next={next_url}",
                    status_code=status.HTTP_303_SEE_OTHER,
                )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Доступ разрешен только владельцу"},
            )

        response = await call_next(request)
        owner_id = os.getenv("OWNER_ID")
        if owner_id and request.query_params.get("owner_id") == owner_id:
            response.set_cookie(
                OWNER_COOKIE,
                owner_id,
                httponly=True,
                samesite="lax",
                max_age=SESSION_TTL_SECONDS,
            )
        return response


def _is_public_path(path: str) -> bool:
    """Определяет маршруты, доступные без авторизации."""
    return (
        path == "/login"
        or path.startswith("/static/")
        or path in {"/favicon.ico", "/healthz"}
    )


def _has_any_auth_config() -> bool:
    return bool(
        os.getenv("OWNER_ID")
        or os.getenv("ADMIN_PASSWORD")
        or os.getenv("ADMIN_PASSWORD_SHA256")
        or os.getenv("TRUSTED_ADMIN_IPS")
    )


def _is_authorized_request(request: Request) -> bool:
    if _is_trusted_ip(request):
        return True

    owner_id = os.getenv("OWNER_ID")
    request_owner_id = (
        request.headers.get(OWNER_HEADER)
        or request.query_params.get("owner_id")
        or request.cookies.get(OWNER_COOKIE)
    )
    if owner_id and request_owner_id == owner_id:
        return True

    return _is_valid_session_token(request.cookies.get(SESSION_COOKIE))


def _is_trusted_ip(request: Request) -> bool:
    trusted_ips = {
        item.strip()
        for item in os.getenv("TRUSTED_ADMIN_IPS", "").split(",")
        if item.strip()
    }
    if not trusted_ips:
        return False

    client_ip = _client_ip(request)
    return client_ip in trusted_ips


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept or "*/*" in accept


def _is_https_request(request: Request) -> bool:
    return (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
    )


def _safe_next_url(next_url: str) -> str:
    if not next_url.startswith("/") or next_url.startswith("//"):
        return "/admin"
    return next_url


def _password_matches(password: str) -> bool:
    expected_hash = os.getenv("ADMIN_PASSWORD_SHA256")
    if expected_hash:
        actual_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(actual_hash, expected_hash)

    expected_password = os.getenv("ADMIN_PASSWORD")
    if expected_password:
        return hmac.compare_digest(password, expected_password)

    return False


def _session_secret() -> str:
    return (
        os.getenv("ADMIN_SESSION_SECRET")
        or os.getenv("ADMIN_PASSWORD_SHA256")
        or os.getenv("ADMIN_PASSWORD")
        or os.getenv("OWNER_ID")
        or ""
    )


def _create_session_token() -> str:
    issued_at = int(time.time())
    expires_at = issued_at + SESSION_TTL_SECONDS
    nonce = secrets.token_urlsafe(16)
    payload = f"v1.{issued_at}.{expires_at}.{nonce}"
    signature = hmac.new(
        _session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}.{signature}"


def _is_valid_session_token(token: str | None) -> bool:
    secret = _session_secret()
    if not token or not secret:
        return False

    parts = token.split(".")
    if len(parts) != 5 or parts[0] != "v1":
        return False

    payload = ".".join(parts[:4])
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(parts[4], expected_signature):
        return False

    try:
        expires_at = int(parts[2])
    except ValueError:
        return False
    return expires_at > int(time.time())


app = FastAPI(title="MaxIDBot Admin API")
app.add_middleware(OwnerOnlyMiddleware)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
def on_startup() -> None:
    """Создает таблицы первой фазы, если они еще не существуют."""
    init_models()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Легкая проверка работоспособности admin-api."""
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/admin"):
    """Показывает форму входа администратора."""
    return templates.TemplateResponse(
        request=request,
        name="admin/login.html",
        context={
            "request": request,
            "title": "Вход",
            "next": _safe_next_url(next),
            "error": "",
        },
    )


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    password: str = Form(...),
    next: str = Form("/admin"),
):
    """Создает долгоживущую сессию администратора."""
    safe_next = _safe_next_url(next)
    if not _password_matches(password):
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            status_code=status.HTTP_401_UNAUTHORIZED,
            context={
                "request": request,
                "title": "Вход",
                "next": safe_next,
                "error": "Неверный пароль",
            },
        )

    response = RedirectResponse(
        url=safe_next,
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.set_cookie(
        SESSION_COOKIE,
        _create_session_token(),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=_is_https_request(request),
        samesite="lax",
    )
    return response


@app.get("/logout")
async def logout(request: Request):
    """Удаляет cookie-сессию администратора."""
    response = RedirectResponse(
        url="/login",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.delete_cookie(
        SESSION_COOKIE,
        secure=_is_https_request(request),
        samesite="lax",
    )
    return response


@app.get("/stats")
async def get_stats(session: Session = Depends(get_session)) -> dict[str, int | float]:
    """Возвращает базовую статистику пользователей."""
    _try_sync_subscriptions(session)
    total_users = session.query(func.count(User.user_id)).scalar() or 0
    subscribed_users = (
        session.query(func.count(User.user_id))
        .filter(User.is_subscribed.is_(True))
        .scalar()
        or 0
    )
    active_since = datetime.now(timezone.utc) - timedelta(hours=24)
    active_24h = (
        session.query(func.count(User.user_id))
        .filter(User.last_activity >= active_since)
        .scalar()
        or 0
    )
    subscribed_percent = (
        round((subscribed_users / total_users) * 100, 2)
        if total_users
        else 0.0
    )

    return {
        "total_users": total_users,
        "subscribed_users": subscribed_users,
        "subscribed_percent": subscribed_percent,
        "active_24h": active_24h,
    }


@app.post("/stats/sync")
async def sync_stats(session: Session = Depends(get_session)) -> dict[str, int]:
    """Принудительно синхронизирует подписчиков канала с PostgreSQL."""
    report = sync_subscriptions(session)
    return {
        "known_before": report.known_before,
        "real_members": report.real_members,
        "updated_rows": report.updated_rows,
        "inserted_rows": report.inserted_rows,
        "known_after": report.known_after,
    }


def _dashboard_context(request: Request, session: Session) -> dict:
    """Собирает данные главной страницы админ-панели."""
    sync_report = _try_sync_subscriptions(session)
    total_users = session.query(func.count(User.user_id)).scalar() or 0
    subscribed_users = (
        session.query(func.count(User.user_id))
        .filter(User.is_subscribed.is_(True))
        .scalar()
        or 0
    )
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    api_errors_24h = (
        session.query(func.count(EventLog.id))
        .filter(EventLog.timestamp >= since_24h)
        .filter(
            EventLog.event_type.in_(
                [
                    "api_error",
                    "max_api_error",
                    "broadcast_delivery_failed",
                ]
            )
        )
        .scalar()
        or 0
    )
    since_14d = datetime.now(timezone.utc) - timedelta(days=13)
    events = (
        session.query(EventLog.timestamp)
        .filter(EventLog.timestamp >= since_14d)
        .order_by(EventLog.timestamp)
        .all()
    )
    activity = {}
    for index in range(14):
        day = (since_14d + timedelta(days=index)).date()
        activity[day.isoformat()] = 0
    for row in events:
        if row[0]:
            activity[row[0].date().isoformat()] = (
                activity.get(row[0].date().isoformat(), 0) + 1
            )
    max_activity = max(activity.values()) if activity else 0
    growth_chart = _build_growth_chart(session, since_14d)
    feature_chart = _build_feature_chart(session)

    return {
        "request": request,
        "title": "Панель управления",
        "total_users": total_users,
        "subscribed_users": subscribed_users,
        "api_errors_24h": api_errors_24h,
        "sync_report": sync_report,
        "conversion_chart": {
            "labels": ["Зашли в бот", "Подписались"],
            "values": [total_users, subscribed_users],
        },
        "growth_chart": growth_chart,
        "feature_chart": feature_chart,
        "activity": [
            {
                "date": day,
                "count": count,
                "height": 8 + int((count / max_activity) * 92)
                if max_activity
                else 8,
            }
            for day, count in activity.items()
        ],
    }


def _try_sync_subscriptions(session: Session):
    """Пытается актуализировать подписчиков без падения UI при ошибке API."""
    try:
        return ensure_recent_subscription_sync(session)
    except Exception as error:
        session.add(
            EventLog(
                event_type="subscription_sync_failed",
                details=f"{type(error).__name__}: {error}",
            )
        )
        session.commit()
        return None


def _build_growth_chart(session: Session, since_14d: datetime) -> dict:
    """Готовит данные роста базы за 14 дней."""
    labels = []
    daily_values = []
    for index in range(14):
        day = (since_14d + timedelta(days=index)).date()
        next_day = day + timedelta(days=1)
        count = (
            session.query(func.count(User.user_id))
            .filter(User.created_at >= datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc))
            .filter(User.created_at < datetime.combine(next_day, datetime.min.time(), tzinfo=timezone.utc))
            .scalar()
            or 0
        )
        labels.append(day.strftime("%d.%m"))
        daily_values.append(count)
    return {"labels": labels, "values": daily_values}


def _build_feature_chart(session: Session) -> dict:
    """Считает популярность функций по events_log."""
    rows = (
        session.query(EventLog.event_type, func.count(EventLog.id))
        .group_by(EventLog.event_type)
        .order_by(func.count(EventLog.id).desc())
        .limit(6)
        .all()
    )
    labels = [row[0] for row in rows] or ["Нет данных"]
    values = [row[1] for row in rows] or [0]
    return {"labels": labels, "values": values}


@app.get("/", response_class=HTMLResponse)
async def dashboard_root(
    request: Request,
    session: Session = Depends(get_session),
):
    """Показывает главную страницу панели."""
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context=_dashboard_context(request, session),
    )


@app.get("/admin", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: Session = Depends(get_session),
):
    """Показывает главную страницу панели."""
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context=_dashboard_context(request, session),
    )


@app.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    q: str | None = None,
    session: Session = Depends(get_session),
):
    """Показывает страницу управления пользователями."""
    users = _find_users(session=session, q=q)
    return templates.TemplateResponse(
        request=request,
        name="admin/users.html",
        context={
            "request": request,
            "title": "Пользователи",
            "users": users,
            "q": q or "",
        },
    )


@app.get("/users/table", response_class=HTMLResponse)
async def users_table(
    request: Request,
    q: str | None = None,
    session: Session = Depends(get_session),
):
    """Возвращает HTMX-фрагмент таблицы пользователей."""
    users = _find_users(session=session, q=q)
    return templates.TemplateResponse(
        request=request,
        name="admin/partials/users_table.html",
        context={"request": request, "users": users, "q": q or ""},
    )


def _find_users(session: Session, q: str | None) -> list[User]:
    """Ищет пользователей по user_id."""
    query = session.query(User).order_by(User.created_at.desc())
    if q:
        try:
            query = query.filter(User.user_id == int(q))
        except ValueError:
            return []
    return query.limit(200).all()


@app.get("/api/discovered-entities")
async def discovered_entities_api(
    entity_type: str | None = None,
    session: Session = Depends(get_session),
) -> list[dict[str, int | str]]:
    """Возвращает найденные ID с необязательным фильтром по типу."""
    entities = _find_discovered_entities(session=session, entity_type=entity_type)
    return [_serialize_discovered_entity(entity) for entity in entities]


@app.get("/discovered-entities", response_class=HTMLResponse)
async def discovered_entities_page(
    request: Request,
    entity_type: str | None = None,
    session: Session = Depends(get_session),
):
    """Показывает страницу найденных объектов ID-Harvester."""
    entities = _find_discovered_entities(
        session=session,
        entity_type=entity_type,
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/discovered_entities.html",
        context={
            "request": request,
            "title": "Найденные объекты",
            "entities": entities,
            "entity_type": entity_type or "",
        },
    )


@app.get("/discovered-entities/table", response_class=HTMLResponse)
async def discovered_entities_table(
    request: Request,
    entity_type: str | None = None,
    session: Session = Depends(get_session),
):
    """Возвращает HTMX-фрагмент таблицы найденных объектов."""
    entities = _find_discovered_entities(
        session=session,
        entity_type=entity_type,
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/partials/discovered_entities_table.html",
        context={
            "request": request,
            "entities": entities,
            "entity_type": entity_type or "",
        },
    )


def _find_discovered_entities(
    *,
    session: Session,
    entity_type: str | None,
) -> list[DiscoveredEntity]:
    """Возвращает найденные объекты с фильтром по типу."""
    query = session.query(DiscoveredEntity).order_by(
        DiscoveredEntity.timestamp.desc()
    )
    if entity_type:
        normalized_type = entity_type.strip().lower()
        if normalized_type not in {"user", "chat", "bot"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Некорректный тип объекта",
            )
        query = query.filter(DiscoveredEntity.entity_type == normalized_type)
    return query.limit(500).all()


def _serialize_discovered_entity(
    entity: DiscoveredEntity,
) -> dict[str, int | str]:
    """Готовит найденный объект для JSON API."""
    return {
        "id": entity.id,
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type,
        "discovered_by_user_id": entity.discovered_by_user_id,
        "timestamp": entity.timestamp.isoformat() if entity.timestamp else "",
    }


@app.post("/users/{user_id}/toggle-ban", response_class=HTMLResponse)
async def toggle_user_ban(
    user_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Переключает ban/unban и возвращает обновленную таблицу."""
    user = session.get(User, user_id)
    if user:
        user.is_banned = not user.is_banned
        session.commit()
    return await users_table(request=request, session=session)


@app.post("/users/{user_id}/reset-subscription", response_class=HTMLResponse)
async def reset_user_subscription(
    user_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Сбрасывает статус подписки пользователя."""
    user = session.get(User, user_id)
    if user:
        user.is_subscribed = False
        session.commit()
    return await users_table(request=request, session=session)


@app.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(request: Request):
    """Показывает панель запуска рассылок."""
    return templates.TemplateResponse(
        request=request,
        name="admin/broadcast.html",
        context={
            "request": request,
            "title": "Рассылки",
        },
    )


def _broadcast_error_response(
    request: Request,
    message: str,
    status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE,
) -> HTMLResponse | JSONResponse:
    """Возвращает ошибку запуска рассылки в формате текущего запроса."""
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="admin/partials/broadcast_error.html",
            status_code=status_code,
            context={
                "request": request,
                "error_message": message,
            },
        )
    return JSONResponse(status_code=status_code, content={"detail": message})


def _mark_broadcast_failed(
    session: Session,
    broadcast_id: int | None,
    error: Exception,
) -> None:
    """Фиксирует сбой запуска рассылки без падения UI."""
    try:
        if broadcast_id is not None:
            broadcast = session.get(Broadcast, broadcast_id)
            if broadcast is not None:
                broadcast.status = "failed"

        session.add(
            EventLog(
                event_type="broadcast_enqueue_failed",
                details=f"{type(error).__name__}: {error}"[:2000],
            )
        )
        session.commit()
    except Exception:
        session.rollback()


@app.post("/broadcast/send", response_model=None)
async def send_broadcast(
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, int | str] | HTMLResponse:
    """Создает рассылку и ставит доставку в Celery-очередь."""
    broadcast_id = None
    try:
        if request.headers.get("content-type", "").startswith(
            "application/json"
        ):
            body = await request.json()
            payload = BroadcastSendRequest(**body)
        else:
            form = await request.form()
            media_type = str(form.get("media_type") or "").strip() or None
            media_file_id = str(form.get("media_file_id") or "").strip() or None
            media_upload = form.get("media_upload")
            if hasattr(media_upload, "filename") and media_upload.filename:
                content = await media_upload.read()
                media_file_id = upload_media_to_max(
                    filename=media_upload.filename,
                    content=content,
                    content_type=media_upload.content_type,
                )
                if (
                    media_upload.content_type
                    and media_upload.content_type.startswith("video/")
                ):
                    media_type = "video"
                else:
                    media_type = "image"
            payload = BroadcastSendRequest(
                text=str(form.get("text", "")),
                media_type=media_type,
                media_file_id=media_file_id,
            )

        user_ids = [
            row[0]
            for row in (
                session.query(User.user_id)
                .filter(User.is_banned.is_(False))
                .order_by(User.user_id)
                .all()
            )
        ]
        broadcast = Broadcast(
            text=payload.text,
            media_type=payload.media_type,
            media_file_id=payload.media_file_id,
            status="running" if user_ids else "completed",
            total_count=len(user_ids),
            sent_count=0,
        )
        session.add(broadcast)
        session.commit()
        session.refresh(broadcast)
        broadcast_id = broadcast.id

        if user_ids:
            enqueue_broadcast(
                broadcast_id=broadcast.id,
                user_ids=user_ids,
                text=payload.text,
                media_type=payload.media_type,
                media_file_id=payload.media_file_id,
            )
    except Exception as error:
        session.rollback()
        _mark_broadcast_failed(session, broadcast_id, error)
        return _broadcast_error_response(
            request=request,
            message=f"Не удалось запустить рассылку: {type(error).__name__}: {error}",
        )

    response_payload = {
        "broadcast_id": broadcast.id,
        "status": broadcast.status,
        "total_count": broadcast.total_count,
        "sent_count": broadcast.sent_count,
        "media_type": broadcast.media_type or "",
        "media_file_id": broadcast.media_file_id or "",
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="admin/partials/broadcast_progress.html",
            context={
                "request": request,
                "broadcast": broadcast,
                "progress_percent": 0.0 if user_ids else 100.0,
            },
        )
    return response_payload


@app.get("/broadcast/{broadcast_id}/status", response_model=None)
async def get_broadcast_status(
    broadcast_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, int | str | float] | HTMLResponse:
    """Возвращает прогресс доставки рассылки."""
    broadcast = session.get(Broadcast, broadcast_id)
    if broadcast is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Рассылка не найдена"},
        )

    progress_percent = (
        round((broadcast.sent_count / broadcast.total_count) * 100, 2)
        if broadcast.total_count
        else 100.0
    )
    response_payload = {
        "broadcast_id": broadcast.id,
        "status": broadcast.status,
        "sent_count": broadcast.sent_count,
        "total_count": broadcast.total_count,
        "progress_percent": progress_percent,
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request=request,
            name="admin/partials/broadcast_progress.html",
            context={
                "request": request,
                "broadcast": broadcast,
                "progress_percent": progress_percent,
            },
        )
    return response_payload


@app.get("/broadcast/{broadcast_id}/progress", response_class=HTMLResponse)
async def get_broadcast_progress(
    broadcast_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Возвращает HTMX-фрагмент прогресса рассылки."""
    broadcast = session.get(Broadcast, broadcast_id)
    if broadcast is None:
        return HTMLResponse("Рассылка не найдена", status_code=404)

    progress_percent = (
        round((broadcast.sent_count / broadcast.total_count) * 100, 2)
        if broadcast.total_count
        else 100.0
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/partials/broadcast_progress.html",
        context={
            "request": request,
            "broadcast": broadcast,
            "progress_percent": progress_percent,
        },
    )


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """Показывает последние строки journalctl сервиса max-id-bot."""
    return templates.TemplateResponse(
        request=request,
        name="admin/logs.html",
        context={
            "request": request,
            "title": "Логи",
            "logs": _read_service_logs(),
        },
    )


@app.get("/logs/fragment", response_class=HTMLResponse)
async def logs_fragment(request: Request):
    """Возвращает HTMX-фрагмент логов."""
    return templates.TemplateResponse(
        request=request,
        name="admin/partials/logs_output.html",
        context={
            "request": request,
            "logs": _read_service_logs(),
        },
    )


def _read_service_logs() -> str:
    """Читает последние 100 строк journalctl для сервиса max-id-bot."""
    try:
        result = subprocess.run(
            [
                "journalctl",
                "-u",
                "max-id-bot",
                "-n",
                "100",
                "--no-pager",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as error:
        return f"journalctl недоступен: {error}"

    return result.stdout or result.stderr or "Логи пусты."
