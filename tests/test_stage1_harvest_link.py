from __future__ import annotations

import asyncio
import importlib
import os
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))



class TestNormalizeMaxLink(unittest.TestCase):
    def setUp(self):
        import handlers.messages
        importlib.reload(handlers.messages)
        self._normalize_max_link = handlers.messages._normalize_max_link

    def test_full_urls(self):
        cases = [
            ("https://max.ru/id752703975446_biz", "id752703975446_biz"),
            ("https://www.max.ru/id752703975446_biz", "id752703975446_biz"),
            ("https://web.max.ru/id752703975446_biz", "id752703975446_biz"),
            ("https://max.ru/name?foo=bar", "name"),
            ("https://max.ru/name/#fragment", "name"),
            ("https://max.ru/name/", "name"),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(self._normalize_max_link(source), expected)

    def test_short_forms(self):
        cases = [
            ("max.ru/id752703975446_biz", "id752703975446_biz"),
            ("www.max.ru/id752703975446_biz", "id752703975446_biz"),
            ("web.max.ru/id752703975446_biz", "id752703975446_biz"),
            ("@id752703975446_biz", "id752703975446_biz"),
            ("id752703975446_biz", "id752703975446_biz"),
            ("name", "name"),
            ("@name", "name"),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(self._normalize_max_link(source), expected)

    def test_invalid_and_unsafe(self):
        cases = [
            "",
            "   ",
            "https://other.ru/name",
            "https://max.ru/",
            "https://max.ru.evil.com/name",
            "evilmax.ru/name",
            "https://evil.com/max.ru/name",
            "javascript:alert(1)",
            "https://max.ru/",
            "https://max.ru//",
        ]
        for source in cases:
            with self.subTest(source=source):
                self.assertIsNone(self._normalize_max_link(source))


class TestHarvestLinkConfigFallback(unittest.TestCase):
    def setUp(self):
        import config
        import handlers.messages
        self._config = config
        self._hm = handlers.messages

    def _apply_env(self):
        importlib.reload(self._config)
        importlib.reload(self._hm)

    def test_config_channel_match_by_channel_id(self):
        os.environ["CHANNEL_ID"] = "id752703975446_biz"
        os.environ["CHANNEL_LINK"] = "https://max.ru/id752703975446_biz"
        os.environ["CHANNEL_CHAT_ID"] = "-72143469522347"
        self._apply_env()

        from handlers.messages import _handle_harvest_link

        fake_bot = SimpleNamespace(get_chat_by_link=AsyncMock())
        event = SimpleNamespace(
            bot=fake_bot,
            from_user=SimpleNamespace(user_id=1),
            message=SimpleNamespace(
                recipient=SimpleNamespace(chat_id=2),
                delete=AsyncMock(),
            ),
            chat_id=2,
        )
        message = SimpleNamespace(answer=AsyncMock())

        with patch("handlers.messages.clear_harvest_state") as mock_clear, \
             patch("handlers.messages._schedule_discovered_entity_save") as mock_save, \
             patch("handlers.messages._delete_original_message") as mock_delete, \
             patch("handlers.messages.id_harvest_keyboard", return_value="keyboard"):
            result = asyncio.run(
                _handle_harvest_link(event, message, "https://max.ru/id752703975446_biz")
            )

        self.assertTrue(result)
        fake_bot.get_chat_by_link.assert_not_called()
        mock_clear.assert_called_once_with(1)
        mock_save.assert_called_once()

    def test_config_channel_match_by_link(self):
        os.environ["CHANNEL_ID"] = "id752703975446_biz"
        os.environ["CHANNEL_LINK"] = "https://max.ru/id752703975446_biz"
        os.environ["CHANNEL_CHAT_ID"] = "-72143469522347"
        self._apply_env()

        from handlers.messages import _handle_harvest_link

        fake_bot = SimpleNamespace(get_chat_by_link=AsyncMock())
        event = SimpleNamespace(
            bot=fake_bot,
            from_user=SimpleNamespace(user_id=1),
            message=SimpleNamespace(
                recipient=SimpleNamespace(chat_id=2),
                delete=AsyncMock(),
            ),
            chat_id=2,
        )
        message = SimpleNamespace(answer=AsyncMock())

        with patch("handlers.messages.clear_harvest_state") as mock_clear, \
             patch("handlers.messages._schedule_discovered_entity_save") as mock_save, \
             patch("handlers.messages._delete_original_message") as mock_delete, \
             patch("handlers.messages.id_harvest_keyboard", return_value="keyboard"):
            result = asyncio.run(
                _handle_harvest_link(event, message, "id752703975446_biz")
            )

        self.assertTrue(result)
        fake_bot.get_chat_by_link.assert_not_called()
        mock_clear.assert_called_once_with(1)
        mock_save.assert_called_once()

    def test_config_channel_match_by_channel_id_with_at(self):
        os.environ["CHANNEL_ID"] = "@id752703975446_biz"
        os.environ["CHANNEL_LINK"] = "https://max.ru/id752703975446_biz"
        os.environ["CHANNEL_CHAT_ID"] = "-72143469522347"
        self._apply_env()

        from handlers.messages import _handle_harvest_link

        fake_bot = SimpleNamespace(get_chat_by_link=AsyncMock())
        event = SimpleNamespace(
            bot=fake_bot,
            from_user=SimpleNamespace(user_id=1),
            message=SimpleNamespace(
                recipient=SimpleNamespace(chat_id=2),
                delete=AsyncMock(),
            ),
            chat_id=2,
        )
        message = SimpleNamespace(answer=AsyncMock())

        with patch("handlers.messages.clear_harvest_state") as mock_clear, \
             patch("handlers.messages._schedule_discovered_entity_save") as mock_save, \
             patch("handlers.messages._delete_original_message") as mock_delete, \
             patch("handlers.messages.id_harvest_keyboard", return_value="keyboard"):
            result = asyncio.run(
                _handle_harvest_link(event, message, "id752703975446_biz")
            )

        self.assertTrue(result)
        fake_bot.get_chat_by_link.assert_not_called()
        mock_clear.assert_called_once_with(1)
        mock_save.assert_called_once()

    def test_api_call_when_config_is_empty(self):
        os.environ["CHANNEL_ID"] = ""
        os.environ["CHANNEL_LINK"] = ""
        os.environ["CHANNEL_CHAT_ID"] = ""
        self._apply_env()

        from handlers.messages import _handle_harvest_link

        chat = SimpleNamespace(chat_id=100, title="Chat", type="chat", link="https://max.ru/chat")
        fake_bot = SimpleNamespace(get_chat_by_link=AsyncMock(return_value=chat))
        event = SimpleNamespace(
            bot=fake_bot,
            from_user=SimpleNamespace(user_id=1),
            message=SimpleNamespace(
                recipient=SimpleNamespace(chat_id=2),
                delete=AsyncMock(),
            ),
            chat_id=2,
        )
        message = SimpleNamespace(answer=AsyncMock())

        with patch("handlers.messages.clear_harvest_state") as mock_clear, \
             patch("handlers.messages._schedule_discovered_entity_save") as mock_save, \
             patch("handlers.messages._delete_original_message") as mock_delete, \
             patch("handlers.messages.id_harvest_keyboard", return_value="keyboard"):
            result = asyncio.run(
                _handle_harvest_link(event, message, "https://max.ru/id752703975446_biz")
            )

        self.assertTrue(result)
        fake_bot.get_chat_by_link.assert_called_once_with(link="id752703975446_biz")
        mock_clear.assert_called_once_with(1)
        mock_save.assert_called_once()

    def test_api_not_called_when_channel_chat_id_empty(self):
        os.environ["CHANNEL_ID"] = "id752703975446_biz"
        os.environ["CHANNEL_LINK"] = "https://max.ru/id752703975446_biz"
        os.environ["CHANNEL_CHAT_ID"] = ""
        self._apply_env()

        from handlers.messages import _handle_harvest_link

        chat = SimpleNamespace(chat_id=100, title="Chat", type="chat", link="https://max.ru/chat")
        fake_bot = SimpleNamespace(get_chat_by_link=AsyncMock(return_value=chat))
        event = SimpleNamespace(
            bot=fake_bot,
            from_user=SimpleNamespace(user_id=1),
            message=SimpleNamespace(
                recipient=SimpleNamespace(chat_id=2),
                delete=AsyncMock(),
            ),
            chat_id=2,
        )
        message = SimpleNamespace(answer=AsyncMock())

        with patch("handlers.messages.clear_harvest_state") as mock_clear, \
             patch("handlers.messages._schedule_discovered_entity_save") as mock_save, \
             patch("handlers.messages._delete_original_message") as mock_delete, \
             patch("handlers.messages.id_harvest_keyboard", return_value="keyboard"):
            result = asyncio.run(
                _handle_harvest_link(event, message, "https://max.ru/id752703975446_biz")
            )

        self.assertTrue(result)
        fake_bot.get_chat_by_link.assert_called_once_with(link="id752703975446_biz")
        mock_clear.assert_called_once_with(1)
        mock_save.assert_called_once()

    def test_api_not_found_shows_fallback_keyboard(self):
        os.environ["CHANNEL_ID"] = ""
        os.environ["CHANNEL_LINK"] = ""
        os.environ["CHANNEL_CHAT_ID"] = ""
        self._apply_env()

        from handlers.messages import _handle_harvest_link

        fake_bot = SimpleNamespace(get_chat_by_link=AsyncMock(side_effect=Exception("chat.not.found")))
        event = SimpleNamespace(
            bot=fake_bot,
            from_user=SimpleNamespace(user_id=1),
            message=SimpleNamespace(
                recipient=SimpleNamespace(chat_id=2),
                delete=AsyncMock(),
            ),
            chat_id=2,
        )
        message = SimpleNamespace(answer=AsyncMock())

        with patch("handlers.messages.clear_harvest_state") as mock_clear, \
             patch("handlers.messages._schedule_discovered_entity_save") as mock_save, \
             patch("handlers.messages._delete_original_message") as mock_delete, \
             patch("handlers.messages.id_harvest_keyboard", return_value="keyboard"):
            result = asyncio.run(
                _handle_harvest_link(event, message, "https://max.ru/id752703975446_biz")
            )

        self.assertTrue(result)
        fake_bot.get_chat_by_link.assert_called_once_with(link="id752703975446_biz")
        message.answer.assert_called_once()
        args, kwargs = message.answer.call_args
        self.assertIn("attachments", kwargs)
        self.assertEqual(kwargs["attachments"], ["keyboard"])


if __name__ == "__main__":
    unittest.main()
