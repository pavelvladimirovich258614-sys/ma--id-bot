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
    ADMIN_USER_IDS,
    SUBSCRIPTION_TEXT,
)
from database.postgres_storage import get_admin_user_state, upsert_admin_user
from database.storage import get_user, update_user
from keyboards.subscription import subscription_keyboard, subscription_retry_keyboard


logger = logging.getLogger(__name__)

PROTECTED_CALLBACK_PAYLOADS = {
    "get_user_id",
    "get_bot_id",
    "get_chat_id",
    "get_channel_id",
    "get_sticker_info",
    "subscription_retry",
    "harvest_menu",
    "harvest_bot_id",
    "harvest_by_link",
    "harvest_by_message",
    "harvest_back",
}


class SubscriptionCheckError(Exception):
    """Временная ошибка проверки подписки через MAX API."""
    pass


class SubscriptionAccess:
    ADMIN = "admin"
    SUBSCRIBED = "subscribed"
    NOT_SUBSCRIBED = "not_subscribed"
    UNAVAILABLE = "unavailable"


async def check_subscription_access(user_id: int) -> str:
    """
    Единый helper проверки доступа по подписке.
    """
    if user_id in ADMIN_USER_IDS:
        return SubscriptionAccess.ADMIN

    chat_id = CHANNEL_CHAT_ID if CHANNEL_CHAT_ID is not None else CHANNEL_ID
    url = f"{API_BASE}/chats/{chat_id}/members"
    headers = {"Authorization": BOT_TOKEN}
    logger.info(f"Checking subscription: user_id={user_id}")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                url,
                headers=headers,
                params={"user_ids": user_id}
            )

        logger.info(f"Members API status: {resp.status_code}")

        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                logger.warning("Members API invalid JSON")
                return SubscriptionAccess.UNAVAILABLE

            decision = _members_include_user(data, user_id)
            logger.info(
                f"Subscription decision: {decision} (source=api)"
            )
            return SubscriptionAccess.SUBSCRIBED if decision else SubscriptionAccess.NOT_SUBSCRIBED

        logger.warning(f"Members API error: {resp.status_code}")
        return SubscriptionAccess.UNAVAILABLE
    except httpx.TimeoutException:
        logger.warning("Members API timeout")
        return SubscriptionAccess.UNAVAILABLE
    except Exception:
        logger.warning("Members API unavailable")
        return SubscriptionAccess.UNAVAILABLE


def require_subscription(handler_func: Callable[..., Awaitable[Any]]):
    """
    Проверяет подписку перед вызовом обработчика.

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

        admin_user = await get_admin_user_state(user_id)
        if admin_user and bool(admin_user.get("is_banned")):
            logger.warning(f"Пользователь заблокирован в админ-панели: {user_id}")
            await _send_banned_message(event)
            await _answer_callback_if_needed(
                event,
                notification="Доступ заблокирован"
            )
            return None

        access = await check_subscription_access(user_id)

        if access == SubscriptionAccess.ADMIN:
            return await handler_func(event, *args, **kwargs)

        if access == SubscriptionAccess.SUBSCRIBED:
            await update_user(
                user_id,
                is_subscribed=1,
                last_check=datetime.utcnow().isoformat(),
                subscription_source="api"
            )
            await upsert_admin_user(user_id, is_subscribed=True)
            return await handler_func(event, *args, **kwargs)

        if access == SubscriptionAccess.NOT_SUBSCRIBED:
            await update_user(
                user_id,
                is_subscribed=0,
                last_check=datetime.utcnow().isoformat(),
                subscription_source="api"
            )
            await upsert_admin_user(user_id, is_subscribed=False)
            await _send_subscription_message(event, retry=False)
            await _answer_callback_if_needed(event)
            return None

        await _send_unavailable_message(event)
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
    if message is not None and body is not None:
        text = (getattr(body, "text", None) or "").strip()
        if text.startswith("/start") or text.startswith("/help"):
            return True

    if getattr(event, "from_user", None) is not None and getattr(event, "bot", None) is not None:
        if getattr(event, "message", None) is None:
            return True

    if message is None or body is None:
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


async def _send_subscription_message(event: Any, retry: bool = False) -> None:
    """Отправляет пользователю сообщение с кнопкой подписки."""
    keyboard = subscription_retry_keyboard() if retry else subscription_keyboard()
    attachments = [keyboard] if keyboard is not None else None
    message = getattr(event, "message", None)

    if message is not None and callable(getattr(message, "answer", None)):
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


async def _send_unavailable_message(event: Any) -> None:
    """Сообщает, что проверка подписки временно недоступна."""
    keyboard = subscription_retry_keyboard()
    attachments = [keyboard] if keyboard is not None else None
    text = (
        "❌ Извините, сейчас не удалось проверить подписку. "
        "Попробуйте ещё раз через несколько секунд."
    )
    message = getattr(event, "message", None)

    if message is not None and callable(getattr(message, "answer", None)):
        await message.answer(
            text=text,
            parse_mode=ParseMode.HTML,
            attachments=attachments
        )
        return

    chat_id = _extract_chat_id(event)
    bot = getattr(event, "bot", None)
    if chat_id is None or bot is None:
        logger.warning("Не удалось отправить сообщение о недоступности проверки")
        return

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        attachments=attachments
    )


async def _send_banned_message(event: Any) -> None:
    """Сообщает пользователю, что доступ заблокирован владельцем."""
    text = "Доступ к боту заблокирован администратором."
    message = getattr(event, "message", None)

    if message is not None and hasattr(message, "answer"):
        await message.answer(text=text)
        return

    chat_id = _extract_chat_id(event)
    bot = getattr(event, "bot", None)
    if chat_id is None or bot is None:
        logger.warning("Не удалось отправить сообщение о блокировке")
        return

    await bot.send_message(chat_id=chat_id, text=text)


async def _answer_callback_if_needed(
    event: Any,
    notification: str = "Подпишитесь на канал",
) -> None:
    """Отвечает на callback, чтобы кнопка не оставалась в ожидании."""
    callback = getattr(event, "callback", None)
    callback_id = getattr(callback, "callback_id", None)
    bot = getattr(event, "bot", None)
    if callback_id is None or bot is None:
        return

    try:
        await bot.send_callback(
            callback_id=callback_id,
            notification=notification
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
