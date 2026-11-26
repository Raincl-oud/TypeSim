"""Tests for config migration, clamping, atomic writes, presets, and profile CRUD."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from typesim.config import AppConfig, AppPreferences, TypingSettings, load_config, save_config
from typesim.profiles import (
    BUILTIN_PRESETS, apply_preset, delete_profile, list_profiles, load_profile, preset_matches, save_profile,
)


class TestConfigAndProfiles(unittest.TestCase):
    def test_v11_config_migration_and_clamping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            v11 = {
                "wpm": 999,
                "variation": -0.5,
                "error_rate": 0.9,
                "error_correction_delay": 0.001,
                "thinking_pause_chance": 0.5,
                "thinking_pause_min": 4.0,
                "thinking_pause_max": 1.2,
                "burst_mode": True,
                "burst_chars": 0,
                "burst_pause": 9.0,
                "unicode_method": "pynput",
                "countdown": 25,
                "hotkey_start": "F9",
                "hotkey_pause": "f10",
                "hotkey_stop": "f11",
                "future_setting": "keep_me",
            }
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(v11, f)

            loaded = load_config(cfg_path)
            t = loaded.typing
            self.assertEqual(t.wpm, 400)
            self.assertEqual(t.variation, 0.0)
            self.assertEqual(t.error_rate, 0.2)
            self.assertEqual(t.error_correction_delay, 0.02)
            self.assertEqual(t.thinking_pause_chance, 0.2)
            self.assertEqual((t.thinking_pause_min, t.thinking_pause_max), (1.2, 4.0))
            self.assertTrue(t.burst_mode)
            self.assertEqual(t.burst_chars, 1)
            self.assertEqual(t.burst_pause, 5.0)
            self.assertEqual(t.unicode_method, "sendinput")
            self.assertEqual(t.countdown, 10)
            self.assertEqual((t.hotkey_start, t.hotkey_pause, t.hotkey_stop), ("f9", "f10", "f11"))
            self.assertFalse(t.coding_mode)
            self.assertTrue(t.strip_ide_auto_indent)
            self.assertTrue(t.focus_guard)
            self.assertEqual(t.focus_resume_countdown, 2)
            self.assertEqual(loaded.extra, {"future_setting": "keep_me"})

            # Round-trip preserves unknown keys and writes flat v1.1 + v2 keys
            loaded.prefs.theme_mode = "dark"
            loaded.prefs.hud_anchor = "bottom-right"
            save_config(loaded, cfg_path)
            with open(cfg_path, "r", encoding="utf-8") as f:
                raw_out = json.load(f)
            self.assertEqual(raw_out["future_setting"], "keep_me")
            self.assertEqual(raw_out["theme_mode"], "dark")
            self.assertEqual(raw_out["hud_anchor"], "bottom-right")

    def test_corrupt_config_backs_up_and_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write("{broken json")
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.typing.wpm, 65)
            self.assertTrue(os.path.exists(cfg_path + ".bak"))

    def test_boolean_and_duplicate_hotkeys_sanitized(self) -> None:
        s = TypingSettings.from_dict({
            "wpm": True,
            "hotkey_start": "f9",
            "hotkey_pause": "f9",
            "hotkey_stop": "f12",
        })
        self.assertEqual(s.wpm, 65)
        self.assertEqual((s.hotkey_start, s.hotkey_pause, s.hotkey_stop), ("f9", "f10", "f11"))

    def test_snapshot_isolation(self) -> None:
        s = TypingSettings(wpm=80)
        snap = s.snapshot()
        snap.wpm = 220
        self.assertEqual(s.wpm, 80)

    def test_presets_do_not_clobber_hotkeys_or_prefs(self) -> None:
        base = TypingSettings(hotkey_start="ctrl+f9", unicode_method="clipboard", countdown=5, focus_guard=False)
        for name in BUILTIN_PRESETS:
            updated = apply_preset(base, name)
            self.assertTrue(preset_matches(updated, name))
            self.assertEqual(updated.hotkey_start, "ctrl+f9")
            self.assertEqual(updated.unicode_method, "clipboard")
            self.assertEqual(updated.countdown, 5)
            self.assertFalse(updated.focus_guard)
        self.assertTrue(apply_preset(base, "Precision Code").coding_mode)

    def test_v11_profile_crud_and_pref_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prof_path = os.path.join(tmp, "profiles.json")
            with open(prof_path, "w", encoding="utf-8") as f:
                json.dump({
                    "LegacyWork": {
                        "wpm": 92,
                        "unicode_method": "pynput",
                        "hotkey_start": "ctrl+shift+f8",
                        "theme_mode": "light",  # pref key must never leak into profile
                    }
                }, f)

            self.assertEqual(list_profiles(prof_path), ["LegacyWork"])
            loaded = load_profile("LegacyWork", prof_path)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.wpm, 92)
            self.assertEqual(loaded.unicode_method, "sendinput")
            self.assertEqual(loaded.hotkey_start, "ctrl+shift+f8")
            self.assertTrue(loaded.focus_guard)

            cfg = AppConfig(typing=loaded, prefs=AppPreferences(theme_mode="dark", close_to_tray=True))
            self.assertEqual(cfg.prefs.theme_mode, "dark")

            with self.assertRaises(ValueError):
                save_profile("Natural", loaded, prof_path)
            with self.assertRaises(ValueError):
                save_profile("   ", loaded, prof_path)

            cleaned = save_profile("  Demo Profile  ", TypingSettings(wpm=130, coding_mode=True), prof_path)
            self.assertEqual(cleaned, "Demo Profile")
            self.assertEqual(list_profiles(prof_path), ["Demo Profile", "LegacyWork"])
            self.assertTrue(delete_profile("LegacyWork", prof_path))
            self.assertFalse(delete_profile("Missing", prof_path))
            self.assertEqual(list_profiles(prof_path), ["Demo Profile"])
