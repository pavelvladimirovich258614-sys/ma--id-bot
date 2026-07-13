from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


WELCOME_TEXT = """👋 Добро пожаловать!

Я бот для получения ID различных сущностей в MAX.

Выберите, что хотите узнать:
• ID чата — добавьте меня в группу
• ID канала — добавьте меня в канал
• ID пользователя — перешлите сообщение от пользователя
• ID бота — перешлите сообщение от бота
• ID стикера — пришлите стикер
• Разведка ID — найдите ID по ссылке или сообщению"""


def main_menu_keyboard():
    """Возвращает главную клавиатуру бота."""
    builder = InlineKeyboardBuilder()

    builder.row(
        CallbackButton(text="💬 Чат", payload="get_chat_id"),
        CallbackButton(text="📣 Канал", payload="get_channel_id"),
    )
    builder.row(
        CallbackButton(text="👤 Пользователь", payload="get_user_id"),
        CallbackButton(text="🤖 Бот", payload="get_bot_id"),
    )
    builder.row(
        CallbackButton(text="🎟 Стикер", payload="get_sticker_info"),
    )
    builder.row(
        CallbackButton(text="🔍 Разведка ID", payload="harvest_menu"),
    )

    return builder.as_markup()


def id_harvest_keyboard():
    """Возвращает подменю модуля разведки ID."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="🆔 ID по ссылке", payload="harvest_by_link"),
    )
    builder.row(
        CallbackButton(text="✉️ ID по сообщению", payload="harvest_by_message"),
    )
    builder.row(
        CallbackButton(text="🤖 ID этого бота", payload="harvest_bot_id"),
    )
    builder.row(
        CallbackButton(text="⬅️ Назад", payload="harvest_back"),
    )
    return builder.as_markup()


def dismiss_keyboard():
    """Возвращает клавиатуру с кнопкой 'Прочитано' для удаления сообщения."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="✅ Прочитано", payload="dismiss"),
    )
    return builder.as_markup()
