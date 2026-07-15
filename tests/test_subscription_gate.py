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

from config import ADMIN_USER_IDS, CHANNEL_CHAT_ID, CHANNEL_LINK
import httpx
from middleware.subscription import (
    SubscriptionAccess,
    SubscriptionCheckError,
    check_subscription_access,
    require_subscription,
)


class SubscriptionGateTests(unittest.TestCase):
    def test_admin_user_ids_parsed(self):
        self.assertIsInstance(ADMIN_USER_IDS, set)
        self.assertIn(73412011, ADMIN_USER_IDS)

    def _fake_event(self, user_id, payload=None, text=None):
        user = types.SimpleNamespace(user_id=user_id)
        event_kwargs = {
            "user_id": user_id,
            "from_user": user,
            "chat_id": 123,
            "bot": types.SimpleNamespace(
                send_message=lambda **kwargs: asyncio.sleep(0),
                send_callback=lambda **kwargs: asyncio.sleep(0),
            ),
            "message": types.SimpleNamespace(
                recipient=types.SimpleNamespace(chat_id=123),
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

    def _async_result(self, value):
        async def _coro(*args, **kwargs):
            return value
        return _coro

    def _fake_get_user(self, user_id):
        return {}

    def test_admin_bypass_without_http(self):
        with mock.patch("middleware.subscription.get_user", self._fake_get_user), \
             mock.patch("middleware.subscription.check_subscription_access", self._async_result(SubscriptionAccess.ADMIN)), \
             mock.patch("middleware.subscription.update_user"), \
             mock.patch("middleware.subscription.upsert_admin_user"):
            called = []

            async def fake_handler(event, *args, **kwargs):
                called.append((event, args, kwargs))
                return "admin_ok"

            wrapped = require_subscription(fake_handler)
            event = self._fake_event(73412011, payload="get_user_id")
            result = asyncio.run(wrapped(event))
            self.assertEqual(result, "admin_ok")
            self.assertEqual(called, [(event, (), {})])

    def test_subscribed_user_has_access(self):
        with mock.patch("middleware.subscription.get_user", self._fake_get_user), \
             mock.patch("middleware.subscription.check_subscription_access", self._async_result(SubscriptionAccess.SUBSCRIBED)), \
             mock.patch("middleware.subscription.update_user") as update_user, \
             mock.patch("middleware.subscription.upsert_admin_user"):
            called = []

            async def fake_handler(event, *args, **kwargs):
                called.append(event)
                return "ok"

            wrapped = require_subscription(fake_handler)
            event = self._fake_event(222, payload="get_user_id")
            result = asyncio.run(wrapped(event))
            self.assertEqual(result, "ok")
            self.assertEqual(called, [event])
            update_user.assert_called_once()
            _, kwargs = update_user.call_args
            self.assertEqual(kwargs["is_subscribed"], 1)

    def test_unsubscribed_user_gets_gate_message(self):
        with mock.patch("middleware.subscription.get_user", self._fake_get_user), \
             mock.patch("middleware.subscription.check_subscription_access", self._async_result(SubscriptionAccess.NOT_SUBSCRIBED)), \
             mock.patch("middleware.subscription.update_user") as update_user, \
             mock.patch("middleware.subscription.upsert_admin_user"), \
             mock.patch("middleware.subscription._send_subscription_message") as send_sub, \
             mock.patch("middleware.subscription._answer_callback_if_needed") as answer_cb:
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = require_subscription(fake_handler)
                event = self._fake_event(333, payload="get_user_id")
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                send_sub.assert_called_once_with(event, retry=False)
                answer_cb.assert_called_once_with(event)
                update_user.assert_called_once()
                _, kwargs = update_user.call_args
                self.assertEqual(kwargs["is_subscribed"], 0)

    def _assert_unavailable(self, status):
        with mock.patch("middleware.subscription.get_user", self._fake_get_user), \
             mock.patch("middleware.subscription.update_user") as update_user, \
             mock.patch("middleware.subscription.upsert_admin_user"), \
             mock.patch("middleware.subscription._send_unavailable_message") as send_unavail, \
             mock.patch("middleware.subscription._answer_callback_if_needed") as answer_cb:
            async def fake_check(user_id):
                return status

            with mock.patch("middleware.subscription.check_subscription_access", fake_check):
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = require_subscription(fake_handler)
                event = self._fake_event(444, payload="get_user_id")
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                send_unavail.assert_called_once_with(event)
                answer_cb.assert_called_once_with(event)
                update_user.assert_not_called()

    def test_http_401_returns_unavailable(self):
        self._assert_unavailable(SubscriptionAccess.UNAVAILABLE)

    def test_http_403_returns_unavailable(self):
        self._assert_unavailable(SubscriptionAccess.UNAVAILABLE)

    def test_http_404_returns_unavailable(self):
        self._assert_unavailable(SubscriptionAccess.UNAVAILABLE)

    def test_http_429_returns_unavailable(self):
        self._assert_unavailable(SubscriptionAccess.UNAVAILABLE)

    def test_http_500_returns_unavailable(self):
        self._assert_unavailable(SubscriptionAccess.UNAVAILABLE)

    def test_timeout_returns_unavailable(self):
        self._assert_unavailable(SubscriptionCheckError("timeout"))

    def test_network_exception_returns_unavailable(self):
        self._assert_unavailable(SubscriptionCheckError("network"))

    def test_invalid_json_returns_unavailable(self):
        self._assert_unavailable(SubscriptionCheckError("invalid json"))

    def test_retry_callback_after_subscribe_opens_menu(self):
        with mock.patch("middleware.subscription.get_user", self._fake_get_user), \
             mock.patch("middleware.subscription.check_subscription_access", self._async_result(SubscriptionAccess.SUBSCRIBED)), \
             mock.patch("middleware.subscription.update_user"), \
             mock.patch("middleware.subscription.upsert_admin_user"):
            called = []

            async def fake_handler(event, *args, **kwargs):
                called.append(event)
                return "main_menu"

            wrapped = require_subscription(fake_handler)
            event = self._fake_event(445, payload="subscription_retry")
            result = asyncio.run(wrapped(event))
            self.assertEqual(result, "main_menu")
            self.assertEqual(called, [event])

    def test_positive_db_status_does_not_grant_access(self):
        user = {
            "user_id": 555,
            "usage_count": 1,
            "is_subscribed": 1,
            "last_check": "2099-01-01T00:00:00",
            "subscription_source": "api",
        }

        async def fake_get_user(user_id):
            return user

        with mock.patch("middleware.subscription.get_user", fake_get_user), \
             mock.patch("middleware.subscription.check_subscription_access", self._async_result(SubscriptionAccess.NOT_SUBSCRIBED)), \
             mock.patch("middleware.subscription.update_user") as update_user, \
             mock.patch("middleware.subscription.upsert_admin_user"), \
             mock.patch("middleware.subscription._send_subscription_message") as send_sub:
            async def fake_handler(event, *args, **kwargs):
                return "protected"

            wrapped = require_subscription(fake_handler)
            event = self._fake_event(555, payload="get_user_id")
            result = asyncio.run(wrapped(event))
            self.assertIsNone(result)
            send_sub.assert_called_once_with(event, retry=False)
            update_user.assert_called_once()
            _, kwargs = update_user.call_args
            self.assertEqual(kwargs["is_subscribed"], 0)

    def test_harvest_payloads_are_protected(self):
        for payload in [
            "harvest_menu",
            "harvest_bot_id",
            "harvest_by_link",
            "harvest_by_message",
            "harvest_back",
        ]:
            with mock.patch("middleware.subscription.get_user", self._fake_get_user), \
                 mock.patch("middleware.subscription.check_subscription_access", self._async_result(SubscriptionAccess.NOT_SUBSCRIBED)), \
                 mock.patch("middleware.subscription.update_user"), \
                 mock.patch("middleware.subscription.upsert_admin_user"), \
                 mock.patch("middleware.subscription._send_subscription_message") as send_sub:
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = require_subscription(fake_handler)
                event = self._fake_event(666, payload=payload)
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                send_sub.assert_called_once_with(event, retry=False)

    def test_bot_started_blocks_unsubscribed(self):
        event = types.SimpleNamespace(
            from_user=types.SimpleNamespace(user_id=777),
            bot=types.SimpleNamespace(
                send_message=lambda **kwargs: asyncio.sleep(0),
                send_callback=lambda **kwargs: asyncio.sleep(0),
            ),
            chat_id=123,
            message=None,
            callback=None,
        )
        with mock.patch("middleware.subscription.get_user", self._fake_get_user), \
             mock.patch("middleware.subscription.check_subscription_access", self._async_result(SubscriptionAccess.NOT_SUBSCRIBED)), \
             mock.patch("middleware.subscription.update_user"), \
             mock.patch("middleware.subscription.upsert_admin_user"), \
             mock.patch("middleware.subscription._send_subscription_message") as send_sub:
            async def fake_handler(event, *args, **kwargs):
                return "protected"

            wrapped = require_subscription(fake_handler)
            result = asyncio.run(wrapped(event))
            self.assertIsNone(result)
            send_sub.assert_called_once_with(event, retry=False)

    def test_start_command_blocks_unsubscribed(self):
        event = self._fake_event(888, text="/start")
        with mock.patch("middleware.subscription.get_user", self._fake_get_user), \
             mock.patch("middleware.subscription.check_subscription_access", self._async_result(SubscriptionAccess.NOT_SUBSCRIBED)), \
             mock.patch("middleware.subscription.update_user"), \
             mock.patch("middleware.subscription.upsert_admin_user"), \
             mock.patch("middleware.subscription._send_subscription_message") as send_sub:
            async def fake_handler(event, *args, **kwargs):
                return "protected"

            wrapped = require_subscription(fake_handler)
            result = asyncio.run(wrapped(event))
            self.assertIsNone(result)
            send_sub.assert_called_once_with(event, retry=False)

    def test_help_command_blocks_unsubscribed(self):
        event = self._fake_event(889, text="/help")
        with mock.patch("middleware.subscription.get_user", self._fake_get_user), \
             mock.patch("middleware.subscription.check_subscription_access", self._async_result(SubscriptionAccess.NOT_SUBSCRIBED)), \
             mock.patch("middleware.subscription.update_user"), \
             mock.patch("middleware.subscription.upsert_admin_user"), \
             mock.patch("middleware.subscription._send_subscription_message") as send_sub:
            async def fake_handler(event, *args, **kwargs):
                return "protected"

            wrapped = require_subscription(fake_handler)
            result = asyncio.run(wrapped(event))
            self.assertIsNone(result)
            send_sub.assert_called_once_with(event, retry=False)

    def test_ordinary_callback_after_refusal_not_executed(self):
        with mock.patch("middleware.subscription.get_user", self._fake_get_user), \
             mock.patch("middleware.subscription.check_subscription_access", self._async_result(SubscriptionAccess.NOT_SUBSCRIBED)), \
             mock.patch("middleware.subscription.update_user"), \
             mock.patch("middleware.subscription.upsert_admin_user"), \
             mock.patch("middleware.subscription._send_subscription_message") as send_sub:
            called = []

            async def fake_handler(event, *args, **kwargs):
                called.append(event)
                return "protected"

            wrapped = require_subscription(fake_handler)
            event = self._fake_event(999, payload="get_chat_id")
            result = asyncio.run(wrapped(event))
            self.assertIsNone(result)
            self.assertEqual(called, [])
            send_sub.assert_called_once_with(event, retry=False)

    def test_harvest_menu_after_refusal_not_executed(self):
        with mock.patch("middleware.subscription.get_user", self._fake_get_user), \
             mock.patch("middleware.subscription.check_subscription_access", self._async_result(SubscriptionAccess.NOT_SUBSCRIBED)), \
             mock.patch("middleware.subscription.update_user"), \
             mock.patch("middleware.subscription.upsert_admin_user"), \
             mock.patch("middleware.subscription._send_subscription_message") as send_sub:
            called = []

            async def fake_handler(event, *args, **kwargs):
                called.append(event)
                return "protected"

            wrapped = require_subscription(fake_handler)
            event = self._fake_event(1001, payload="harvest_menu")
            result = asyncio.run(wrapped(event))
            self.assertIsNone(result)
            self.assertEqual(called, [])
            send_sub.assert_called_once_with(event, retry=False)

    def test_harvest_by_link_after_refusal_not_executed(self):
        with mock.patch("middleware.subscription.get_user", self._fake_get_user), \
             mock.patch("middleware.subscription.check_subscription_access", self._async_result(SubscriptionAccess.NOT_SUBSCRIBED)), \
             mock.patch("middleware.subscription.update_user"), \
             mock.patch("middleware.subscription.upsert_admin_user"), \
             mock.patch("middleware.subscription._send_subscription_message") as send_sub:
            called = []

            async def fake_handler(event, *args, **kwargs):
                called.append(event)
                return "protected"

            wrapped = require_subscription(fake_handler)
            event = self._fake_event(1002, payload="harvest_by_link")
            result = asyncio.run(wrapped(event))
            self.assertIsNone(result)
            self.assertEqual(called, [])
            send_sub.assert_called_once_with(event, retry=False)

    def test_check_subscription_access_admin_without_http(self):
        result = asyncio.run(check_subscription_access(73412011))
        self.assertEqual(result, SubscriptionAccess.ADMIN)

    def test_check_subscription_access_subscribed(self):
        async def fake_members(*args, **kwargs):
            return {"members": [{"user_id": 555}]}

        async def fake_get(*args, **kwargs):
            response = mock.Mock()
            response.status_code = 200
            response.json = lambda: {"members": [{"user_id": 555}]}
            return response

        with mock.patch("httpx.AsyncClient.get", fake_get):
            result = asyncio.run(check_subscription_access(555))
            self.assertEqual(result, SubscriptionAccess.SUBSCRIBED)

    def test_check_subscription_access_not_subscribed(self):
        async def fake_get(*args, **kwargs):
            response = mock.Mock()
            response.status_code = 200
            response.json = lambda: {"members": []}
            return response

        with mock.patch("httpx.AsyncClient.get", fake_get):
            result = asyncio.run(check_subscription_access(556))
            self.assertEqual(result, SubscriptionAccess.NOT_SUBSCRIBED)

    def test_check_subscription_access_unavailable_on_timeout(self):
        async def fake_get(*args, **kwargs):
            raise httpx.TimeoutException("timeout")

        with mock.patch("httpx.AsyncClient.get", fake_get):
            result = asyncio.run(check_subscription_access(557))
            self.assertEqual(result, SubscriptionAccess.UNAVAILABLE)


    def test_retry_subscribed_returns_main_menu(self):
        with open("/opt/ma--id-bot/handlers/callbacks.py", "r", encoding="utf-8") as f:
            source = f.read()

        retry_branch = "elif payload == \"subscription_retry\":"
        branch_index = source.find(retry_branch)
        self.assertNotEqual(branch_index, -1, "subscription_retry branch not found")

        branch_end = source.find("else:", branch_index)
        branch_source = source[branch_index:branch_end]

        self.assertIn("main_menu_keyboard()", branch_source)
        self.assertIn("WELCOME_TEXT", branch_source)
        self.assertNotIn("subscription_retry_keyboard", branch_source)
        self.assertNotIn("SUBSCRIPTION_TEXT", branch_source)
class ConfigTests(unittest.TestCase):
    def test_channel_link_configured(self):
        self.assertTrue(CHANNEL_LINK)

    def test_channel_chat_id_configured(self):
        self.assertEqual(CHANNEL_CHAT_ID, -72143469522347)


if __name__ == "__main__":
    unittest.main()
