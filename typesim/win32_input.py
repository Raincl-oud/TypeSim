"""Pure-ctypes Win32 layer: SendInput, window/focus helpers, OS queries, and InputBackend adapters.

Every user32/kernel32 function gets explicit argtypes/restype (HWND is pointer-sized on x64) and lives on
private WinDLL instances so other libraries cannot mutate our prototypes.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass

from .engine import Key

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


assert ctypes.sizeof(INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
VK_BACK, VK_TAB, VK_RETURN, VK_SHIFT, VK_CONTROL, VK_MENU = 0x08, 0x09, 0x0D, 0x10, 0x11, 0x12
VK_SPACE, VK_END, VK_HOME, VK_LWIN, VK_RWIN, VK_V = 0x20, 0x23, 0x24, 0x5B, 0x5C, 0x56
VK_PRIOR, VK_NEXT, VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN, VK_INSERT, VK_DELETE = 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E
EXTENDED_VKS = {VK_HOME, VK_END, VK_LEFT, VK_RIGHT, VK_UP, VK_DOWN, VK_INSERT, VK_DELETE, VK_PRIOR, VK_NEXT}
MAPVK_VK_TO_VSC, SW_RESTORE, GW_OWNER = 0, 9, 4
SPI_GETCLIENTAREAANIMATION = 0x1042
GWL_EXSTYLE, WS_EX_NOACTIVATE = -20, 0x08000000
PROCESS_QUERY_LIMITED_INFORMATION, TOKEN_QUERY, TOKEN_ELEVATION_CLASS = 0x1000, 0x8, 20
DWMWA_CLOAKED = 14

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _sig(fn, restype, *argtypes):
    fn.restype, fn.argtypes = restype, argtypes


_sig(user32.SendInput, wintypes.UINT, wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_sig(user32.MapVirtualKeyW, wintypes.UINT, wintypes.UINT, wintypes.UINT)
_sig(user32.GetAsyncKeyState, ctypes.c_short, ctypes.c_int)
_sig(user32.GetForegroundWindow, wintypes.HWND)
_sig(user32.IsWindow, wintypes.BOOL, wintypes.HWND)
_sig(user32.IsIconic, wintypes.BOOL, wintypes.HWND)
_sig(user32.IsWindowVisible, wintypes.BOOL, wintypes.HWND)
_sig(user32.ShowWindow, wintypes.BOOL, wintypes.HWND, ctypes.c_int)
_sig(user32.SetForegroundWindow, wintypes.BOOL, wintypes.HWND)
_sig(user32.BringWindowToTop, wintypes.BOOL, wintypes.HWND)
_sig(user32.GetWindow, wintypes.HWND, wintypes.HWND, wintypes.UINT)
_sig(user32.GetWindowThreadProcessId, wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_sig(user32.AttachThreadInput, wintypes.BOOL, wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
_sig(user32.GetWindowTextLengthW, ctypes.c_int, wintypes.HWND)
_sig(user32.GetWindowTextW, ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_sig(user32.EnumWindows, wintypes.BOOL, _WNDENUMPROC, wintypes.LPARAM)
_sig(user32.SystemParametersInfoW, wintypes.BOOL, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT)
_sig(user32.GetWindowLongPtrW, ctypes.c_ssize_t, wintypes.HWND, ctypes.c_int)
_sig(user32.SetWindowLongPtrW, ctypes.c_ssize_t, wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
_sig(kernel32.OpenProcess, wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_sig(kernel32.GetCurrentProcess, wintypes.HANDLE)
_sig(kernel32.CloseHandle, wintypes.BOOL, wintypes.HANDLE)
_sig(kernel32.GetCurrentThreadId, wintypes.DWORD)
_sig(kernel32.QueryFullProcessImageNameW, wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
     ctypes.POINTER(wintypes.DWORD))
_sig(advapi32.OpenProcessToken, wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
_sig(advapi32.GetTokenInformation, wintypes.BOOL, wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
     ctypes.POINTER(wintypes.DWORD))
_sig(dwmapi.DwmGetWindowAttribute, ctypes.c_long, wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)


# ---------------------------------------------------------------- input events

def _unicode_events(text: str) -> list[INPUT]:
    data = text.encode("utf-16-le")
    out = []
    for i in range(0, len(data), 2):
        unit = int.from_bytes(data[i:i + 2], "little")
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            ev = INPUT(type=INPUT_KEYBOARD)
            ev.ki = KEYBDINPUT(0, unit, flags, 0, 0)
            out.append(ev)
    return out


def _vk_event(vk: int, up: bool) -> INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0)
    ev = INPUT(type=INPUT_KEYBOARD)
    ev.ki = KEYBDINPUT(vk, user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC), flags, 0, 0)
    return ev


def _send(events: list[INPUT]) -> bool:
    """One SendInput batch; False when Windows injected fewer events (UIPI block)."""
    arr = (INPUT * len(events))(*events)
    return user32.SendInput(len(events), arr, ctypes.sizeof(INPUT)) == len(events)


def _key_events(vk: int, *, shift: bool = False, ctrl: bool = False) -> list[INPUT]:
    mods = ([VK_SHIFT] if shift else []) + ([VK_CONTROL] if ctrl else [])
    return ([_vk_event(m, False) for m in mods] + [_vk_event(vk, False), _vk_event(vk, True)]
            + [_vk_event(m, True) for m in reversed(mods)])


_KEY_VK = {Key.ENTER: VK_RETURN, Key.TAB: VK_TAB, Key.SPACE: VK_SPACE, Key.BACKSPACE: VK_BACK, Key.HOME: VK_HOME}
_MODIFIERS = (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)


# ---------------------------------------------------------------- windows

@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    process_name: str

    @property
    def label(self) -> str:
        return f"{self.title} — {self.process_name}" if self.process_name else self.title


def get_foreground_hwnd() -> int:
    return user32.GetForegroundWindow() or 0


def is_window_valid(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def _pid(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_own_window(hwnd: int) -> bool:
    return bool(hwnd) and _pid(hwnd) == os.getpid()


def process_name(hwnd: int) -> str:
    pid = _pid(hwnd)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid) if pid else None
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _is_cloaked(hwnd: int) -> bool:
    flag = wintypes.DWORD(0)
    try:
        return dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(flag), ctypes.sizeof(flag)) == 0 and flag.value != 0
    except OSError:
        return False


def enumerate_windows() -> list[WindowInfo]:
    found: list[WindowInfo] = []

    def visit(hwnd, _lparam):
        try:
            if (user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, GW_OWNER)
                    and not is_own_window(hwnd) and not _is_cloaked(hwnd)):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    found.append(WindowInfo(int(hwnd), buf.value, process_name(hwnd)))
        except Exception:  # one odd window must not abort the enumeration
            pass
        return True

    cb = _WNDENUMPROC(visit)  # keep a reference for the duration of the call
    user32.EnumWindows(cb, 0)
    return found


def focus_window(hwnd: int) -> bool:
    """Bring `hwnd` to the foreground. No synthetic Alt tap: its Alt-up would open the target's menu bar."""
    if not is_window_valid(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    if get_foreground_hwnd() == hwnd:
        return True
    cur = kernel32.GetCurrentThreadId()
    peers = {t for t in (user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None),
                         user32.GetWindowThreadProcessId(hwnd, None)) if t and t != cur}
    attached = [t for t in peers if user32.AttachThreadInput(cur, t, True)]
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        for t in attached:
            user32.AttachThreadInput(cur, t, False)
    deadline = time.monotonic() + 0.15
    while get_foreground_hwnd() != hwnd and time.monotonic() < deadline:
        time.sleep(0.01)
    return get_foreground_hwnd() == hwnd


def _token_elevated(proc_handle: wintypes.HANDLE) -> bool | None:
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(proc_handle, TOKEN_QUERY, ctypes.byref(token)):
        return True if ctypes.get_last_error() == 5 else None
    try:
        elevated, ret = wintypes.DWORD(0), wintypes.DWORD(0)
        ok = advapi32.GetTokenInformation(
            token, TOKEN_ELEVATION_CLASS, ctypes.byref(elevated), ctypes.sizeof(elevated), ctypes.byref(ret)
        )
        return bool(elevated.value) if ok else None
    finally:
        kernel32.CloseHandle(token)


def is_self_elevated() -> bool:
    """True when TypeSim itself is running elevated (Administrator)."""
    return bool(_token_elevated(kernel32.GetCurrentProcess()))


def is_window_elevated(hwnd: int) -> bool | None:
    """True/False when known, None when it cannot be determined (no warning is shown then)."""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, _pid(hwnd)) if hwnd else None
    if not handle:
        return None
    try:
        return _token_elevated(handle)
    finally:
        kernel32.CloseHandle(handle)


def set_no_activate(hwnd: int) -> None:
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)


def wait_modifiers_released(timeout_s: float = 0.4, poll_s: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout_s
    while any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MODIFIERS):
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_s)
    return True


def system_prefers_dark_theme() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def system_animations_enabled() -> bool:
    flag = wintypes.BOOL(1)
    return bool(user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(flag), 0)) and bool(flag.value)


# ---------------------------------------------------------------- InputBackend adapters

class Win32InputBackend:
    """SendInput with KEYEVENTF_UNICODE: no clipboard involved, surrogate pairs sent as one batch."""

    def send_text(self, text: str) -> bool:
        return _send(_unicode_events(text))

    def send_key(self, key: Key, *, shift: bool = False) -> bool:
        return _send(_key_events(_KEY_VK[key], shift=shift))

    def foreground_window(self) -> int:
        return get_foreground_hwnd()

    def is_window(self, hwnd: int) -> bool:
        return is_window_valid(hwnd)

    def is_own_window(self, hwnd: int) -> bool:
        return is_own_window(hwnd)

    def focus_window(self, hwnd: int) -> bool:
        return focus_window(hwnd)

    def process_name(self, hwnd: int) -> str:
        return process_name(hwnd)

    def wait_modifiers_released(self, timeout_s: float) -> bool:
        return wait_modifiers_released(timeout_s)

    def begin_session(self) -> None:
        pass

    def end_session(self) -> None:
        pass


class ClipboardInputBackend(Win32InputBackend):
    """Paste-per-character fallback for apps that ignore KEYEVENTF_UNICODE (some remote desktops).

    Clipboard is saved once per session and restored once at the end. The 80 ms of waits per character
    are uninterruptible by design.
    """

    def __init__(self) -> None:
        self._saved: str | None = None

    def begin_session(self) -> None:
        import pyperclip
        try:
            self._saved = pyperclip.paste()
        except Exception:
            self._saved = None

    def end_session(self) -> None:
        import pyperclip
        if self._saved is not None:
            try:
                pyperclip.copy(self._saved)
            except Exception:
                pass
            self._saved = None

    def send_text(self, text: str) -> bool:
        import pyperclip
        pyperclip.copy(text)
        time.sleep(0.03)
        ok = _send(_key_events(VK_V, ctrl=True))
        time.sleep(0.05)
        return ok


def make_backend(unicode_method: str) -> Win32InputBackend:
    return ClipboardInputBackend() if unicode_method == "clipboard" else Win32InputBackend()
