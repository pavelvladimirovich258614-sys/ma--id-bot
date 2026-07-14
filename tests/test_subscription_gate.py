"""
Минимальные тесты проверки шлюза подписки.
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

from config import ADMIN_USER_IDS, CHANNEL_CHAT_ID, CHANNEL_LINK
from middleware.subscription import SubscriptionCheckError


class SubscriptionGateTests(unittest.TestCase):
    def test_admin_user_ids_parsed(self):
        self.assertIsInstance(ADMIN_USER_IDS, set)
        self.assertIn(73412011, ADMIN_USER_IDS)

    def _fake_event(self, user_id, payload=None, text=None):
        user = types.SimpleNamespace(user_id=user_id)
        callback = types.SimpleNamespace(
            user=user,
            callback_id="callback_id",
            payload=payload,
        )
        event = types.SimpleNamespace(
            user_id=user_id,
            from_user=user,
            callback=callback,
            chat_id=123,
            bot=types.SimpleNamespace(
                send_message=lambda **kwargs: asyncio.sleep(0),
                send_callback=lambda **kwargs: asyncio.sleep(0),
            ),
            message=types.SimpleNamespace(
                recipient=types.SimpleNamespace(chat_id=123),
                body=types.SimpleNamespace(
                    text=text or "",
                    attachments=[],
                ),
                link=None,
                answer=lambda **kwargs: asyncio.sleep(0),
                edit=None,
            ),
        )
        return event

    def test_admin_bypass_without_http(self):
        import middleware.subscription as subscription

        async def fake_get_user(user_id):
            return {}

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "_check_subscription", self._async_false), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            called = []

            async def fake_handler(event, *args, **kwargs):
                called.append((event, args, kwargs))
                return "admin_ok"

            wrapped = subscription.require_subscription(fake_handler)
            event = self._fake_event(73412011, payload="get_user_id")
            result = asyncio.run(wrapped(event))
            self.assertEqual(result, "admin_ok")
            self.assertTrue(called)

    def test_regular_user_first_request_not_free(self):
        import middleware.subscription as subscription

        async def fake_get_user(user_id):
            return {}

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "_check_subscription", self._async_false), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            sent = []

            async def fake_send(event, retry=False):
                sent.append((event, retry))

            with mock.patch.object(subscription, "_send_subscription_message", fake_send):
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = subscription.require_subscription(fake_handler)
                event = self._fake_event(111, payload="get_user_id", text="hello")
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                self.assertEqual(sent, [(event, False)])

    def test_subscribed_user_has_access(self):
        import middleware.subscription as subscription

        async def fake_get_user(user_id):
            return {}

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "_check_subscription", self._async_true), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            called = []

            async def fake_handler(event, *args, **kwargs):
                called.append(event)
                return "ok"

            wrapped = subscription.require_subscription(fake_handler)
            event = self._fake_event(222, payload="get_user_id")
            result = asyncio.run(wrapped(event))
            self.assertEqual(result, "ok")
            self.assertEqual(called, [event])

    def test_http_401_blocks_access(self):
        import middleware.subscription as subscription

        async def fake_get_user(user_id):
            return {}

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            sent_unavailable = []

            async def fake_unavailable(event):
                sent_unavailable.append(event)

            async def fake_check(user_id):
                raise SubscriptionCheckError("401")

            with mock.patch.object(subscription, "_send_unavailable_message", fake_unavailable), \
                 mock.patch.object(subscription, "_check_subscription", fake_check):
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = subscription.require_subscription(fake_handler)
                event = self._fake_event(333, payload="get_user_id")
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                self.assertEqual(sent_unavailable, [event])

    def test_http_403_blocks_access(self):
        import middleware.subscription as subscription

        async def fake_get_user(user_id):
            return {}

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            sent_unavailable = []

            async def fake_unavailable(event):
                sent_unavailable.append(event)

            async def fake_check(user_id):
                raise SubscriptionCheckError("403")

            with mock.patch.object(subscription, "_send_unavailable_message", fake_unavailable), \
                 mock.patch.object(subscription, "_check_subscription", fake_check):
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = subscription.require_subscription(fake_handler)
                event = self._fake_event(334, payload="get_user_id")
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                self.assertEqual(sent_unavailable, [event])

    def test_http_404_blocks_access(self):
        import middleware.subscription as subscription

        async def fake_get_user(user_id):
            return {}

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            sent_unavailable = []

            async def fake_unavailable(event):
                sent_unavailable.append(event)

            async def fake_check(user_id):
                raise SubscriptionCheckError("404")

            with mock.patch.object(subscription, "_send_unavailable_message", fake_unavailable), \
                 mock.patch.object(subscription, "_check_subscription", fake_check):
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = subscription.require_subscription(fake_handler)
                event = self._fake_event(335, payload="get_user_id")
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                self.assertEqual(sent_unavailable, [event])

    def test_http_429_blocks_access(self):
        import middleware.subscription as subscription

        async def fake_get_user(user_id):
            return {}

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            sent_unavailable = []

            async def fake_unavailable(event):
                sent_unavailable.append(event)

            async def fake_check(user_id):
                raise SubscriptionCheckError("429")

            with mock.patch.object(subscription, "_send_unavailable_message", fake_unavailable), \
                 mock.patch.object(subscription, "_check_subscription", fake_check):
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = subscription.require_subscription(fake_handler)
                event = self._fake_event(336, payload="get_user_id")
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                self.assertEqual(sent_unavailable, [event])

    def test_http_500_blocks_access(self):
        import middleware.subscription as subscription

        async def fake_get_user(user_id):
            return {}

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            sent_unavailable = []

            async def fake_unavailable(event):
                sent_unavailable.append(event)

            async def fake_check(user_id):
                raise SubscriptionCheckError("500")

            with mock.patch.object(subscription, "_send_unavailable_message", fake_unavailable), \
                 mock.patch.object(subscription, "_check_subscription", fake_check):
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = subscription.require_subscription(fake_handler)
                event = self._fake_event(337, payload="get_user_id")
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                self.assertEqual(sent_unavailable, [event])

    def test_timeout_blocks_access(self):
        import middleware.subscription as subscription

        async def fake_get_user(user_id):
            return {}

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            sent_unavailable = []

            async def fake_unavailable(event):
                sent_unavailable.append(event)

            async def fake_check(user_id):
                raise SubscriptionCheckError("timeout")

            with mock.patch.object(subscription, "_send_unavailable_message", fake_unavailable), \
                 mock.patch.object(subscription, "_check_subscription", fake_check):
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = subscription.require_subscription(fake_handler)
                event = self._fake_event(338, payload="get_user_id")
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                self.assertEqual(sent_unavailable, [event])

    def test_network_exception_blocks_access(self):
        import middleware.subscription as subscription

        async def fake_get_user(user_id):
            return {}

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            sent_unavailable = []

            async def fake_unavailable(event):
                sent_unavailable.append(event)

            async def fake_check(user_id):
                raise SubscriptionCheckError("network")

            with mock.patch.object(subscription, "_send_unavailable_message", fake_unavailable), \
                 mock.patch.object(subscription, "_check_subscription", fake_check):
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = subscription.require_subscription(fake_handler)
                event = self._fake_event(339, payload="get_user_id")
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                self.assertEqual(sent_unavailable, [event])

    def test_invalid_json_blocks_access(self):
        import middleware.subscription as subscription

        async def fake_get_user(user_id):
            return {}

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            sent_unavailable = []

            async def fake_unavailable(event):
                sent_unavailable.append(event)

            async def fake_check(user_id):
                raise SubscriptionCheckError("invalid json")

            with mock.patch.object(subscription, "_send_unavailable_message", fake_unavailable), \
                 mock.patch.object(subscription, "_check_subscription", fake_check):
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = subscription.require_subscription(fake_handler)
                event = self._fake_event(340, payload="get_user_id")
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                self.assertEqual(sent_unavailable, [event])

    def test_retry_callback_skips_negative_cache(self):
        import middleware.subscription as subscription

        user = {
            "is_subscribed": 0,
            "last_check": "2099-01-01T00:00:00",
            "subscription_source": "api",
        }
        async def fake_get_user(user_id):
            return user

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "_check_subscription", self._async_true), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            sent = []

            async def fake_send(event, retry=False):
                sent.append((event, retry))

            with mock.patch.object(subscription, "_send_subscription_message", fake_send):
                called = []

                async def fake_handler(event, *args, **kwargs):
                    called.append(event)
                    return "ok"

                wrapped = subscription.require_subscription(fake_handler)
                event = self._fake_event(444, payload="subscription_retry")
                result = asyncio.run(wrapped(event))
                self.assertEqual(result, "ok")
                self.assertEqual(called, [event])

    def test_retry_callback_after_success_opens_main_menu(self):
        import middleware.subscription as subscription

        user = {
            "is_subscribed": 1,
            "last_check": "2099-01-01T00:00:00",
            "subscription_source": "api",
        }
        async def fake_get_user(user_id):
            return user

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "_check_subscription", self._async_true):
            called = []

            async def fake_handler(event, *args, **kwargs):
                called.append(event)
                return "main_menu"

            wrapped = subscription.require_subscription(fake_handler)
            event = self._fake_event(445, payload="subscription_retry")
            result = asyncio.run(wrapped(event))
            self.assertEqual(result, "main_menu")
            self.assertEqual(called, [event])

    def test_non_subscribed_user_gets_two_buttons(self):
        import middleware.subscription as subscription
        import keyboards.subscription as keyboards

        async def fake_get_user(user_id):
            return {}

        with mock.patch.object(subscription, "get_user", fake_get_user), \
             mock.patch.object(subscription, "_check_subscription", self._async_false), \
             mock.patch.object(subscription, "update_user"), \
             mock.patch.object(subscription, "upsert_admin_user"):
            sent = []

            async def fake_send(event, retry=False):
                sent.append((event, retry))

            with mock.patch.object(subscription, "_send_subscription_message", fake_send):
                async def fake_handler(event, *args, **kwargs):
                    return "protected"

                wrapped = subscription.require_subscription(fake_handler)
                event = self._fake_event(555, payload="get_user_id")
                result = asyncio.run(wrapped(event))
                self.assertIsNone(result)
                self.assertEqual(sent, [(event, False)])
                keyboard = keyboards.subscription_keyboard()
                self.assertIsNotNone(keyboard)

    def test_response_body_not_logged(self):
        import middleware.subscription as subscription

        logged = []

        class FakeLogHandler(logging.Handler):
            def emit(self, record):
                logged.append(self.format(record))

        async def fake_check(user_id):
            subscription.logger.info("Checking subscription: user_id=%s", user_id)
            return True

        with mock.patch.object(subscription, "_check_subscription", fake_check):
            handler = FakeLogHandler()
            handler.setLevel(logging.INFO)
            subscription.logger.addHandler(handler)
            subscription.logger.setLevel(logging.INFO)

            try:
                result = asyncio.run(subscription._check_subscription(999))
                self.assertTrue(result)
            finally:
                subscription.logger.removeHandler(handler)

        self.assertTrue(any("Checking subscription" in message for message in logged))
        self.assertTrue(all("secret" not in message for message in logged))

    @staticmethod
    def _async_true(user_id):
        async def _coro():
            return True
        return _coro()

    @staticmethod
    def _async_false(user_id):
        async def _coro():
            return False
        return _coro()


class ConfigTests(unittest.TestCase):
    def test_channel_link_configured(self):
        self.assertTrue(CHANNEL_LINK)

    def test_channel_chat_id_configured(self):
        self.assertEqual(CHANNEL_CHAT_ID, -72143469522347)


if __name__ == "__main__":
    unittest.main()
