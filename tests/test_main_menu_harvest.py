"""Тесты главного меню: кнопка «Разведка ID» и возврат из разведки."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

TMP_DIR = tempfile.mkdtemp(prefix="maxidbot_menu_tests_")
TEST_DB_PATH = os.path.join(TMP_DIR, "test.sqlite3")
os.environ["MAXIDBOT_DB_PATH"] = TEST_DB_PATH
os.environ.setdefault("BOT_TOKEN", "TEST_FAKE_TOKEN")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from keyboards.main_menu import main_menu_keyboard, id_harvest_keyboard


def _button_texts(kb):
    """Извлекает (text, payload) из markup, возвращаемого as_markup()."""
    out = []
    for row in kb.payload.buttons:
        for btn in row:
            out.append((btn.text, btn.payload))
    return out


class MainMenuHarvestButtonTests(unittest.TestCase):
    def test_main_menu_contains_razvedka_id(self):
        kb = main_menu_keyboard()
        texts = _button_texts(kb)
        found = [t for t in texts if t[1] == "harvest_menu"]
        self.assertTrue(found, "Кнопка harvest_menu отсутствует в главном меню")
        text, _ = found[0]
        self.assertIn("Разведка", text)

    def test_main_menu_has_all_core_buttons(self):
        kb = main_menu_keyboard()
        payloads = {p for _, p in _button_texts(kb)}
        for expected in ("get_chat_id", "get_channel_id", "get_user_id",
                         "get_bot_id", "get_sticker_info", "harvest_menu"):
            self.assertIn(expected, payloads, f"Нет кнопки {expected}")

    def test_id_harvest_keyboard_has_all_actions(self):
        kb = id_harvest_keyboard()
        payloads = {p for _, p in _button_texts(kb)}
        for expected in ("harvest_by_link", "harvest_by_message",
                         "harvest_bot_id", "harvest_back"):
            self.assertIn(expected, payloads, f"Нет кнопки {expected}")

    def test_harvest_back_returns_main_menu(self):
        """harvest_back должен возвращать главное меню (payload harvest_menu)."""
        kb = main_menu_keyboard()
        payloads = {p for _, p in _button_texts(kb)}
        self.assertIn("harvest_menu", payloads)


if __name__ == "__main__":
    unittest.main()
