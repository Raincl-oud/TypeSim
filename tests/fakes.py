"""Deterministic test doubles for TypingEngine and UI tests (zero OS side effects)."""

from __future__ import annotations

import threading
from typing import Callable

from typesim.engine import EngineState, Key, PauseReason, SessionStats


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t


class FakeSleeper:
    """Advances virtual clock immediately in zero wall time unless woken early."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.calls: list[float] = []

    def wait(self, seconds: float, wake: threading.Event) -> bool:
        if wake.is_set():
            return True
        self.calls.append(seconds)
        self.clock.t += max(0.0, seconds)
        return wake.is_set()


class FakeBackend:
    """In-memory InputBackend recording ops and simulating cursor, selection, and IDE auto-indent."""

    def __init__(
        self,
        *,
        foreground: int = 1001,
        valid_windows: set[int] | None = None,
        own_windows: set[int] | None = None,
        process_names: dict[int, str] | None = None,
        focus_ok: bool = True,
        send_ok: bool = True,
        auto_indent_on_enter: str = "",
    ) -> None:
        self.foreground = foreground
        self.valid_windows = {foreground} if valid_windows is None else set(valid_windows)
        self.own_windows = set(own_windows or ())
        self.process_names = dict(process_names or {foreground: "notepad.exe"})
        self.focus_ok = focus_ok
        self.send_ok = send_ok
        self.auto_indent_on_enter = auto_indent_on_enter

        self.ops: list[tuple] = []
        self.hooks: dict[int, Callable[["FakeBackend"], None]] = {}
        self.session_begins = 0
        self.session_ends = 0
        self.modifiers_waited = 0

        self._buf = ""
        self._cursor = 0
        self._sel_start: int | None = None

    @property
    def buffer(self) -> str:
        return self._buf

    def _fire_hook(self) -> None:
        n = len(self.ops)
        hook = self.hooks.pop(n, None)
        if hook is not None:
            hook(self)

    def _replace_selection(self, text: str) -> None:
        if self._sel_start is not None:
            lo, hi = sorted((self._sel_start, self._cursor))
            self._buf = self._buf[:lo] + text + self._buf[hi:]
            self._cursor = lo + len(text)
            self._sel_start = None
        else:
            self._buf = self._buf[:self._cursor] + text + self._buf[self._cursor:]
            self._cursor += len(text)

    def send_text(self, text: str) -> bool:
        self.ops.append(("text", text))
        if not self.send_ok:
            self._fire_hook()
            return False
        self._replace_selection(text)
        self._fire_hook()
        return True

    def send_key(self, key: Key, *, shift: bool = False) -> bool:
        self.ops.append(("key", key.value, shift))
        if not self.send_ok:
            self._fire_hook()
            return False
        if key == Key.ENTER:
            self._replace_selection("\n" + self.auto_indent_on_enter)
        elif key == Key.TAB:
            self._replace_selection("\t")
        elif key == Key.SPACE:
            self._replace_selection(" ")
        elif key == Key.BACKSPACE:
            if self._sel_start is not None:
                self._replace_selection("")
            elif self._cursor > 0:
                self._buf = self._buf[:self._cursor - 1] + self._buf[self._cursor:]
                self._cursor -= 1
        elif key == Key.HOME and shift:
            line_start = self._buf.rfind("\n", 0, self._cursor) + 1
            self._sel_start = line_start
        self._fire_hook()
        return True

    def foreground_window(self) -> int:
        return self.foreground

    def is_window(self, hwnd: int) -> bool:
        return hwnd in self.valid_windows

    def is_own_window(self, hwnd: int) -> bool:
        return hwnd in self.own_windows

    def focus_window(self, hwnd: int) -> bool:
        if not self.focus_ok or hwnd not in self.valid_windows:
            return False
        self.foreground = hwnd
        return True

    def process_name(self, hwnd: int) -> str:
        return self.process_names.get(hwnd, "")

    def wait_modifiers_released(self, timeout_s: float) -> bool:
        self.modifiers_waited += 1
        return True

    def begin_session(self) -> None:
        self.session_begins += 1

    def end_session(self) -> None:
        self.session_ends += 1


class RecordingListener:
    def __init__(self) -> None:
        self.states: list[tuple[EngineState, PauseReason, int]] = []
        self.progress: list[tuple[int, int, int, float]] = []
        self.finished: list[SessionStats] = []
        self.done_event = threading.Event()
        self.state_events: list[tuple[EngineState, PauseReason, threading.Event]] = []

    def on_state(self, state: EngineState, reason: PauseReason, countdown_remaining: int) -> None:
        self.states.append((state, reason, countdown_remaining))
        for st, rs, ev in self.state_events:
            if state == st and reason == rs:
                ev.set()

    def on_progress(self, done: int, total: int, live_wpm: int, eta_seconds: float) -> None:
        self.progress.append((done, total, live_wpm, eta_seconds))

    def on_finished(self, stats: SessionStats) -> None:
        self.finished.append(stats)
        self.done_event.set()
