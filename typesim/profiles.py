"""Built-in presets and user-defined typing profiles (`~/.typesim/profiles.json`)."""

from __future__ import annotations

import dataclasses
import os

from .config import APP_DIR, REALISM_KEYS, TypingSettings, atomic_write_json, read_json

PROFILES_PATH = os.path.join(APP_DIR, "profiles.json")

# Realism keys only: presets never touch hotkeys, input method, countdown, focus settings or AppPreferences.
_BASE = dict(burst_mode=False, coding_mode=False, strip_ide_auto_indent=True)
BUILTIN_PRESETS: dict[str, dict] = {
    "Casual": dict(_BASE, wpm=45, variation=0.28, error_rate=0.040, error_correction_delay=0.22,
                   thinking_pause_chance=0.030, thinking_pause_min=0.7, thinking_pause_max=2.5),
    "Natural": dict(_BASE, wpm=65, variation=0.20, error_rate=0.025, error_correction_delay=0.15,
                    thinking_pause_chance=0.020, thinking_pause_min=0.5, thinking_pause_max=2.0),
    "Fast": dict(_BASE, wpm=110, variation=0.15, error_rate=0.015, error_correction_delay=0.10,
                 thinking_pause_chance=0.010, thinking_pause_min=0.3, thinking_pause_max=1.2),
    "Precision Code": dict(_BASE, wpm=85, variation=0.12, error_rate=0.0, error_correction_delay=0.10,
                           thinking_pause_chance=0.005, thinking_pause_min=0.3, thinking_pause_max=1.0,
                           coding_mode=True),
}
assert all(set(p) <= set(REALISM_KEYS) for p in BUILTIN_PRESETS.values())


def apply_preset(settings: TypingSettings, name: str) -> TypingSettings:
    """Return a new settings object with the preset's realism keys applied."""
    return TypingSettings.from_dict({**settings.to_dict(), **BUILTIN_PRESETS[name]})


def preset_matches(settings: TypingSettings, name: str) -> bool:
    return all(getattr(settings, k) == v for k, v in BUILTIN_PRESETS[name].items())


def _read(path: str | None) -> dict[str, TypingSettings]:
    raw = read_json(path or PROFILES_PATH)
    if not isinstance(raw, dict):
        return {}
    return {str(name): TypingSettings.from_dict(entry) for name, entry in raw.items()}


def _write(profiles: dict[str, TypingSettings], path: str | None) -> None:
    atomic_write_json(path or PROFILES_PATH, {n: s.to_dict() for n, s in profiles.items()})


def list_profiles(path: str | None = None) -> list[str]:
    return sorted(_read(path), key=str.lower)


def load_profile(name: str, path: str | None = None) -> TypingSettings | None:
    """Full settings including hotkeys; v1.1 entries get v2 defaults. Caller re-applies hotkeys."""
    return _read(path).get(name)


def save_profile(name: str, settings: TypingSettings, path: str | None = None) -> str:
    """Create or overwrite a profile; returns the cleaned name. Raises ValueError for bad names."""
    name = name.strip()
    if not 1 <= len(name) <= 40:
        raise ValueError("Profile name must be 1–40 characters.")
    if name.lower() in {p.lower() for p in BUILTIN_PRESETS}:
        raise ValueError(f"“{name}” is a built-in preset name.")
    profiles = _read(path)
    profiles[name] = dataclasses.replace(settings)
    _write(profiles, path)
    return name


def delete_profile(name: str, path: str | None = None) -> bool:
    profiles = _read(path)
    if name not in profiles:
        return False
    del profiles[name]
    _write(profiles, path)
    return True
