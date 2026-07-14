"""
Клавиатура для перехода на обязательный канал.
"""
import logging

from config import CHANNEL_LINK

logger = logging.getLogger(__name__)


def subscription_keyboard():
    """Возвращает inline-клавиатуру с кнопкой подписки."""
    try:
        from maxapi.types import CallbackButton, LinkButton
        from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
    except Exception as import_err:
        logger.warning(
            f"Не удалось импортировать link-кнопку подписки: {import_err}"
        )
        return None

    builder = InlineKeyboardBuilder()
    builder.row(
        LinkButton(text="Подписаться на канал", url=CHANNEL_LINK)
    )
    builder.row(
        CallbackButton(
            text="Проверить подписку",
            payload="subscription_retry"
        )
    )
    return builder.as_markup()


def subscription_retry_keyboard():
    """Возвращает inline-клавиатуру для повторной проверки подписки."""
    try:
        from maxapi.types import CallbackButton, LinkButton
        from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
    except Exception as import_err:
        logger.warning(
            f"Не удалось импортировать клавиатуру проверки подписки: {import_err}"
        )
        return None

    builder = InlineKeyboardBuilder()
    builder.row(
        LinkButton(text="Подписаться на канал", url=CHANNEL_LINK)
    )
    builder.row(
        CallbackButton(
            text="Проверить подписку",
            payload="subscription_retry"
        )
    )
    return builder.as_markup()
