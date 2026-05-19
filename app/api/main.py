"""FastAPI backend первой фазы админ-панели."""
import os
import subprocess
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.models.database import get_session, init_models
from app.models.tables import Broadcast, EventLog, User
from app.tasks.broadcast import enqueue_broadcast


OWNER_HEADER = "X-Owner-Id"
OWNER_COOKIE = "owner_id"
templates = Jinja2Templates(directory="app/templates")


class BroadcastSendRequest(BaseModel):
    """Запрос на запуск массовой рассылки."""

    text: str = Field(min_length=1, max_length=4000)


class OwnerOnlyMiddleware(BaseHTTPMiddleware):
    """Ограничивает доступ к панели владельцем из OWNER_ID."""

    async def dispatch(self, request: Request, call_next):
        owner_id = os.getenv("OWNER_ID")
        request_owner_id = (
            request.headers.get(OWNER_HEADER)
            or request.query_params.get("owner_id")
            or request.cookies.get(OWNER_COOKIE)
        )

        if not owner_id:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "OWNER_ID не настроен"},
            )

        if request_owner_id != owner_id:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Доступ разрешен только владельцу"},
            )

        response = await call_next(request)
        if request.query_params.get("owner_id") == owner_id:
            response.set_cookie(
                OWNER_COOKIE,
                owner_id,
                httponly=True,
                samesite="lax",
            )
        return response


app = FastAPI(title="MaxIDBot Admin API")
app.add_middleware(OwnerOnlyMiddleware)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
def on_startup() -> None:
    """Создает таблицы первой фазы, если они еще не существуют."""
    init_models()


@app.get("/stats")
async def get_stats(session: Session = Depends(get_session)) -> dict[str, int | float]:
    """Возвращает базовую статистику пользователей."""
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
        "subscribed_percent": subscribed_percent,
        "active_24h": active_24h,
    }


def _dashboard_context(request: Request, session: Session) -> dict:
    """Собирает данные главной страницы админ-панели."""
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

    return {
        "request": request,
        "title": "Dashboard",
        "total_users": total_users,
        "subscribed_users": subscribed_users,
        "api_errors_24h": api_errors_24h,
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
            "title": "Users",
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
            "title": "Broadcast",
        },
    )


@app.post("/broadcast/send", response_model=None)
async def send_broadcast(
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, int | str] | HTMLResponse:
    """Создает рассылку и ставит доставку в Celery-очередь."""
    if request.headers.get("content-type", "").startswith(
        "application/json"
    ):
        body = await request.json()
        payload = BroadcastSendRequest(**body)
    else:
        form = await request.form()
        payload = BroadcastSendRequest(text=str(form.get("text", "")))

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
        status="running" if user_ids else "completed",
        total_count=len(user_ids),
        sent_count=0,
    )
    session.add(broadcast)
    session.commit()
    session.refresh(broadcast)

    if user_ids:
        enqueue_broadcast(
            broadcast_id=broadcast.id,
            user_ids=user_ids,
            text=payload.text,
        )

    response_payload = {
        "broadcast_id": broadcast.id,
        "status": broadcast.status,
        "total_count": broadcast.total_count,
        "sent_count": broadcast.sent_count,
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
            "title": "Logs",
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
