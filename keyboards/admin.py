"""
Клавиатуры админ-панели и конструктора рассылок.
"""
from maxapi.types import CallbackButton, LinkButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


def admin_panel_keyboard():
    """Возвращает клавиатуру главного экрана админ-панели."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="\U0001f4e3 Создать рассылку", payload="admin_broadcast_new"),
    )
    builder.row(
        CallbackButton(text="\U0001f4cb Последняя рассылка", payload="admin_broadcast_last"),
    )
    builder.row(
        CallbackButton(text="\u274c Закрыть", payload="admin_close"),
    )
    return builder.as_markup()


def admin_broadcast_image_keyboard():
    """Возвращает клавиатуру шага выбора изображения."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="\U0001f5bc \u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0435", payload="admin_broadcast_add_image"),
    )
    builder.row(
        CallbackButton(text="\u23f9 \u0411\u0435\u0437 \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u044f", payload="admin_broadcast_skip_image"),
    )
    builder.row(
        CallbackButton(text="\u274c \u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c", payload="admin_broadcast_cancel"),
    )
    return builder.as_markup()


def admin_broadcast_text_keyboard():
    """Возвращает клавиатуру шага ввода текста."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="\u274c \u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c", payload="admin_broadcast_cancel"),
    )
    return builder.as_markup()


def admin_broadcast_button_keyboard():
    """Возвращает клавиатуру шага выбора кнопки."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="\U0001f198 \u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u043a\u043d\u043e\u043f\u043a\u0443", payload="admin_broadcast_add_button"),
    )
    builder.row(
        CallbackButton(text="\u23f9 \u0411\u0435\u0437 \u043a\u043d\u043e\u043f\u043a\u0438", payload="admin_broadcast_skip_button"),
    )
    builder.row(
        CallbackButton(text="\u274c \u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c", payload="admin_broadcast_cancel"),
    )
    return builder.as_markup()


def admin_broadcast_preview_keyboard():
    """Возвращает клавиатуру предпросмотра."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="\u2705 \u0412\u0441\u0451 \u0432\u0435\u0440\u043d\u043e", payload="admin_broadcast_confirm"),
    )
    builder.row(
        CallbackButton(text="\u270f\ufe0f \u0418\u0437\u043c\u0435\u043d\u0438\u0442\u044c \u0442\u0435\u043a\u0441\u0442", payload="admin_broadcast_edit_text"),
    )
    builder.row(
        CallbackButton(text="\U0001f5bc \u0418\u0437\u043c\u0435\u043d\u0438\u0442\u044c \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0435", payload="admin_broadcast_edit_image"),
    )
    builder.row(
        CallbackButton(text="\U0001f198 \u0418\u0437\u043c\u0435\u043d\u0438\u0442\u044c \u043a\u043d\u043e\u043f\u043a\u0443", payload="admin_broadcast_edit_button"),
    )
    builder.row(
        CallbackButton(text="\u274c \u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c", payload="admin_broadcast_cancel"),
    )
    return builder.as_markup()


def admin_broadcast_launch_keyboard(total_recipients):
    """Возвращает клавиатуру подтверждения запуска рассылки."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="\U0001f680 \u041d\u0430\u0447\u0430\u0442\u044c \u0440\u0430\u0441\u0441\u044b\u043b\u043a\u0443", payload="admin_broadcast_start"),
    )
    builder.row(
        CallbackButton(text="\u274c \u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c", payload="admin_broadcast_cancel"),
    )
    return builder.as_markup()


def admin_broadcast_running_keyboard():
    """Возвращает клавиатуру управления запущенной рассылкой."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="\u26d4 \u041e\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c", payload="admin_broadcast_stop"),
    )
    return builder.as_markup()
