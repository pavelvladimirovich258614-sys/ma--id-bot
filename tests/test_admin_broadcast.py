import asyncio
import hashlib
import json
import os
import tempfile

TMP_DIR = tempfile.mkdtemp(prefix="maxidbot_tests_")
TEST_DB_PATH = os.path.join(TMP_DIR, "test.sqlite3")
os.environ["MAXIDBOT_DB_PATH"] = TEST_DB_PATH

PROD_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "users.sqlite3"
)


def assert_production_db_untouched() -> None:
    if os.path.exists(PROD_DB_PATH):
        with open(PROD_DB_PATH, "rb") as f:
            prod_hash = hashlib.sha256(f.read()).hexdigest()
        assert prod_hash != hashlib.sha256(b"").hexdigest()


"""
Тесты админ-панели и конструктора рассылок.
"""
import asyncio
import logging
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path("/opt/ma--id-bot")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import ADMIN_USER_IDS
from database.admin_storage import (
    add_broadcast_recipients,
    count_bot_users,
    create_broadcast,
    get_broadcast,
    get_broadcast_recipients,
    get_bot_users,
    init_admin_db,
    update_broadcast,
    update_recipient_status,
)
from database.storage import init_db
from handlers.admin import (
    _handle_broadcast_image_upload,
      _handle_broadcast_button,
    _clear_admin_state,
    _get_admin_state,
    _is_admin,
    _set_admin_state,
    _handle_broadcast_button_input,
    _handle_broadcast_button_input_text,
    _handle_broadcast_launch,
    _handle_broadcast_preview,
    _handle_broadcast_text,
      _handle_broadcast_text_input,
    _send_message,
    _show_broadcast_preview,
    handle_admin_callback,
    handle_admin_command,
    handle_admin_message,
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
from maxapi.enums.parse_mode import TextFormat
from tasks.broadcast_worker import BroadcastWorker


class AdminAccessTests(unittest.TestCase):
    def setUp(self):
        init_admin_db()

    def test_admin_user_ids_parsed(self):
        self.assertIsInstance(ADMIN_USER_IDS, set)
        self.assertIn(73412011, ADMIN_USER_IDS)

    def test_is_admin_true(self):
        self.assertTrue(_is_admin(73412011))

    def test_is_admin_false(self):
        self.assertFalse(_is_admin(123456789))


class AdminPanelTests(unittest.TestCase):
    def setUp(self):
        init_admin_db()
        _clear_admin_state(73412011)

    def _fake_event(self, user_id, payload=None, text=None, chat_id=123):
        user = types.SimpleNamespace(user_id=user_id)
        event_kwargs = {
            "user_id": user_id,
            "from_user": user,
            "chat_id": chat_id,
            "bot": types.SimpleNamespace(
                send_message=lambda **kwargs: asyncio.sleep(0),
                send_callback=lambda **kwargs: asyncio.sleep(0),
            ),
            "message": types.SimpleNamespace(
                recipient=types.SimpleNamespace(chat_id=chat_id),
                body=types.SimpleNamespace(
                    text=text or "",
                    attachments=[],
                ),
                link=None,
                answer=lambda **kwargs: asyncio.sleep(0),
                edit=None,
            ),
        }
        if payload is not None:
            event_kwargs["callback"] = types.SimpleNamespace(
                user=user,
                callback_id="callback_id",
                payload=payload,
            )
        return types.SimpleNamespace(**event_kwargs)

    def test_admin_command_opens_panel(self):
        with mock.patch("handlers.admin._send_message") as mock_send:
            async def run():
                event = self._fake_event(73412011)
                event.message = types.SimpleNamespace(
                    body=types.SimpleNamespace(text="/admin", attachments=[]),
                    answer=lambda **kwargs: asyncio.sleep(0),
                )
                event.from_user = types.SimpleNamespace(user_id=73412011)
                await handle_admin_command(event)

            asyncio.run(run())
            self.assertTrue(mock_send.called)

    def test_non_admin_cannot_open_panel(self):
        with mock.patch("handlers.admin._send_message") as mock_send:
            async def run():
                event = self._fake_event(999999999)
                event.message = types.SimpleNamespace(
                    body=types.SimpleNamespace(text="/admin", attachments=[]),
                    answer=lambda **kwargs: asyncio.sleep(0),
                )
                event.from_user = types.SimpleNamespace(user_id=999999999)
                await handle_admin_command(event)

            asyncio.run(run())
            mock_send.assert_called_with(mock.ANY, "Доступ запрещен")

    def test_fake_admin_callback_blocked(self):
        async def run():
            event = self._fake_event(999999999, payload="admin_broadcast_new")
            await handle_admin_callback(event)

        with mock.patch("handlers.admin._answer") as mock_answer:
            asyncio.run(run())
            mock_answer.assert_called_with(mock.ANY, "Доступ запрещен")

class BroadcastConstructorTests(unittest.TestCase):
    def setUp(self):
        init_admin_db()
        _clear_admin_state(73412011)

    def _fake_event(self, user_id, payload=None, text=None, chat_id=123):
        user = types.SimpleNamespace(user_id=user_id)
        event_kwargs = {
            "user_id": user_id,
            "from_user": user,
            "chat_id": chat_id,
            "bot": types.SimpleNamespace(
                send_message=lambda **kwargs: asyncio.sleep(0),
                send_callback=lambda **kwargs: asyncio.sleep(0),
            ),
            "message": types.SimpleNamespace(
                recipient=types.SimpleNamespace(chat_id=chat_id),
                body=types.SimpleNamespace(
                    text=text or "",
                    attachments=[],
                ),
                link=None,
                answer=lambda **kwargs: asyncio.sleep(0),
                edit=None,
            ),
        }
        if payload is not None:
            event_kwargs["callback"] = types.SimpleNamespace(
                user=user,
                callback_id="callback_id",
                payload=payload,
            )
        return types.SimpleNamespace(**event_kwargs)

    def test_image_can_be_added_or_skipped(self):
        _set_admin_state(
            73412011,
            "broadcast_image",
            image_file_id=None,
            image_content_type=None,
            text=None,
            format="markdown",
            button_text=None,
            button_url=None,
            broadcast_id=None,
        )

        event = self._fake_event(73412011, payload="admin_broadcast_skip_image")
        with mock.patch("handlers.admin._send_message") as mock_send:
            asyncio.run(handle_admin_callback(event))
            self.assertTrue(mock_send.called)
            call_args = mock_send.call_args[0]
            self.assertIn("текст рассылки", call_args[1])

    def test_text_cannot_be_skipped(self):
        _set_admin_state(
            73412011,
            "broadcast_text",
            image_file_id=None,
            image_content_type=None,
            text=None,
            format="markdown",
            button_text=None,
            button_url=None,
            broadcast_id=None,
        )

        event = self._fake_event(73412011, payload="admin_broadcast_cancel")
        with mock.patch("handlers.admin._send_message") as mock_send:
            asyncio.run(handle_admin_callback(event))
            self.assertTrue(mock_send.called)

    def test_text_length_limit(self):
        _set_admin_state(
            73412011,
            "broadcast_text",
            image_file_id=None,
            image_content_type=None,
            text=None,
            format="markdown",
            button_text=None,
            button_url=None,
            broadcast_id=None,
        )

        event = self._fake_event(73412011, text="x" * 4001)
        with mock.patch("handlers.admin._send_message") as mock_send:
            asyncio.run(handle_admin_message(event))
            self.assertTrue(mock_send.called)
            call_args = mock_send.call_args[0]
            self.assertIn("4001", call_args[1])

    def test_button_can_be_added_or_skipped(self):
        _set_admin_state(
            73412011,
            "broadcast_button",
            image_file_id=None,
            image_content_type=None,
            text="test",
            format="markdown",
            button_text=None,
            button_url=None,
            broadcast_id=None,
        )

        event = self._fake_event(73412011, payload="admin_broadcast_skip_button")
        with mock.patch("handlers.admin._show_broadcast_preview") as mock_preview:
            asyncio.run(handle_admin_callback(event))
            self.assertTrue(mock_preview.called)

    def test_button_url_validated(self):
        _set_admin_state(
            73412011,
            "broadcast_button_url",
            image_file_id=None,
            image_content_type=None,
            text="test",
            format="markdown",
            button_text=None,
            button_url=None,
            broadcast_id=None,
        )

        event = self._fake_event(73412011, text="javascript:alert(1)")
        with mock.patch("handlers.admin._send_message") as mock_send:
            asyncio.run(handle_admin_message(event))
            self.assertTrue(mock_send.called)
            call_args = mock_send.call_args[0]
            self.assertIn("http", call_args[1])

    def test_preview_matches_final_payload(self):
        _set_admin_state(
            73412011,
            "broadcast_preview",
            image_file_id=None,
            image_content_type=None,
            text="test message",
            format="markdown",
            button_text="Go",
            button_url="https://example.com",
            broadcast_id=1,
        )

        state = _get_admin_state(73412011)
        self.assertEqual(state["text"], "test message")
        self.assertEqual(state["button_text"], "Go")
        self.assertEqual(state["button_url"], "https://example.com")

    def test_admin_buttons_not_sent_to_recipients(self):
        from maxapi.types import CallbackButton
        from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

        builder = InlineKeyboardBuilder()
        builder.row(CallbackButton(text="Остановить", payload="admin_broadcast_stop"))

        for row in builder.as_markup().payload.buttons:
            for button in row:
                self.assertEqual(button.payload, "admin_broadcast_stop")

class BroadcastStorageTests(unittest.TestCase):
    def setUp(self):
        import asyncio
        asyncio.run(init_db())
        init_admin_db()
        _clear_admin_state(73412011)
    def setUp(self):
        import asyncio
        asyncio.run(init_db())
        init_admin_db()

    def test_recipients_from_bot_users_only(self):
        create_broadcast(admin_user_id=73412011, text="test")
        broadcast = get_broadcast(1)
        self.assertIsNotNone(broadcast)

    def test_duplicate_user_ids_removed(self):
        create_broadcast(admin_user_id=73412011, text="test")
        add_broadcast_recipients(1, [1, 2, 2, 3])
        recipients = get_broadcast_recipients(1)
        user_ids = [r["user_id"] for r in recipients]
        self.assertEqual(len(user_ids), len(set(user_ids)))

    def test_chats_and_channels_not_in_recipients(self):
        user_ids = get_bot_users()
        for uid in user_ids:
            self.assertIsInstance(uid, int)
            self.assertGreater(uid, 0)


class BroadcastWorkerTests(unittest.TestCase):
    def setUp(self):
        init_admin_db()

    def test_only_one_broadcast_at_a_time(self):
        worker = BroadcastWorker()
        self.assertFalse(worker.is_running(1))

    def test_worker_does_not_auto_start_after_restart(self):
        create_broadcast(admin_user_id=73412011, text="restart test")
        update_broadcast(1, status="interrupted")
        broadcast = get_broadcast(1)
        self.assertEqual(broadcast["status"], "interrupted")

    def test_secrets_not_logged(self):
        logger = logging.getLogger("tasks.broadcast_worker")
        with self.assertLogs(logger, level="INFO") as cm:
            logger.info("test message")
        for record in cm.records:
            self.assertNotIn("secret", record.getMessage())
            self.assertNotIn("secret", str(record.args))

    def test_successful_send_records_sent(self):
        create_broadcast(admin_user_id=73412011, text="test")
        add_broadcast_recipients(1, [1])
        update_recipient_status(1, 1, status="sent")
        recipients = get_broadcast_recipients(1)
        self.assertEqual(recipients[0]["status"], "sent")

    def test_one_user_error_does_not_stop_others(self):
        create_broadcast(admin_user_id=73412011, text="test")
        add_broadcast_recipients(1, [1, 2, 3])
        update_recipient_status(1, 1, status="failed")
        update_recipient_status(1, 2, status="pending")
        update_recipient_status(1, 3, status="pending")
        pending = [r for r in get_broadcast_recipients(1) if r["status"] == "pending"]
        self.assertEqual(len(pending), 2)

    def test_retry_limit(self):
        worker = BroadcastWorker()
        self.assertEqual(worker._extract_status_code(Exception("429 Too Many Requests")), 429)

    def test_admin_stop_works(self):
        worker = BroadcastWorker()
        self.assertFalse(worker.is_running(99))
        worker._stop_flags[99] = True
        self.assertTrue(worker._stop_flags[99])

    def test_progress_counted_correctly(self):
        create_broadcast(admin_user_id=73412011, text="progress")
        update_broadcast(1, sent=5, failed=2, total=10)
        broadcast = get_broadcast(1)
        self.assertEqual(broadcast["sent"], 5)
        self.assertEqual(broadcast["failed"], 2)

    def test_401_stops_task(self):
        worker = BroadcastWorker()
        exc = Exception("401 Unauthorized")
        exc.status_code = 401
        self.assertEqual(worker._extract_status_code(exc), 401)

    def test_403_stops_task(self):
        worker = BroadcastWorker()
        exc = Exception("403 Forbidden")
        exc.status_code = 403
        self.assertEqual(worker._extract_status_code(exc), 403)


class BroadcastKeyboardTests(unittest.TestCase):
    def _flat_payloads(self, kb):
        buttons = getattr(kb, "payload", None)
        if buttons is None:
            return []
        rows = getattr(buttons, "buttons", [])
        flat = []
        for row in rows:
            for button in row:
                flat.append(getattr(button, "payload", None))
        return flat

    def test_admin_panel_keyboard_has_required_buttons(self):
        kb = admin_panel_keyboard()
        self.assertIsNotNone(kb)
        flat = self._flat_payloads(kb)

        self.assertIn("admin_broadcast_new", flat)
        self.assertIn("admin_broadcast_last", flat)
        self.assertIn("admin_close", flat)

    def test_image_keyboard_has_required_buttons(self):
        kb = admin_broadcast_image_keyboard()
        flat = self._flat_payloads(kb)

        self.assertIn("admin_broadcast_add_image", flat)
        self.assertIn("admin_broadcast_skip_image", flat)
        self.assertIn("admin_broadcast_cancel", flat)

    def test_text_keyboard_has_cancel(self):
        kb = admin_broadcast_text_keyboard()
        flat = self._flat_payloads(kb)

        self.assertIn("admin_broadcast_cancel", flat)

    def test_button_keyboard_has_required_buttons(self):
        kb = admin_broadcast_button_keyboard()
        flat = self._flat_payloads(kb)

        self.assertIn("admin_broadcast_add_button", flat)
        self.assertIn("admin_broadcast_skip_button", flat)
        self.assertIn("admin_broadcast_cancel", flat)

    def test_preview_keyboard_has_required_buttons(self):
        kb = admin_broadcast_preview_keyboard()
        flat = self._flat_payloads(kb)

        self.assertIn("admin_broadcast_confirm", flat)
        self.assertIn("admin_broadcast_edit_text", flat)
        self.assertIn("admin_broadcast_edit_image", flat)
        self.assertIn("admin_broadcast_edit_button", flat)
        self.assertIn("admin_broadcast_cancel", flat)

    def test_launch_keyboard_has_required_buttons(self):
        kb = admin_broadcast_launch_keyboard(10)
        flat = self._flat_payloads(kb)

        self.assertIn("admin_broadcast_start", flat)
        self.assertIn("admin_broadcast_cancel", flat)

    def test_running_keyboard_has_stop(self):
        kb = admin_broadcast_running_keyboard()
        flat = self._flat_payloads(kb)

        self.assertIn("admin_broadcast_stop", flat)


if __name__ == "__main__":
    unittest.main()


def _callback_event(payload: str, admin_id: int = 73412011):
    event = mock.MagicMock()
    event.callback.payload = payload
    event.from_user.user_id = admin_id
    event.chat_id = admin_id
    event.bot.send_message = mock.AsyncMock()
    event.bot.send_callback = mock.AsyncMock()
    event.message = mock.create_autospec(object, instance=True)
    event.message.answer = mock.AsyncMock()
    return event


def _message_event(text: str, attachments=None, admin_id: int = 73412011):
    event = mock.MagicMock()
    event.message.body.text = text
    event.message.body.attachments = attachments or []
    event.from_user.user_id = admin_id
    event.chat_id = admin_id
    event.bot.send_message = mock.AsyncMock()
    event.bot.send_callback = mock.AsyncMock()
    event.message.answer = mock.AsyncMock()
    return event


def build_image_attachment(token: str | None = None, url: str | None = None):
    from maxapi.types import Attachment
    payload = mock.MagicMock()
    payload.token = token
    payload.url = url

    attachment = mock.MagicMock(spec=Attachment)
    attachment.type = "image"
    attachment.payload = payload
    attachment.content_type = "image/jpeg"
    return attachment


class TestAdminBroadcastIntegration(unittest.TestCase):
    def setUp(self) -> None:
        init_admin_db()
        self.admin_id = 73412011

    def test_full_flow_without_image_and_button(self) -> None:
        create_broadcast(admin_user_id=self.admin_id, text="", format="markdown")
        state = get_broadcast(1)
        state["state"] = "broadcast_image"
        event = _callback_event("admin_broadcast_new")
        asyncio.run(_handle_broadcast_preview(event, self.admin_id, state, "broadcast_preview"))

    def test_full_flow_with_image_and_button(self) -> None:
        state = create_broadcast(admin_user_id=self.admin_id, text="", format="markdown")
        state["state"] = "broadcast_image"
        image_event = _message_event(
            "", attachments=[build_image_attachment(token="img_token_123")]
        )
        asyncio.run(_handle_broadcast_image_upload(image_event, self.admin_id, state))

        state = _get_admin_state(self.admin_id)
        self.assertEqual(json.loads(state["image_file_id"]), {"token": "img_token_123"})

        text_event = _message_event("*italic* text")
        asyncio.run(_handle_broadcast_text_input(text_event, self.admin_id, state))

        state = _get_admin_state(self.admin_id)
        self.assertEqual(state["text"], "*italic* text")

        button_event = _callback_event("admin_broadcast_add_button")
        asyncio.run(_handle_broadcast_button(button_event, self.admin_id, state, "admin_broadcast_add_button"))

        state = _get_admin_state(self.admin_id)
        self.assertEqual(state["state"], "broadcast_button_text")

        btn_text_event = _message_event("Click me")
        asyncio.run(_handle_broadcast_button_input_text(btn_text_event, self.admin_id, state))

        state = _get_admin_state(self.admin_id)
        self.assertEqual(state["button_text"], "Click me")
        self.assertEqual(state["state"], "broadcast_button_url")

        btn_url_event = _message_event("https://example.com")
        asyncio.run(_handle_broadcast_button_input(btn_url_event, self.admin_id, state))

        final_state = _get_admin_state(self.admin_id)
        self.assertEqual(final_state["button_url"], "https://example.com")
        self.assertEqual(final_state["state"], "broadcast_preview")

    def test_safety_switch_blocks_broadcast(self) -> None:
        state = create_broadcast(admin_user_id=self.admin_id, text="test")
        with mock.patch("handlers.admin.BROADCAST_LIVE_ENABLED", False):
            event = _callback_event("admin_broadcast_start")
            asyncio.run(_handle_broadcast_launch(
                event, self.admin_id, {"broadcast_id": state["id"]}, "admin_broadcast_start"
            ))

            event.message.answer.assert_called_once()
            sent_text = event.message.answer.call_args[1]["text"]
            self.assertIn("отключены", sent_text)


class TestMarkdownFormatting(unittest.TestCase):
    def setUp(self) -> None:
        init_admin_db()
        self.admin_id = 997

    def test_markdown_text_preserved_in_preview(self) -> None:
        state = create_broadcast(admin_user_id=self.admin_id, text="**bold**")
        self.assertEqual(state["text"], "**bold**")
        self.assertEqual(state["format"], "markdown")

    def test_url_preserved_in_preview(self) -> None:
        state = create_broadcast(admin_user_id=self.admin_id, text="https://example.com")
        self.assertEqual(state["text"], "https://example.com")

    def test_preview_uses_markdown_format(self) -> None:
        state = create_broadcast(admin_user_id=self.admin_id, text="test")
        event = mock.MagicMock()
        event.from_user.user_id = self.admin_id
        event.chat_id = self.admin_id
        event.message = None
        event.bot.send_message = mock.AsyncMock()
        asyncio.run(_show_broadcast_preview(event, self.admin_id, state))
        sent_kwargs = event.bot.send_message.call_args[1]
        self.assertEqual(sent_kwargs["format"], TextFormat.MARKDOWN)


class TestImageAttachment(unittest.TestCase):
    def test_token_image_payload(self) -> None:
        attachment = build_image_attachment(token="tok_123")
        payload = getattr(attachment, "payload", None)
        self.assertEqual(payload.token, "tok_123")
        self.assertIsNone(payload.url)

    def test_url_image_payload(self) -> None:
        attachment = build_image_attachment(url="https://example.com/img.jpg")
        payload = getattr(attachment, "payload", None)
        self.assertEqual(payload.url, "https://example.com/img.jpg")
        self.assertIsNone(payload.token)


class TestProductionDBIsolation(unittest.TestCase):
    def test_production_db_not_used_by_tests(self) -> None:
        assert_production_db_untouched()
