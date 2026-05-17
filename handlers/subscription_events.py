"""
Обработчики событий подписки и отписки от канала.
"""
import logging
from datetime import datetime
from typing import Any

from maxapi.types import UserAdded, UserRemoved

from config import CHANNEL_CHAT_ID
from database.storage import update_user

logger = logging.getLogger(__name__)


def register_subscription_event_handlers(dp):
    """
    Регистрирует обработчики входа и выхода пользователя из канала.

    Args:
        dp: Dispatcher экземпляр для регистрации обработчиков.
    """

    @dp.user_added()
    async def on_user_added(event: UserAdded):
        """Фиксирует активную подписку пользователя на канал."""
        if not _is_target_channel_event(event):
            return

        user_id = _extract_event_user_id(event)
        if user_id is None:
            logger.warning("Не удалось определить user_id в user_added")
            return

        await update_user(
            user_id,
            is_subscribed=1,
            last_check=datetime.utcnow().isoformat(),
            subscription_source="event"
        )
        logger.info(
            "Subscription event: user_added user_id=%s chat_id=%s",
            user_id,
            getattr(event, "chat_id", None)
        )

    @dp.user_removed()
    async def on_user_removed(event: UserRemoved):
        """Фиксирует отписку пользователя от канала."""
        if not _is_target_channel_event(event):
            return

        user_id = _extract_event_user_id(event)
        if user_id is None:
            logger.warning("Не удалось определить user_id в user_removed")
            return

        await update_user(
            user_id,
            is_subscribed=0,
            last_check=datetime.utcnow().isoformat(),
            subscription_source="event"
        )
        logger.info(
            "Subscription event: user_removed user_id=%s chat_id=%s",
            user_id,
            getattr(event, "chat_id", None)
        )

    logger.info("Subscription event handlers registered")


def _is_target_channel_event(event: Any) -> bool:
    """Проверяет, что событие пришло из нужного канала."""
    if not getattr(event, "is_channel", False):
        return False

    event_chat_id = getattr(event, "chat_id", None)
    if CHANNEL_CHAT_ID is None:
        logger.warning(
            "CHANNEL_CHAT_ID не задан, принимаем событие канала chat_id=%s",
            event_chat_id
        )
        return True

    return event_chat_id == CHANNEL_CHAT_ID


def _extract_event_user_id(event: Any) -> int | None:
    """Достает ID пользователя из события канала."""
    user = getattr(event, "user", None)
    value = (
        getattr(user, "user_id", None)
        or getattr(user, "id", None)
        or getattr(event, "user_id", None)
    )

    try:
        return int(value)
    except (TypeError, ValueError):
        return None
