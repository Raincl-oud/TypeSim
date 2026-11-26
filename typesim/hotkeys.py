"""Global hotkeys via Win32 RegisterHotKey, delivered through a Qt native event filter.

RegisterHotKey is bound to a dedicated hidden QWidget hwnd (thread messages are dropped by native modal
loops) and WM_HOTKEY is consumed, so F10/F11 never leak into the focused app.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Callable

from PyQt6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, pyqtSignal
from PyQt6.QtWidgets import QWidget

from .hotkey_parser import (  # noqa: F401
    Hotkey, HotkeyError, MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT,
    display_hotkey, format_hotkey, parse_hotkey,
)

WM_HOTKEY, WM_SETTINGCHANGE = 0x0312, 0x001A
SPI_SETCLIENTAREAANIMATION = 0x1043
ACTIONS = ("start", "pause", "stop")
_IDS = {"start": 1, "pause": 2, "stop": 3}


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, on_hotkey: Callable[[int], None], on_setting: Callable[[int, str], None]) -> None:
        super().__init__()
        self._on_hotkey, self._on_setting = on_hotkey, on_setting

    def nativeEventFilter(self, eventType, message):
        try:  # an exception escaping a PyQt virtual aborts the process
            if message is None or bytes(eventType) != b"windows_generic_MSG":
                return False, 0
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self._on_hotkey(int(msg.wParam))
                return True, 0
            if msg.message == WM_SETTINGCHANGE:
                area = ctypes.wstring_at(msg.lParam) if msg.lParam else ""
                self._on_setting(int(msg.wParam), area)  # never consumed: every window needs a copy
        except Exception:
            logging.exception("native event filter")
        return False, 0


def _win32_register():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
    u.RegisterHotKey.restype = wintypes.BOOL
    u.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
    u.UnregisterHotKey.restype = wintypes.BOOL
    return u.RegisterHotKey, u.UnregisterHotKey


class HotkeyManager(QObject):
    """Owns the one native event filter (WM_HOTKEY and WM_SETTINGCHANGE) for the whole app."""

    triggered = pyqtSignal(str)  # "start" | "pause" | "stop"
    settingChanged = pyqtSignal(int, str)  # (wParam, lParam string)

    def __init__(self, register: Callable | None = None, unregister: Callable | None = None, parent=None) -> None:
        super().__init__(parent)
        if register is None:
            register, unregister = _win32_register()
        self._register, self._unregister = register, unregister or (lambda hwnd, hid: True)
        self._host = QWidget()  # never shown; never call setWindowFlags (it would recreate the hwnd)
        self._hwnd = int(self._host.winId())
        self._active: set[int] = set()
        self._last: dict[str, str] = {}
        self._filter = _Filter(self._on_hotkey, self.settingChanged.emit)
        self._app = QCoreApplication.instance()
        self._app.installNativeEventFilter(self._filter)

    def _on_hotkey(self, hid: int) -> None:
        for action, i in _IDS.items():
            if i == hid:
                self.triggered.emit(action)

    def _unregister_all(self) -> None:
        for hid in list(self._active):
            self._unregister(self._hwnd, hid)
        self._active.clear()

    def apply(self, bindings: dict[str, str]) -> dict[str, str | None]:
        """(Re)register all bindings. Returns action -> conflict/invalid message, or None when active."""
        self._last = dict(bindings)
        self._unregister_all()
        result: dict[str, str | None] = {}
        seen: dict[str, str] = {}
        for action in ACTIONS:
            try:
                hk = parse_hotkey(bindings[action])
            except (HotkeyError, KeyError) as e:
                result[action] = str(e)
                continue
            canon = format_hotkey(hk)
            if canon in seen:
                result[action] = f"Already used for {seen[canon]}."
                continue
            seen[canon] = action.capitalize()
            if self._register(self._hwnd, _IDS[action], hk.mods | MOD_NOREPEAT, hk.vk):
                self._active.add(_IDS[action])
                result[action] = None
            else:
                result[action] = f"{display_hotkey(canon)} is already used by another app."
        return result

    def suspend(self) -> None:
        """Unregister everything (Key-Capture recording) so the pressed key reaches the recorder."""
        self._unregister_all()

    def resume(self) -> dict[str, str | None]:
        return self.apply(self._last) if self._last else {}

    def shutdown(self) -> None:
        self._unregister_all()
        self._app.removeNativeEventFilter(self._filter)
