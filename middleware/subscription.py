"""
Декоратор проверки подписки на канал.
"""
import logging
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Awaitable

import httpx
from maxapi.enums.parse_mode import ParseMode

from config import (
    API_BASE,
    BOT_TOKEN,
    CHANNEL_CHAT_ID,
    CHANNEL_ID,
    SUBSCRIPTION_TEXT,
)
from database.storage import get_user, update_user
from keyboards.subscription import subscription_keyboard


logger = logging.getLogger(__name__)

CACHE_TTL_SUBSCRIBED = 300
CACHE_TTL_NOT_SUBSCRIBED = 60
PROTECTED_CALLBACK_PAYLOADS = {
    "get_user_id",
    "get_bot_id",
    "get_chat_id",
    "get_channel_id",
    "get_sticker_info",
}


def require_subscription(handler_func: Callable[..., Awaitable[Any]]):
    """
    Пропускает первый запрос пользователя и дальше проверяет подписку.

    Args:
        handler_func: Исходный async-обработчик.
    """
    @wraps(handler_func)
    async def wrapper(event: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_protected_event(event):
            return await handler_func(event, *args, **kwargs)

        user_id = _extract_user_id(event)
        if user_id is None:
            logger.warning("Не удалось определить пользователя для проверки подписки")
            return await handler_func(event, *args, **kwargs)

        user = await get_user(user_id)
        usage_count = int(user.get("usage_count") or 0)
        logger.info(
            "Middleware entered: user_id=%s usage_count=%s",
            user_id,
            usage_count
        )

        if usage_count < 1:
            await update_user(user_id, usage_count=usage_count + 1)
            return await handler_func(event, *args, **kwargs)

        event_decision = _get_event_subscription_decision(user)
        if event_decision is not None:
            logger.info(
                "Subscription decision: %s (source=%s)",
                event_decision,
                "event"
            )
            if event_decision:
                return await handler_func(event, *args, **kwargs)

            await _send_subscription_message(event)
            await _answer_callback_if_needed(event)
            return None

        cached_decision = _get_cached_subscription_decision(user)
        if cached_decision is not None:
            logger.info(
                "Subscription decision: %s (cached=%s)",
                cached_decision,
                True
            )
            if cached_decision:
                return await handler_func(event, *args, **kwargs)

            await _send_subscription_message(event)
            await _answer_callback_if_needed(event)
            return None

        is_subscribed = await _check_subscription(user_id)
        await update_user(
            user_id,
            is_subscribed=1 if is_subscribed else 0,
            last_check=datetime.utcnow().isoformat(),
            subscription_source="api"
        )

        if is_subscribed:
            return await handler_func(event, *args, **kwargs)

        await _send_subscription_message(event)
        await _answer_callback_if_needed(event)
        return None

    return wrapper


def _extract_user_id(event: Any) -> int | None:
    """Достает user_id из разных типов событий maxapi."""
    candidates = [
        getattr(event, "user_id", None),
        getattr(getattr(event, "from_user", None), "user_id", None),
        getattr(getattr(event, "from_user", None), "id", None),
        getattr(getattr(getattr(event, "callback", None), "user", None), "user_id", None),
        getattr(getattr(getattr(event, "callback", None), "user", None), "id", None),
    ]

    for candidate in candidates:
        if candidate is not None:
            try:
                return int(candidate)
            except (TypeError, ValueError):
                logger.warning(f"Некорректный user_id: {candidate}")
                return None

    return None


def _is_protected_event(event: Any) -> bool:
    """Определяет, нужно ли применять подписку к событию."""
    callback = getattr(event, "callback", None)
    if callback is not None:
        payload = getattr(callback, "payload", None)
        return payload in PROTECTED_CALLBACK_PAYLOADS

    message = getattr(event, "message", None)
    body = getattr(message, "body", None)
    if message is None or body is None:
        return False

    text = (getattr(body, "text", None) or "").strip()
    if text.startswith("/start") or text.startswith("/help"):
        return False

    attachments = getattr(body, "attachments", None) or []
    if any(_is_sticker_attachment(attachment) for attachment in attachments):
        return True

    link = getattr(message, "link", None)
    if link is not None:
        link_type = getattr(link, "type", None)
        if str(link_type).lower().endswith("forward") or link_type == "forward":
            return True

    if text:
        if "max.ru/" in text or text.startswith("@"):
            return True
        try:
            int(text)
            return True
        except ValueError:
            return False

    return False


def _is_sticker_attachment(attachment: Any) -> bool:
    """Проверяет, является ли вложение стикером."""
    return (
        attachment.__class__.__name__ == "Sticker"
        or getattr(attachment, "type", None) == "sticker"
    )


def _get_cached_subscription_decision(user: dict[str, Any]) -> bool | None:
    """Возвращает кэшированное решение или None, если кэш устарел."""
    if user.get("subscription_source") == "event":
        return None

    last_check = user.get("last_check")
    if not last_check:
        return None

    try:
        checked_at = datetime.fromisoformat(last_check)
    except ValueError:
        return None

    is_subscribed = int(user.get("is_subscribed") or 0) == 1
    ttl_seconds = (
        CACHE_TTL_SUBSCRIBED
        if is_subscribed
        else CACHE_TTL_NOT_SUBSCRIBED
    )
    age_seconds = (datetime.utcnow() - checked_at).total_seconds()
    if age_seconds < ttl_seconds:
        return is_subscribed

    return None


def _get_event_subscription_decision(user: dict[str, Any]) -> bool | None:
    """Возвращает состояние подписки, полученное из событий канала."""
    if user.get("subscription_source") != "event":
        return None

    return int(user.get("is_subscribed") or 0) == 1


async def _check_subscription(user_id: int) -> bool:
    """
    Проверяет подписку через MAX API.

    Ошибки прав доступа и неверного канала блокируют пользователя.
    Временные сетевые проблемы пропускают запрос.
    """
    chat_id = CHANNEL_CHAT_ID if CHANNEL_CHAT_ID is not None else CHANNEL_ID
    url = f"{API_BASE}/chats/{chat_id}/members"
    headers = {"Authorization": BOT_TOKEN}
    logger.info("Checking subscription: user_id=%s, url=%s", user_id, url)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                url,
                headers=headers,
                params={"user_ids": user_id}
            )

        logger.info("Members API status: %s", resp.status_code)
        logger.info("Members API body preview: %s", str(resp.text)[:500])

        if resp.status_code == 200:
            data = resp.json()
            decision = _members_include_user(data, user_id)
            logger.info(
                "Subscription decision: %s (cached=%s)",
                decision,
                False
            )
            return decision

        if resp.status_code in (403, 404):
            logger.error(
                "Subscription API error: %s. Bot may not be admin in channel "
                "or channel ID is wrong.",
                resp.status_code
            )
            logger.info(
                "Subscription decision: %s (cached=%s)",
                False,
                False
            )
            return False

        if resp.status_code == 429:
            logger.warning("Rate limit")
            logger.info(
                "Subscription decision: %s (cached=%s)",
                True,
                False
            )
            return True

        if 500 <= resp.status_code <= 599:
            logger.warning("API unreachable")
            logger.info(
                "Subscription decision: %s (cached=%s)",
                True,
                False
            )
            return True

        logger.error("Subscription API unexpected status: %s", resp.status_code)
        logger.info(
            "Subscription decision: %s (cached=%s)",
            False,
            False
        )
        return False
    except httpx.TimeoutException:
        logger.warning("API unreachable")
        logger.info(
            "Subscription decision: %s (cached=%s)",
            True,
            False
        )
        return True
    except Exception:
        logger.exception("Subscription check failed")
        logger.warning(
            "API unreachable"
        )
        logger.info(
            "Subscription decision: %s (cached=%s)",
            True,
            False
        )
        return True


def _members_include_user(data: Any, user_id: int) -> bool:
    """Ищет пользователя в разных возможных формах ответа API."""
    members = data
    if isinstance(data, dict):
        members = (
            data.get("members")
            or data.get("users")
            or data.get("items")
            or data.get("data")
            or []
        )

    if not isinstance(members, list):
        logger.warning("Неожиданный формат списка участников канала")
        return False

    for member in members:
        if _member_user_id(member) == user_id:
            return True

    return False


def _member_user_id(member: Any) -> int | None:
    """Достает user_id из элемента списка участников."""
    if isinstance(member, int):
        return member

    if isinstance(member, str):
        try:
            return int(member)
        except ValueError:
            return None

    if isinstance(member, dict):
        user = member.get("user")
        value = (
            member.get("user_id")
            or member.get("id")
            or (user.get("user_id") if isinstance(user, dict) else None)
            or (user.get("id") if isinstance(user, dict) else None)
            or getattr(user, "user_id", None)
            or getattr(user, "id", None)
        )
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    value = (
        getattr(member, "user_id", None)
        or getattr(member, "id", None)
        or getattr(getattr(member, "user", None), "user_id", None)
        or getattr(getattr(member, "user", None), "id", None)
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _send_subscription_message(event: Any) -> None:
    """Отправляет пользователю сообщение с кнопкой подписки."""
    keyboard = subscription_keyboard()
    attachments = [keyboard] if keyboard is not None else None
    message = getattr(event, "message", None)

    if message is not None and hasattr(message, "answer"):
        await message.answer(
            text=SUBSCRIPTION_TEXT,
            parse_mode=ParseMode.HTML,
            attachments=attachments
        )
        return

    chat_id = _extract_chat_id(event)
    bot = getattr(event, "bot", None)
    if chat_id is None or bot is None:
        logger.warning("Не удалось отправить сообщение о подписке")
        return

    await bot.send_message(
        chat_id=chat_id,
        text=SUBSCRIPTION_TEXT,
        parse_mode=ParseMode.HTML,
        attachments=attachments
    )


async def _answer_callback_if_needed(event: Any) -> None:
    """Отвечает на callback, чтобы кнопка не оставалась в ожидании."""
    callback = getattr(event, "callback", None)
    callback_id = getattr(callback, "callback_id", None)
    bot = getattr(event, "bot", None)
    if callback_id is None or bot is None:
        return

    try:
        await bot.send_callback(
            callback_id=callback_id,
            notification="Подпишитесь на канал"
        )
    except Exception as callback_err:
        logger.warning(f"Не удалось ответить на callback: {callback_err}")


def _extract_chat_id(event: Any) -> int | str | None:
    """Достает chat_id для отправки сообщения."""
    candidates = [
        getattr(event, "chat_id", None),
        getattr(getattr(getattr(event, "message", None), "recipient", None), "chat_id", None),
    ]

    for candidate in candidates:
        if candidate is not None:
            return candidate

    return None
