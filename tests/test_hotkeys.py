"""Tests for hotkey parsing, validation, HotkeyManager conflicts, and WM_HOTKEY/WM_SETTINGCHANGE filter."""

from __future__ import annotations

import ctypes
import os
import unittest
from ctypes import wintypes

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import sip
from PyQt6.QtWidgets import QApplication

from typesim.hotkeys import (
    HotkeyError, HotkeyManager, MOD_ALT, MOD_CONTROL, MOD_SHIFT,
    WM_HOTKEY, WM_SETTINGCHANGE, _Filter, display_hotkey, format_hotkey, parse_hotkey,
)


_APP: QApplication | None = None


def _app() -> QApplication:
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


class TestHotkeys(unittest.TestCase):
    def test_parse_and_format_valid_bindings(self) -> None:
        hk = parse_hotkey("F9")
        self.assertEqual((hk.mods, hk.vk), (0, 0x78))
        self.assertEqual(format_hotkey(hk), "f9")
        self.assertEqual(display_hotkey("f9"), "F9")

        combo = parse_hotkey("Shift + Control + f9")
        self.assertEqual((combo.mods, combo.vk), (MOD_CONTROL | MOD_SHIFT, 0x78))
        self.assertEqual(format_hotkey(combo), "ctrl+shift+f9")
        self.assertEqual(display_hotkey("ctrl+shift+f9"), "Ctrl+Shift+F9")

        alt_a = parse_hotkey("alt+a")
        self.assertEqual((alt_a.mods, alt_a.vk), (MOD_ALT, ord("A")))
        self.assertEqual(display_hotkey("ctrl+pageup"), "Ctrl+PageUp")

    def test_reject_reserved_and_unsafe_bindings(self) -> None:
        for bad in ("win+f9", "f12", "a", "5", "space", "enter", "tab", "backspace", "esc", "shift+home", "ctrl+"):
            with self.subTest(bad=bad):
                with self.assertRaises(HotkeyError):
                    parse_hotkey(bad)

    def test_hotkey_manager_conflict_and_suspend_resume(self) -> None:
        _app()
        registered: list[tuple[int, int, int]] = []
        unregistered: list[int] = []

        def fake_reg(_hwnd, hid, mods, vk):
            if hid == 2:  # simulate pause hotkey taken by another app
                return False
            registered.append((hid, mods, vk))
            return True

        def fake_unreg(_hwnd, hid):
            unregistered.append(hid)
            return True

        mgr = HotkeyManager(register=fake_reg, unregister=fake_unreg)
        try:
            res = mgr.apply({"start": "f9", "pause": "f10", "stop": "f11"})
            self.assertIsNone(res["start"])
            self.assertIn("already used", res["pause"])
            self.assertIsNone(res["stop"])

            dup = mgr.apply({"start": "f9", "pause": "f9", "stop": "f11"})
            self.assertIn("Already used", dup["pause"])

            mgr.suspend()
            self.assertIn(1, unregistered)
            registered.clear()
            res2 = mgr.resume()
            self.assertIsNone(res2["start"])
            self.assertTrue(any(hid == 1 for hid, _, _ in registered))
        finally:
            mgr.shutdown()

    def test_native_event_filter_handles_messages_safely(self) -> None:
        hotkeys: list[int] = []
        settings: list[tuple[int, str]] = []
        flt = _Filter(hotkeys.append, lambda wp, lp: settings.append((wp, lp)))

        self.assertEqual(flt.nativeEventFilter(b"windows_generic_MSG", None), (False, 0))

        msg = wintypes.MSG()
        msg.message = WM_HOTKEY
        msg.wParam = 2
        ptr = sip.voidptr(ctypes.addressof(msg))
        self.assertEqual(flt.nativeEventFilter(b"windows_generic_MSG", ptr), (True, 0))
        self.assertEqual(hotkeys, [2])

        area = ctypes.create_unicode_buffer("ImmersiveColorSet")
        msg2 = wintypes.MSG()
        msg2.message = WM_SETTINGCHANGE
        msg2.wParam = 0x1043
        msg2.lParam = ctypes.addressof(area)
        ptr2 = sip.voidptr(ctypes.addressof(msg2))
        self.assertEqual(flt.nativeEventFilter(b"windows_generic_MSG", ptr2), (False, 0))
        self.assertEqual(settings, [(0x1043, "ImmersiveColorSet")])
