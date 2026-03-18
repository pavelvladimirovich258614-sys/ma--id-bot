from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types import CallbackButton


WELCOME_TEXT = """<b>👋 Добро пожаловать!</b>

Я бот для получения <i>ID</i> различных сущностей в MAX.

Выберите, что хотите узнать:
• <code>ID чата</code> — добавьте меня в группу
• <code>ID канала</code> — добавьте меня в канал
• <code>ID пользователя</code> — перешлите сообщение от пользователя
• <code>ID бота</code> — перешлите сообщение от бота
• <code>ID стикера</code> — пришлите стикер"""


def main_menu_keyboard():
    """Возвращает главную клавиатуру бота."""
    builder = InlineKeyboardBuilder()
    
    # Первый ряд: Чат и Канал
    builder.row(
        CallbackButton(text="💬 Чат", payload="get_chat_id"),
        CallbackButton(text="📣 Канал", payload="get_channel_id")
    )
    
    # Второй ряд: Пользователь и Бот
    builder.row(
        CallbackButton(text="👤 Пользователь", payload="get_user_id"),
        CallbackButton(text="🤖 Бот", payload="get_bot_id")
    )
    
    # Третий ряд: Стикер (на всю ширину)
    builder.row(
        CallbackButton(text="🎟 Стикер", payload="get_sticker_info")
    )
    
    return builder.as_markup()


def dismiss_keyboard():
    """Возвращает клавиатуру с кнопкой 'Прочитано' для удаления сообщения."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="✅ Прочитано", payload="dismiss")
    )
    return builder.as_markup()
