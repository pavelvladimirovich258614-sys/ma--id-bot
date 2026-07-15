"""
Обработчики админ-панели и конструктора рассылок.
"""
import json
import logging
import time
from typing import Any

from maxapi.types import Command, MessageCreated, MessageCallback
from maxapi.enums.parse_mode import ParseMode, TextFormat

from config import ADMIN_USER_IDS, BROADCAST_LIVE_ENABLED
from database.admin_storage import (
    add_broadcast_recipients,
    count_bot_users,
    create_broadcast,
    get_broadcast,
    get_broadcast_recipients,
    get_bot_users,
    init_admin_db,
    update_broadcast,
)
from keyboards.admin import (
    admin_broadcast_button_keyboard,
    admin_broadcast_image_keyboard,
    admin_broadcast_launch_keyboard,
    admin_broadcast_preview_keyboard,
    admin_broadcast_running_keyboard,
    admin_broadcast_text_keyboard,
    admin_panel_keyboard,
)
from tasks.broadcast_worker import start_broadcast, stop_broadcast

logger = logging.getLogger(__name__)

_admin_states: dict[int, dict[str, Any]] = {}
BROADCAST_STATE_TTL = 1800


def _set_admin_state(user_id: int, state: str, **kwargs: Any) -> None:
    _admin_states[int(user_id)] = {
        "state": state,
        "timestamp": time.time(),
        **kwargs,
    }


def _get_admin_state(user_id: int) -> dict[str, Any] | None:
    state_data = _admin_states.get(int(user_id))
    if not state_data:
        return None

    if time.time() - state_data["timestamp"] > BROADCAST_STATE_TTL:
        _admin_states.pop(int(user_id), None)
        return None

    return state_data


def _clear_admin_state(user_id: int) -> None:
    _admin_states.pop(int(user_id), None)


def _is_admin(user_id: int) -> bool:
    return int(user_id) in {int(uid) for uid in ADMIN_USER_IDS}


def _extract_chat_id(event: Any) -> int | None:
    candidates = [
        getattr(event, "chat_id", None),
        getattr(getattr(getattr(event, "message", None), "recipient", None), "chat_id", None),
    ]
    for candidate in candidates:
        if candidate is not None:
            return candidate
    return None


def _extract_user_id(event: Any) -> int | None:
    callback = getattr(event, "callback", None)
    if callback is not None:
        user = getattr(callback, "user", None)
        if user is not None:
            return int(getattr(user, "user_id", 0) or 0)

    from_user = getattr(event, "from_user", None)
    if from_user is not None:
        return int(getattr(from_user, "user_id", 0) or 0)

    return None


async def _answer(event: Any, notification: str = "Готово") -> None:
    try:
        await event.bot.send_callback(
            callback_id=event.callback.callback_id,
            notification=notification,
        )
    except Exception as exc:
        logger.warning("Не удалось ответить на callback: %s", exc)


async def _send_message(event: Any, text: str, attachments: Any = None, text_format: str = "markdown") -> None:
    message = getattr(event, "message", None)
    if message is not None and callable(getattr(message, "answer", None)):
        await message.answer(text=text, attachments=attachments)
        return

    chat_id = _extract_chat_id(event)
    if chat_id is None:
        return

    format_mode = TextFormat.MARKDOWN if text_format == "markdown" else None
    await event.bot.send_message(chat_id=chat_id, text=text, attachments=attachments, format=format_mode)

async def handle_admin_command(event: MessageCreated) -> None:
    user_id = _extract_user_id(event)
    if user_id is None or not _is_admin(user_id):
        await _send_message(event, "Команда недоступна.")
        return

    _set_admin_state(user_id, "admin_panel")
    await _send_message(
        event,
        "Панель администратора",
        attachments=[admin_panel_keyboard()],
    )


async def handle_admin_callback(event: MessageCallback) -> None:
    user_id = _extract_user_id(event)
    if user_id is None or not _is_admin(user_id):
        await _answer(event, "Доступ запрещен")
        return

    payload = event.callback.payload
    state = _get_admin_state(user_id)

    if payload == "admin_close":
        _clear_admin_state(user_id)
        await _send_message(event, "Панель закрыта", attachments=[None])
        await _answer(event, "Закрыто")
        return

    if payload == "admin_broadcast_new":
        _set_admin_state(
            user_id,
            "broadcast_image",
            image_file_id=None,
            image_content_type=None,
            text=None,
            format="markdown",
            button_text=None,
            button_url=None,
            broadcast_id=None,
        )
        await _send_message(
            event,
            "Шаг 1 из 3: изображение",
            attachments=[admin_broadcast_image_keyboard()],
        )
        await _answer(event, "Шаг 1")
        return

    if payload == "admin_broadcast_last":
        await _handle_last_broadcast(event, user_id)
        await _answer(event, "Готово")
        return

    if not state:
        await _answer(event, "Сессия истекла, откройте /admin заново")
        return

    current_state = state["state"]

    if current_state == "admin_panel":
        if payload == "admin_broadcast_new":
            _set_admin_state(
                user_id,
                "broadcast_image",
                image_file_id=None,
                image_content_type=None,
                text=None,
                format="markdown",
                button_text=None,
                button_url=None,
                broadcast_id=None,
            )
            await _send_message(
                event,
                "Шаг 1 из 3: изображение",
                attachments=[admin_broadcast_image_keyboard()],
            )
        elif payload == "admin_broadcast_last":
            await _handle_last_broadcast(event, user_id)
        await _answer(event, "Готово")
        return

    if current_state == "broadcast_image":
        await _handle_broadcast_image(event, user_id, state, payload)
        await _answer(event, "Готово")
        return

    if current_state == "broadcast_text":
        await _handle_broadcast_text(event, user_id, state, payload)
        await _answer(event, "Готово")
        return

    if current_state in ("broadcast_button", "broadcast_button_text", "broadcast_button_url"):
        await _handle_broadcast_button(event, user_id, state, payload)
        await _answer(event, "Готово")
        return

    if current_state == "broadcast_preview":
        await _handle_broadcast_preview(event, user_id, state, payload)
        await _answer(event, "Готово")
        return

    if current_state == "broadcast_launch":
        await _handle_broadcast_launch(event, user_id, state, payload)
        await _answer(event, "Готово")
        return

    if current_state == "broadcast_running":
        if payload == "admin_broadcast_stop":
            broadcast_id = state.get("broadcast_id")
            if broadcast_id:
                stop_broadcast(broadcast_id)
            _clear_admin_state(user_id)
            await _send_message(event, "Рассылка остановлена", attachments=[admin_panel_keyboard()])
        await _answer(event, "Готово")
        return

    await _answer(event, "Неизвестное состояние")


async def handle_admin_message(event: MessageCreated) -> None:
    user_id = _extract_user_id(event)
    if user_id is None or not _is_admin(user_id):
        return

    state = _get_admin_state(user_id)
    if not state:
        return

    current_state = state["state"]
    if current_state == "broadcast_text":
        await _handle_broadcast_text_input(event, user_id, state)
        return

    if current_state == "broadcast_button_text":
        await _handle_broadcast_button_input_text(event, user_id, state)
        return

    if current_state in ("broadcast_button", "broadcast_button_url"):
        await _handle_broadcast_button_input(event, user_id, state)
        return

    if current_state == "broadcast_image" and event.message.body and event.message.body.attachments:
        await _handle_broadcast_image_upload(event, user_id, state)
        return


async def _handle_broadcast_launch(
    event: MessageCallback,
    user_id: int,
    state: dict[str, Any],
    payload: str,
) -> None:
    if payload == "admin_broadcast_start":
        if not BROADCAST_LIVE_ENABLED:
            await _send_message(
                event,
                "Рассылки отключены. Обратитесь к владельцу бота для включения.",
                attachments=[admin_broadcast_launch_keyboard(0)],
            )
            await _answer(event, "Отключено")
            return

        broadcast_id = state.get("broadcast_id")
        if not broadcast_id:
            await _answer(event, "Рассылка не найдена")
            return

        try:
            await start_broadcast(broadcast_id, event.bot)
            _set_admin_state(
                user_id,
                "broadcast_running",
                image_file_id=state.get("image_file_id"),
                image_content_type=state.get("image_content_type"),
                text=state.get("text"),
                format=state.get("format", "markdown"),
                button_text=state.get("button_text"),
                button_url=state.get("button_url"),
                broadcast_id=broadcast_id,
            )
            await _send_message(
                event,
                "Рассылка запущена",
                attachments=[admin_broadcast_running_keyboard()],
            )
        except Exception as exc:
            logger.error("Не удалось запустить рассылку %s: %s", broadcast_id, exc)
            await _send_message(
                event,
                "Ошибка запуска рассылки",
                attachments=[admin_broadcast_launch_keyboard(0)],
            )
        await _answer(event, "Готово")
        return

    if payload == "admin_broadcast_cancel":
        _clear_admin_state(user_id)
        await _send_message(event, "Отменено", attachments=[admin_panel_keyboard()])
        await _answer(event, "Отменено")
        return

    await _answer(event, "Неизвестное действие")


def register_admin_handlers(dp: Any) -> None:
    """Регистрирует обработчики админ-панели."""
    dp.message_created(Command("admin"))(handle_admin_command)
    dp.message_callback()(handle_admin_callback)
    dp.message_created()(handle_admin_message)

async def _handle_last_broadcast(event: MessageCreated, user_id: int) -> None:
    broadcast_id = _get_last_broadcast_id(user_id)
    if not broadcast_id:
        await _send_message(event, "Рассылок еще не было", attachments=[admin_panel_keyboard()])
        return

    broadcast = get_broadcast(broadcast_id)
    if not broadcast:
        await _send_message(event, "Рассылка не найдена", attachments=[admin_panel_keyboard()])
        return

    bid = broadcast.get("id", "")
    bstatus = broadcast.get("status", "")
    btotal = broadcast.get("total", 0)
    bsent = broadcast.get("sent", 0)
    bfailed = broadcast.get("failed", 0)
    bcreated = broadcast.get("created_at", "")
    text = (
        "Рассылка #" + str(bid) + "\n"
        "Статус: " + str(bstatus) + "\n"
        "Всего: " + str(btotal) + "\n"
        "Отправлено: " + str(bsent) + "\n"
        "Ошибок: " + str(bfailed) + "\n"
        "Создана: " + str(bcreated)
    )
    await _send_message(event, text, attachments=[admin_panel_keyboard()])


def _get_last_broadcast_id(user_id: int) -> int | None:
    import sqlite3
    from database.storage import DB_PATH

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id FROM broadcasts WHERE admin_user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()

    return row[0] if row else None

async def _handle_broadcast_image(
    event: MessageCallback,
    user_id: int,
    state: dict[str, Any],
    payload: str,
) -> None:
    if payload == "admin_broadcast_add_image":
        _set_admin_state(
            user_id,
            "broadcast_image",
            image_file_id=state.get("image_file_id"),
            image_content_type=state.get("image_content_type"),
            text=state.get("text"),
            format=state.get("format", "markdown"),
            button_text=state.get("button_text"),
            button_url=state.get("button_url"),
            broadcast_id=state.get("broadcast_id"),
        )
        await _send_message(
            event,
            "Отправьте изображение для рассылки.\nМожно отправить одно изображение.",
            attachments=[admin_broadcast_image_keyboard()],
        )
        return

    if payload == "admin_broadcast_skip_image":
        _set_admin_state(
            user_id,
            "broadcast_text",
            image_file_id=None,
            image_content_type=None,
            text=state.get("text"),
            format=state.get("format", "markdown"),
            button_text=state.get("button_text"),
            button_url=state.get("button_url"),
            broadcast_id=state.get("broadcast_id"),
        )
        await _send_message(
            event,
            "Шаг 2 из 3: текст рассылки\n\nОтправьте текст сообщения (1–4000 символов).",
            attachments=[admin_broadcast_text_keyboard()],
        )
        return

    if payload == "admin_broadcast_cancel":
        _clear_admin_state(user_id)
        await _send_message(event, "Отменено", attachments=[admin_panel_keyboard()])


async def _handle_broadcast_image_upload(
    event: MessageCreated,
    user_id: int,
    state: dict[str, Any],
) -> None:
    attachments = getattr(event.message.body, "attachments", None) or []
    image_attachment = None
    for attachment in attachments:
        if getattr(attachment, "type", None) == "image":
            image_attachment = attachment
            break

    if image_attachment is None:
        await _send_message(
            event,
            "Вложение не является изображением. Отправьте изображение.",
            attachments=[admin_broadcast_image_keyboard()],
        )
        return

    payload = getattr(image_attachment, "payload", None)
    token = getattr(payload, "token", None) if payload else None
    url = getattr(payload, "url", None) if payload else None
    content_type = getattr(image_attachment, "content_type", None) or "image/jpeg"

    image_payload = None
    if token:
        image_payload = {"token": token}
    elif url:
        image_payload = {"url": url}

    if not image_payload:
        await _send_message(
            event,
            "Не удалось получить изображение. Попробуйте отправить снова.",
            attachments=[admin_broadcast_image_keyboard()],
        )
        return

    _set_admin_state(
        user_id,
        "broadcast_text",
        image_file_id=json.dumps(image_payload),
        image_content_type=content_type,
        text=state.get("text"),
        format=state.get("format", "markdown"),
        button_text=state.get("button_text"),
        button_url=state.get("button_url"),
        broadcast_id=state.get("broadcast_id"),
    )
    await _send_message(
        event,
        "Изображение добавлено.\nШаг 2 из 3: текст рассылки\n\nОтправьте текст сообщения (1–4000 символов).",
        attachments=[admin_broadcast_text_keyboard()],
    )

async def _handle_broadcast_text(
    event: MessageCallback,
    user_id: int,
    state: dict[str, Any],
    payload: str,
) -> None:
    if payload == "admin_broadcast_cancel":
        _clear_admin_state(user_id)
        await _send_message(event, "Отменено", attachments=[admin_panel_keyboard()])
        return

    await _send_message(
        event,
        "Введите текст рассылки (1–4000 символов):",
        attachments=[admin_broadcast_text_keyboard()],
    )


async def _handle_broadcast_text_input(
    event: MessageCreated,
    user_id: int,
    state: dict[str, Any],
) -> None:
    text = (event.message.body.text or "").strip()
    if not text:
        await _send_message(
            event,
            "Текст не может быть пустым. Введите текст рассылки:",
            attachments=[admin_broadcast_text_keyboard()],
        )
        return

    if len(text) > 4000:
        await _send_message(
            event,
            "Текст слишком длинный: " + str(len(text)) + "/4000 символов. Сократите текст.",
            attachments=[admin_broadcast_text_keyboard()],
        )
        return

    _set_admin_state(
        user_id,
        "broadcast_button",
        image_file_id=state.get("image_file_id"),
        image_content_type=state.get("image_content_type"),
        text=text,
        format=state.get("format", "markdown"),
        button_text=state.get("button_text"),
        button_url=state.get("button_url"),
        broadcast_id=state.get("broadcast_id"),
    )
    await _send_message(
        event,
        "Шаг 3 из 3: кнопка",
        attachments=[admin_broadcast_button_keyboard()],
    )


async def _handle_broadcast_button(
    event: MessageCallback,
    user_id: int,
    state: dict[str, Any],
    payload: str,
) -> None:
    if payload == "admin_broadcast_add_button":
        _set_admin_state(
            user_id,
            "broadcast_button_text",
            image_file_id=state.get("image_file_id"),
            image_content_type=state.get("image_content_type"),
            text=state.get("text"),
            format=state.get("format", "markdown"),
            button_text=state.get("button_text"),
            button_url=state.get("button_url"),
            broadcast_id=state.get("broadcast_id"),
        )
        await _send_message(
            event,
            "Отправьте текст кнопки:",
            attachments=[admin_broadcast_text_keyboard()],
        )
        return

    if payload == "admin_broadcast_skip_button":
        await _show_broadcast_preview(event, user_id, state)
        return

    if payload == "admin_broadcast_cancel":
        _clear_admin_state(user_id)
        await _send_message(event, "Отменено", attachments=[admin_panel_keyboard()])


async def _handle_broadcast_button_input(
    event: MessageCreated,
    user_id: int,
    state: dict[str, Any],
) -> None:
    text = (event.message.body.text or "").strip()
    if not text:
        await _send_message(event, "URL не может быть пустым. Отправьте URL:")
        return

    if len(text) > 2048:
        await _send_message(
            event,
            "URL слишком длинный: " + str(len(text)) + "/2048 символов.",
        )
        return

    if not text.lower().startswith("http://") and not text.lower().startswith("https://"):
        await _send_message(
            event,
            "URL должен начинаться с http:// или https://. Отправьте URL:",
        )
        return

    await _show_broadcast_preview(
        event,
        user_id,
        {
            "state": state["state"],
            "image_file_id": state.get("image_file_id"),
            "image_content_type": state.get("image_content_type"),
            "text": state.get("text"),
            "format": state.get("format", "markdown"),
            "button_text": state.get("button_text") or "Перейти",
            "button_url": text,
            "broadcast_id": state.get("broadcast_id"),
            "timestamp": state["timestamp"],
        },
    )


async def _handle_broadcast_button_input_text(
    event: MessageCreated,
    user_id: int,
    state: dict[str, Any],
) -> None:
    text = (event.message.body.text or "").strip()
    if not text:
        await _send_message(event, "Текст кнопки не может быть пустым. Отправьте текст:")
        return

    _set_admin_state(
        user_id,
        "broadcast_button_url",
        image_file_id=state.get("image_file_id"),
        image_content_type=state.get("image_content_type"),
        text=state.get("text"),
        format=state.get("format", "markdown"),
        button_text=text,
        button_url=state.get("button_url"),
        broadcast_id=state.get("broadcast_id"),
    )
    await _send_message(event, "Отправьте URL кнопки (http/https, до 2048 символов):")

async def _show_broadcast_preview(
    event: Any,
    user_id: int,
    state: dict[str, Any],
) -> None:
    text = state.get("text", "")
    text_format = state.get("format", "markdown")
    image_file_id = state.get("image_file_id")
    button_text = state.get("button_text")
    button_url = state.get("button_url")

    broadcast = create_broadcast(
        admin_user_id=user_id,
        text=text,
        format=text_format,
        image_file_id=image_file_id,
        image_content_type=state.get("image_content_type"),
        button_text=button_text,
        button_url=button_url,
    )
    broadcast_id = broadcast["id"]

    _set_admin_state(
        user_id,
        "broadcast_preview",
        image_file_id=image_file_id,
        image_content_type=state.get("image_content_type"),
        text=text,
        format=text_format,
        button_text=button_text,
        button_url=button_url,
        broadcast_id=broadcast_id,
    )

    attachments = []
    if image_file_id:
        try:
            payload = json.loads(image_file_id)
            if not isinstance(payload, dict):
                payload = {"token": str(image_file_id)}
        except json.JSONDecodeError:
            payload = {"token": str(image_file_id)}

        attachments.append(
            {
                "type": (state.get("image_content_type") or "image/jpeg").split("/")[0],
                "payload": payload,
            }
        )

    inline_keyboard = None
    if button_text and button_url:
        from maxapi.types import LinkButton
        from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.row(LinkButton(text=button_text, url=button_url))
        inline_keyboard = builder.as_markup()

    if inline_keyboard:
        attachments.append(inline_keyboard)

    await _send_message(
        event,
        "Предпросмотр рассылки:",
        attachments=attachments if attachments else None,
        text_format=text_format,
    )
    await _send_message(
        event,
        "Это точная копия того, что получат пользователи.",
        attachments=[admin_broadcast_preview_keyboard()],
    )


async def _handle_broadcast_preview(
    event: MessageCallback,
    user_id: int,
    state: dict[str, Any],
    payload: str,
) -> None:
    if payload == "admin_broadcast_confirm":
        broadcast_id = state.get("broadcast_id")
        total_recipients = count_bot_users()
        update_broadcast(broadcast_id, total=total_recipients)

        _set_admin_state(
            user_id,
            "broadcast_launch",
            image_file_id=state.get("image_file_id"),
            image_content_type=state.get("image_content_type"),
            text=state.get("text"),
            format=state.get("format", "markdown"),
            button_text=state.get("button_text"),
            button_url=state.get("button_url"),
            broadcast_id=broadcast_id,
        )
        await _send_message(
            event,
            "Получателей: " + str(total_recipients) + "\n\nЗапустить рассылку?",
            attachments=[admin_broadcast_launch_keyboard(total_recipients)],
        )
        return

    if payload == "admin_broadcast_edit_text":
        _set_admin_state(
            user_id,
            "broadcast_text",
            image_file_id=state.get("image_file_id"),
            image_content_type=state.get("image_content_type"),
            text=None,
            format=state.get("format", "markdown"),
            button_text=state.get("button_text"),
            button_url=state.get("button_url"),
            broadcast_id=state.get("broadcast_id"),
        )
        await _send_message(
            event,
            "Отправьте новый текст рассылки (1–4000 символов):",
            attachments=[admin_broadcast_text_keyboard()],
        )
        return

    if payload == "admin_broadcast_edit_image":
        _set_admin_state(
            user_id,
            "broadcast_image",
            image_file_id=None,
            image_content_type=None,
            text=state.get("text"),
            format=state.get("format", "markdown"),
            button_text=state.get("button_text"),
            button_url=state.get("button_url"),
            broadcast_id=state.get("broadcast_id"),
        )
        await _send_message(
            event,
            "Шаг 1 из 3: изображение",
            attachments=[admin_broadcast_image_keyboard()],
        )
        return

    if payload == "admin_broadcast_edit_button":
        _set_admin_state(
            user_id,
            "broadcast_button",
            image_file_id=state.get("image_file_id"),
            image_content_type=state.get("image_content_type"),
            text=state.get("text"),
            format=state.get("format", "markdown"),
            button_text=None,
            button_url=None,
            broadcast_id=state.get("broadcast_id"),
        )
        await _send_message(
            event,
            "Шаг 3 из 3: кнопка",
            attachments=[admin_broadcast_button_keyboard()],
        )
        return

    if payload == "admin_broadcast_cancel":
        _clear_admin_state(user_id)
        await _send_message(event, "Отменено", attachments=[admin_panel_keyboard()])
