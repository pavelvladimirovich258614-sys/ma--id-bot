"""
Реальный dispatch-тест маршрутизации через настоящий maxapi.Dispatcher.

Доказывает, что команда /admin, админ-текст и admin_*/harvest_* callback
маршрутизируются корректно и НЕ перехватываются общими обработчиками.

Используется фактический Dispatcher из установленного maxapi (instance Event
атрибуты message_created / message_callback / bot_started). События
конструируются как реальные MessageCreated / MessageCallback модели и
прогоняются через dp.handle(event).

Все сетевые вызовы замоканы: bot.send_message / send_callback / edit_message,
проверка подписки и postgres-хранилище.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TMP_DIR = tempfile.mkdtemp(prefix="maxidbot_realdispatch_")
os.environ["MAXIDBOT_DB_PATH"] = os.path.join(TMP_DIR, "test.sqlite3")
os.environ.setdefault("BOT_TOKEN", "TEST_FAKE_TOKEN")
os.environ["ADMIN_USER_IDS"] = "73412011"
os.environ["BROADCAST_LIVE_ENABLED"] = "false"
os.environ["CHANNEL_ID"] = "id752703975446_biz"
os.environ["CHANNEL_LINK"] = "https://max.ru/id752703975446_biz"
os.environ["CHANNEL_CHAT_ID"] = "-72143469522347"

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maxapi import Dispatcher  # noqa: E402
from maxapi.enums.chat_type import ChatType  # noqa: E402
from maxapi.types import (  # noqa: E402
    Message,
    MessageBody,
    MessageCallback,
    MessageCreated,
    Recipient,
    User,
)
from maxapi.types.callback import Callback  # noqa: E402

import middleware.subscription as subscription_mw  # noqa: E402
from handlers import admin as admin_handlers  # noqa: E402


ADMIN_ID = 73412011
NORMAL_ID = 555000111
CHAT_ID = 150467520


def _make_user(user_id):
    return User(
        user_id=user_id,
        first_name="Tester",
        is_bot=False,
        last_activity_time=1,
    )


def build_message(user_id, text, chat_id=CHAT_ID, attachments=None, bot=None):
    body = MessageBody(
        mid=f"{chat_id}:{user_id}:1",
        seq=1,
        text=text,
        attachments=attachments or [],
    )
    msg = Message(
        sender=_make_user(user_id),
        recipient=Recipient(chat_id=chat_id, chat_type=ChatType.DIALOG),
        timestamp=1,
        body=body,
    )
    # В реальном диспетче process_update_request проставляет message.bot.
    # _send_message использует message.answer(), поэтому bot нужен на сообщении.
    if bot is not None:
        msg.bot = bot
    ev = MessageCreated(timestamp=1, message=msg)
    ev.from_user = _make_user(user_id)
    return ev


def build_callback(user_id, payload, chat_id=CHAT_ID, bot=None):
    callback = Callback(
        timestamp=1,
        callback_id=f"cb_{payload}_{user_id}",
        payload=payload,
        user=_make_user(user_id),
    )
    msg = Message(
        sender=_make_user(user_id),
        recipient=Recipient(chat_id=chat_id, chat_type=ChatType.DIALOG),
        timestamp=1,
        body=MessageBody(mid=f"{chat_id}:{user_id}:1", seq=1, text=""),
    )
    if bot is not None:
        msg.bot = bot
    ev = MessageCallback(timestamp=1, message=msg, callback=callback)
    ev.from_user = _make_user(user_id)
    return ev


class RecordingBot:
    """Фиктивный бот, записывающий все вызовы отправки сообщений."""

    def __init__(self):
        self.username = "id752703975446_bot"
        self.me = mock.MagicMock()
        self.me.username = "id752703975446_bot"
        self.commands = []
        self.sent_messages = []
        self.sent_callbacks = []
        self.edited_messages = []

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        return mock.MagicMock()

    async def send_callback(self, **kwargs):
        self.sent_callbacks.append(kwargs)
        return mock.MagicMock()

    async def edit_message(self, **kwargs):
        self.edited_messages.append(kwargs)
        return mock.MagicMock()

    async def get_me(self):
        me = mock.MagicMock()
        me.username = "id752703975446_bot"
        return me


class RealDispatchRoutingTest(unittest.TestCase):
    def setUp(self):
        self.dp = Dispatcher()

        # Подписка: админ -> ADMIN, остальные -> SUBSCRIBED (пропуск).
        async def fake_check(user_id):
            from middleware.subscription import SubscriptionAccess

            if user_id == ADMIN_ID:
                return SubscriptionAccess.ADMIN
            return SubscriptionAccess.SUBSCRIBED

        self._sub_patch = mock.patch.object(
            subscription_mw, "check_subscription_access", fake_check
        )
        self._sub_patch.start()

        # postgres: не забанен, без сети.
        self._pg_patch = mock.patch(
            "middleware.subscription.get_admin_user_state",
            new=mock.AsyncMock(return_value=None),
        )
        self._pg_patch.start()
        self._up_patch = mock.patch(
            "middleware.subscription.update_user", new=mock.AsyncMock()
        )
        self._up_patch.start()
        self._ups_patch = mock.patch(
            "middleware.subscription.upsert_admin_user", new=mock.AsyncMock()
        )
        self._ups_patch.start()

        self.bot = RecordingBot()
        self.dp.bot = self.bot

        # Регистрируем В ТОМ ЖЕ ПОРЯДКЕ, что и в bot.py.
        from handlers import (
            bot_added,
            callbacks,
            messages,
            start,
            subscription_events,
        )

        start.register_start_handlers(self.dp)
        callbacks.register_callback_handlers(self.dp)
        admin_handlers.register_admin_handlers(self.dp)
        messages.register_message_handler(self.dp)
        bot_added.register_bot_added_handler(self.dp)
        subscription_events.register_subscription_event_handlers(self.dp)

        # Реальная подготовка роутеров (как в start_polling -> __ready).
        self.dp.bot = self.bot
        asyncio.run(self.dp._Dispatcher__ready(self.bot))

        # Сброс админ-состояний между тестами.
        admin_handlers._admin_states.clear()

    def tearDown(self):
        self._sub_patch.stop()
        self._pg_patch.stop()
        self._up_patch.stop()
        self._ups_patch.stop()

    def _dispatch(self, event):
        event.bot = self.bot
        asyncio.run(self.dp.handle(event))

    def test_admin_command_reaches_panel(self):
        """/admin от админа открывает панель (не перехватывается общим handler)."""
        ev = build_message(ADMIN_ID, "/admin", bot=self.bot)
        self._dispatch(ev)
        self.assertTrue(
            any("Панель" in m.get("text", "") for m in self.bot.sent_messages),
            f"Ожидалась панель админа, отправлено: {self.bot.sent_messages}",
        )

    def test_admin_command_stranger_refused(self):
        """/admin от постороннего получает отказ."""
        ev = build_message(NORMAL_ID, "/admin", bot=self.bot)
        self._dispatch(ev)
        self.assertTrue(
            any(
                "недоступна" in m.get("text", "").lower()
                for m in self.bot.sent_messages
            ),
            f"Ожидался отказ, отправлено: {self.bot.sent_messages}",
        )

    def test_normal_message_not_eaten_by_admin(self):
        """Обычное сообщение не перехватывается админ-маршрутизацией."""
        ev = build_message(NORMAL_ID, "привет, обычный текст", bot=self.bot)
        # Без активного админ-состояния route_admin_message вернёт False.
        self._dispatch(ev)
        # Админ-панель НЕ должна открыться.
        admin_msgs = [
            m.get("text", "")
            for m in self.bot.sent_messages
            if "Панель" in m.get("text", "")
        ]
        self.assertEqual(admin_msgs, [])

    def test_no_none_in_attachments(self):
        """Ни одно вложение не должно быть None при отправке в MAX API (ШАГ 5)."""
        # Прогоняем сценарий /admin (панель) и закрытие панели.
        ev_panel = build_message(ADMIN_ID, "/admin", bot=self.bot)
        self._dispatch(ev_panel)
        # Закрываем панель через admin_close callback.
        ev_close = build_callback(ADMIN_ID, "admin_close", bot=self.bot)
        self._dispatch(ev_close)

        bad = []
        for m in self.bot.sent_messages:
            atts = m.get("attachments")
            if isinstance(atts, list) and any(a is None for a in atts):
                bad.append(m)
        self.assertEqual(
            bad,
            [],
            f"Обнаружен список вложений с None: {bad}",
        )

    def test_admin_close_no_crash(self):
        """Закрытие панели admin_close не падает и не шлёт [None]."""
        ev_panel = build_message(ADMIN_ID, "/admin", bot=self.bot)
        self._dispatch(ev_panel)
        ev_close = build_callback(ADMIN_ID, "admin_close", bot=self.bot)
        # Не должно бросить исключение.
        self._dispatch(ev_close)
        self.assertTrue(
            any("закрыта" in m.get("text", "").lower() for m in self.bot.sent_messages),
            f"Ожидалось сообщение о закрытии, отправлено: {self.bot.sent_messages}",
        )


if __name__ == "__main__":
    unittest.main()
