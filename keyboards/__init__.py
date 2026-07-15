"""
Пакет keyboards для работы с inline-клавиатурами.
"""
from .admin import (
    admin_broadcast_button_keyboard,
    admin_broadcast_image_keyboard,
    admin_broadcast_launch_keyboard,
    admin_broadcast_preview_keyboard,
    admin_broadcast_running_keyboard,
    admin_broadcast_text_keyboard,
    admin_panel_keyboard,
)
from .main_menu import main_menu_keyboard

__all__ = [
    "main_menu_keyboard",
    "admin_panel_keyboard",
    "admin_broadcast_image_keyboard",
    "admin_broadcast_text_keyboard",
    "admin_broadcast_button_keyboard",
    "admin_broadcast_preview_keyboard",
    "admin_broadcast_launch_keyboard",
    "admin_broadcast_running_keyboard",
]
