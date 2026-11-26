"""Typing settings, app preferences, and v1.1-compatible atomic JSON persistence."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

from .hotkey_parser import HotkeyError, parse_hotkey, format_hotkey

APP_DIR = os.path.join(os.path.expanduser("~"), ".typesim")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

HUD_ANCHORS = ("top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right")
THEME_MODES = ("system", "light", "dark")
UNICODE_METHODS = ("sendinput", "clipboard")
DEFAULT_HOTKEYS = {"hotkey_start": "f9", "hotkey_pause": "f10", "hotkey_stop": "f11"}


def _num(raw: dict, key: str, default, lo, hi, cast):
    raw_val = raw.get(key)
    if isinstance(raw_val, bool):
        return default
    try:
        v = cast(raw[key])
    except (KeyError, TypeError, ValueError, OverflowError):
        return default
    if v != v:  # NaN
        return default
    return min(hi, max(lo, v))


def _flag(raw: dict, key: str, default: bool) -> bool:
    v = raw.get(key, default)
    return v if isinstance(v, bool) else default


@dataclass
class TypingSettings:
    """Per-session typing behaviour. Field order is the on-disk key order (v1.1 keys first)."""

    wpm: int = 65
    variation: float = 0.20
    error_rate: float = 0.025
    error_correction_delay: float = 0.15
    thinking_pause_chance: float = 0.02
    thinking_pause_min: float = 0.5
    thinking_pause_max: float = 2.0
    burst_mode: bool = False
    burst_chars: int = 8
    burst_pause: float = 0.5
    unicode_method: str = "sendinput"
    countdown: int = 3
    hotkey_start: str = "f9"
    hotkey_pause: str = "f10"
    hotkey_stop: str = "f11"
    coding_mode: bool = False
    strip_ide_auto_indent: bool = True
    focus_guard: bool = True
    focus_resume_countdown: int = 2

    @classmethod
    def from_dict(cls, raw: Any) -> "TypingSettings":
        """Coerce and clamp untrusted input; unknown keys are ignored; never raises."""
        if not isinstance(raw, dict):
            raw = {}
        d = cls()
        lo, hi = sorted((
            _num(raw, "thinking_pause_min", d.thinking_pause_min, 0.1, 10.0, float),
            _num(raw, "thinking_pause_max", d.thinking_pause_max, 0.1, 10.0, float),
        ))
        method = raw.get("unicode_method")
        s = cls(
            wpm=_num(raw, "wpm", d.wpm, 10, 400, int),
            variation=_num(raw, "variation", d.variation, 0.0, 0.6, float),
            error_rate=_num(raw, "error_rate", d.error_rate, 0.0, 0.2, float),
            error_correction_delay=_num(raw, "error_correction_delay", d.error_correction_delay, 0.02, 2.0, float),
            thinking_pause_chance=_num(raw, "thinking_pause_chance", d.thinking_pause_chance, 0.0, 0.2, float),
            thinking_pause_min=lo,
            thinking_pause_max=hi,
            burst_mode=_flag(raw, "burst_mode", d.burst_mode),
            burst_chars=_num(raw, "burst_chars", d.burst_chars, 1, 100, int),
            burst_pause=_num(raw, "burst_pause", d.burst_pause, 0.0, 5.0, float),
            unicode_method=method if method in UNICODE_METHODS else "sendinput",  # v1.1 "pynput" -> sendinput
            countdown=_num(raw, "countdown", d.countdown, 0, 10, int),
            coding_mode=_flag(raw, "coding_mode", d.coding_mode),
            strip_ide_auto_indent=_flag(raw, "strip_ide_auto_indent", d.strip_ide_auto_indent),
            focus_guard=_flag(raw, "focus_guard", d.focus_guard),
            focus_resume_countdown=_num(raw, "focus_resume_countdown", d.focus_resume_countdown, 1, 3, int),
        )
        keys = {}
        for name, default in DEFAULT_HOTKEYS.items():
            try:
                keys[name] = format_hotkey(parse_hotkey(str(raw.get(name, default))))
            except HotkeyError:
                keys[name] = default
        if len(set(keys.values())) < 3:  # duplicate bindings: fall back to defaults for all three
            keys = dict(DEFAULT_HOTKEYS)
        for name, value in keys.items():
            setattr(s, name, value)
        return s

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def snapshot(self) -> "TypingSettings":
        """Isolated copy for one typing session (all fields are immutable scalars)."""
        return dataclasses.replace(self)


# Everything except hotkeys: what presets set and what "apply realism" means.
REALISM_KEYS = tuple(f.name for f in dataclasses.fields(TypingSettings) if not f.name.startswith("hotkey_"))


@dataclass
class AppPreferences:
    theme_mode: str = "system"
    close_to_tray: bool = False
    hud_anchor: str = "top-center"

    @classmethod
    def from_dict(cls, raw: Any) -> "AppPreferences":
        if not isinstance(raw, dict):
            raw = {}
        d = cls()
        return cls(
            theme_mode=raw["theme_mode"] if raw.get("theme_mode") in THEME_MODES else d.theme_mode,
            close_to_tray=_flag(raw, "close_to_tray", d.close_to_tray),
            hud_anchor=raw["hud_anchor"] if raw.get("hud_anchor") in HUD_ANCHORS else d.hud_anchor,
        )

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


_KNOWN_KEYS = {f.name for f in dataclasses.fields(TypingSettings)} | {f.name for f in dataclasses.fields(AppPreferences)}


@dataclass
class AppConfig:
    typing: TypingSettings = field(default_factory=TypingSettings)
    prefs: AppPreferences = field(default_factory=AppPreferences)
    extra: dict = field(default_factory=dict)  # unknown keys, preserved for forward compatibility


def atomic_write_json(path: str, data: Any) -> None:
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_json(path: str) -> Any:
    """Return parsed JSON, or None when missing. A corrupt file is moved to `<path>.bak` once."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        with contextlib.suppress(OSError):
            os.replace(path, path + ".bak")
        return None


def load_config(path: str | None = None) -> AppConfig:
    raw = read_json(path or CONFIG_PATH)
    if not isinstance(raw, dict):
        return AppConfig()
    extra = {k: v for k, v in raw.items() if k not in _KNOWN_KEYS}
    return AppConfig(TypingSettings.from_dict(raw), AppPreferences.from_dict(raw), extra)


def save_config(cfg: AppConfig, path: str | None = None) -> None:
    data = {**cfg.typing.to_dict(), **cfg.prefs.to_dict(), **cfg.extra}
    atomic_write_json(path or CONFIG_PATH, data)
