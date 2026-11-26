"""Qt-free Win32 hotkey parser, validator, and display formatter."""

from __future__ import annotations

from dataclasses import dataclass

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000

_NAMED_KEYS = {
    "home": 0x24, "end": 0x23, "insert": 0x2D, "delete": 0x2E, "pageup": 0x21, "pagedown": 0x22,
    "pause": 0x13, "scrolllock": 0x91,
}
_MOD_ORDER = (("ctrl", MOD_CONTROL), ("alt", MOD_ALT), ("shift", MOD_SHIFT))
_ALIASES = {
    "control": "ctrl", "return": "enter", "del": "delete", "ins": "insert",
    "pgup": "pageup", "pgdn": "pagedown", "pgdown": "pagedown",
}
_DISPLAY_NAMED = {"pageup": "PageUp", "pagedown": "PageDown", "scrolllock": "ScrollLock"}


class HotkeyError(ValueError):
    pass


@dataclass(frozen=True)
class Hotkey:
    mods: int
    vk: int
    key: str  # canonical key name, e.g. "f9"


def _key_vk(name: str) -> int | None:
    if name in _NAMED_KEYS:
        return _NAMED_KEYS[name]
    if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        return 0x70 + int(name[1:]) - 1
    if len(name) == 1 and name.isascii() and name.isalnum():
        return ord(name.upper())
    return None


def parse_hotkey(text: str) -> Hotkey:
    """`[ctrl+][alt+][shift+]<key>`, case-insensitive. Raises HotkeyError with a user-facing message."""
    parts = [_ALIASES.get(p, p) for p in text.lower().replace(" ", "").split("+")]
    key, mod_names = parts[-1], parts[:-1]
    if not key:
        raise HotkeyError("Press a key.")
    if "win" in mod_names or "meta" in mod_names:
        raise HotkeyError("The Windows key is reserved by the OS.")
    unknown = [m for m in mod_names if m not in ("ctrl", "alt", "shift")]
    if unknown or len(set(mod_names)) != len(mod_names):
        raise HotkeyError("Use Ctrl, Alt or Shift as modifiers.")
    vk = _key_vk(key)
    if vk is None:
        raise HotkeyError(f"“{key}” can't be used as a hotkey.")
    if key == "f12":
        raise HotkeyError("F12 is reserved for debuggers.")
    mods = sum(flag for name, flag in _MOD_ORDER if name in mod_names)
    if not mods and len(key) == 1:
        raise HotkeyError("Letters and digits need Ctrl, Alt or Shift.")
    if mods == MOD_SHIFT and key == "home":
        raise HotkeyError("Shift+Home is used by Coding Mode.")
    return Hotkey(mods, vk, key)


def format_hotkey(hk: Hotkey) -> str:
    return "+".join([name for name, flag in _MOD_ORDER if hk.mods & flag] + [hk.key])


def display_hotkey(text: str) -> str:
    """'ctrl+shift+f9' -> 'Ctrl+Shift+F9'."""
    def _part(p: str) -> str:
        if p in _DISPLAY_NAMED:
            return _DISPLAY_NAMED[p]
        return p.upper() if p.startswith("f") and p[1:].isdigit() else p.capitalize()

    return "+".join(_part(p) for p in text.split("+") if p)
