"""
Клавиатура для перехода на обязательный канал.
"""
import logging

from config import CHANNEL_LINK

logger = logging.getLogger(__name__)


def subscription_keyboard():
    """Возвращает inline-клавиатуру с кнопкой подписки."""
    try:
        from maxapi.types import LinkButton
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
    return builder.as_markup()
