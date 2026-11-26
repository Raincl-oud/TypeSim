"""Pure-Python typing engine: state machine, human cadence, QWERTY typos, Focus Guard. No Qt, no Win32.

Seams: `InputBackend` (Win32 / clipboard / fake) is the external seam; `Clock`, `Sleeper` and `random.Random`
are internal seams injected by the constructor so tests run in zero wall time.
"""

from __future__ import annotations

import enum
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from .config import TypingSettings
from .estimator import (QWERTY_NEIGHBORS, SessionEstimator, base_interval, estimate_remaining, expected_delay,  # noqa: F401
                        normalize_text, sample_delay, typo_eligible)

log = logging.getLogger(__name__)

# Win32 terminals: Shift+Home auto-indent clearing would hit the shell prompt, so it is skipped for them.
TERMINAL_PROCESSES = frozenset({
    "windowsterminal.exe", "wt.exe", "powershell.exe", "pwsh.exe", "cmd.exe",
    "conhost.exe", "mintty.exe", "alacritty.exe", "wezterm-gui.exe",
})


class Key(enum.Enum):
    ENTER = "enter"
    TAB = "tab"
    SPACE = "space"
    BACKSPACE = "backspace"
    HOME = "home"


class EngineState(enum.Enum):
    IDLE = "idle"
    COUNTDOWN = "countdown"
    TYPING = "typing"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"


class PauseReason(enum.Enum):
    NONE = "none"
    MANUAL = "manual"
    FOCUS_LOST = "focus_lost"


class StopReason(enum.Enum):
    NONE = "none"
    USER = "user"
    TARGET_UNAVAILABLE = "target_unavailable"
    INPUT_BLOCKED = "input_blocked"
    ERROR = "error"


@dataclass(frozen=True)
class SessionStats:
    chars_typed: int
    total_chars: int
    elapsed_seconds: float  # time spent in TYPING (paused and countdown time excluded)
    effective_wpm: float
    typos_corrected: int
    terminal_state: EngineState  # COMPLETED | STOPPED
    reason: StopReason  # NONE when COMPLETED


class InputBackend(Protocol):
    def send_text(self, text: str) -> bool: ...  # printable Unicode (never \n, \t or space); one batch
    def send_key(self, key: Key, *, shift: bool = False) -> bool: ...
    def foreground_window(self) -> int: ...  # 0 when none
    def is_window(self, hwnd: int) -> bool: ...
    def is_own_window(self, hwnd: int) -> bool: ...
    def focus_window(self, hwnd: int) -> bool: ...
    def process_name(self, hwnd: int) -> str: ...
    def wait_modifiers_released(self, timeout_s: float) -> bool: ...
    def begin_session(self) -> None: ...
    def end_session(self) -> None: ...


class EngineListener(Protocol):
    """Called on the worker thread."""

    def on_state(self, state: EngineState, reason: PauseReason, countdown_remaining: int) -> None: ...
    def on_progress(self, done: int, total: int, live_wpm: int, eta_seconds: float) -> None: ...
    def on_finished(self, stats: SessionStats) -> None: ...


class Clock(Protocol):
    def now(self) -> float: ...


class Sleeper(Protocol):
    def wait(self, seconds: float, wake: threading.Event) -> bool: ...  # True = woken early


class SystemClock:
    def now(self) -> float:
        return time.perf_counter()


class HybridSleeper:
    """Interruptible wait with ~0.5 ms accuracy.

    Event.wait rounds up to the ~15.6 ms Windows timer tick, which would distort fast cadences by up to 55%,
    so only the part before the last tick is spent in Event.wait and the tail in a high-resolution sleep.
    Worst-case interrupt latency is therefore ~16 ms (< 20 ms spec).
    """

    COARSE = 0.016

    def wait(self, seconds: float, wake: threading.Event) -> bool:
        deadline = time.perf_counter() + max(0.0, seconds)
        while True:
            if wake.is_set():
                return True
            rem = deadline - time.perf_counter()
            if rem <= 0:
                return False
            if rem > self.COARSE:
                if wake.wait(rem - self.COARSE):
                    return True
            else:
                time.sleep(rem)
                return wake.is_set()


class _End(Exception):
    def __init__(self, reason: StopReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


def _daemon_thread(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="typesim-engine", daemon=True).start()


class TypingEngine:
    """Thread-safe, non-blocking commands; illegal commands for the current state are silently ignored."""

    def __init__(self, backend: InputBackend, listener: EngineListener, *, clock: Clock | None = None,
                 sleeper: Sleeper | None = None, rng: random.Random | None = None,
                 spawn: Callable[[Callable[[], None]], None] | None = None) -> None:
        self._b, self._listener = backend, listener
        self._clock = clock or SystemClock()
        self._sleeper = sleeper or HybridSleeper()
        self._rng = rng or random.Random()
        self._spawn = spawn or _daemon_thread
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._state = EngineState.IDLE
        self._s: TypingSettings | None = None
        self._estimator: SessionEstimator | None = None

    # ------------------------------------------------------------ public interface

    @property
    def state(self) -> EngineState:
        return self._state

    def start(self, text: str, settings: TypingSettings, target_hwnd: int | None) -> None:
        """Type `text` into `target_hwnd`, or into the window that is active when the countdown ends."""
        with self._lock:
            if self._state in (EngineState.COUNTDOWN, EngineState.TYPING, EngineState.PAUSED):
                return
            self._s = settings.snapshot()
            self._text = normalize_text(text)
            self._total = len(self._text)
            self._estimator = SessionEstimator(self._text, self._s)
            self._explicit = target_hwnd
            self._target = target_hwnd or 0
            self._resolved = False
            self._target_process = ""
            self._index = 0
            self._pending: list[tuple] = []
            self._typos = 0
            self._since_burst = 0
            self._typing_since: float | None = None
            self._typing_total = 0.0
            self._stop_req = self._pause_req = self._resume_req = False
            self._wake = threading.Event()
            self._state = EngineState.COUNTDOWN
        self._spawn(self._run)

    def pause(self) -> None:
        with self._lock:
            if self._state in (EngineState.COUNTDOWN, EngineState.TYPING):
                self._pause_req = True
                self._wake.set()

    def resume(self) -> None:
        """Instant when manually paused and the target is still focused; otherwise Focus & Resume."""
        with self._lock:
            if self._state == EngineState.PAUSED:
                self._resume_req = True
                self._wake.set()

    focus_and_resume = resume

    def stop(self) -> None:
        with self._lock:
            if self._state in (EngineState.COUNTDOWN, EngineState.TYPING, EngineState.PAUSED):
                self._stop_req = True
                self._wake.set()

    def set_live_wpm(self, wpm: int) -> int:
        """Session-only speed change (10..400); takes effect immediately in progress/ETA and from next delay."""
        applied = min(400, max(10, int(wpm)))
        emit_args: tuple[int, int, int, float] | None = None
        with self._lock:
            if self._s is not None:
                self._s.wpm = applied
                if (
                    self._state in (EngineState.COUNTDOWN, EngineState.TYPING, EngineState.PAUSED)
                    and self._estimator is not None
                ):
                    emit_args = (
                        self._index,
                        self._total,
                        applied,
                        self._estimator.remaining(self._index, applied),
                    )
        if emit_args is not None:
            self._emit("on_progress", *emit_args)
        return applied

    # ------------------------------------------------------------ worker

    def _emit(self, name: str, *args) -> None:
        try:
            getattr(self._listener, name)(*args)
        except Exception:
            log.exception("engine listener %s", name)

    def _set_state(self, state: EngineState, reason: PauseReason = PauseReason.NONE, countdown: int = 0,
                   *, reset_requests: bool = False) -> None:
        with self._lock:
            if reset_requests:
                self._pause_req = self._resume_req = False
            self._state = state
        self._emit("on_state", state, reason, countdown)

    def _progress(self) -> None:
        with self._lock:
            wpm = self._s.wpm
            idx = self._index
            total = self._total
            est = self._estimator
        eta = est.remaining(idx, wpm) if est is not None else estimate_remaining(self._text, idx, self._s)
        self._emit("on_progress", idx, total, wpm, eta)

    def _poll(self) -> bool:
        """Consume pending commands: raises on stop, returns True when a pause was requested."""
        with self._lock:
            self._wake.clear()  # clear before reading so a command arriving after this point re-wakes us
            stop, pause = self._stop_req, self._pause_req
            self._pause_req = False
        if stop:
            raise _End(StopReason.USER)
        return pause

    def _run(self) -> None:
        state, reason = EngineState.COMPLETED, StopReason.NONE
        try:
            self._b.begin_session()
            self._session()
        except _End as e:
            state, reason = EngineState.STOPPED, e.reason
        except Exception:
            log.exception("typing session failed")
            state, reason = EngineState.STOPPED, StopReason.ERROR
        finally:
            try:
                self._b.end_session()
            except Exception:
                log.exception("end_session")
        elapsed = self._typing_total
        stats = SessionStats(
            chars_typed=self._index, total_chars=self._total, elapsed_seconds=elapsed,
            effective_wpm=(self._index / 5) / (elapsed / 60) if elapsed > 0 else 0.0,
            typos_corrected=self._typos, terminal_state=state, reason=reason)
        self._set_state(state)
        self._emit("on_finished", stats)  # exactly once; COMPLETED only when every char was typed

    def _session(self) -> None:
        s = self._s
        secs = s.countdown
        pause_reason: PauseReason | None = None
        self._progress()
        while True:
            if pause_reason is not None:
                secs = self._paused(pause_reason)
                pause_reason = None
            outcome = self._countdown(secs) if secs > 0 else "ok"
            if outcome == "pause":
                pause_reason = PauseReason.MANUAL
                continue
            if outcome == "focus":
                pause_reason = PauseReason.FOCUS_LOST
                continue
            self._begin(wait_modifiers=secs == 0)
            outcome = self._type()
            if outcome == "done":
                return
            pause_reason = PauseReason.MANUAL if outcome == "pause" else PauseReason.FOCUS_LOST

    def _countdown(self, secs: int) -> str:
        for remaining in range(secs, 0, -1):
            self._set_state(EngineState.COUNTDOWN, PauseReason.NONE, remaining)
            self._sleeper.wait(1.0, self._wake)
            if self._poll():
                return "pause"
            if self._resolved:  # a Focus & Resume countdown: the target must stay valid and focused
                if not self._b.is_window(self._target):
                    raise _End(StopReason.TARGET_UNAVAILABLE)
                if self._s.focus_guard and self._b.foreground_window() != self._target:
                    return "focus"
        return "ok"

    def _begin(self, *, wait_modifiers: bool) -> None:
        b = self._b
        if not self._resolved:
            if self._explicit is None:
                fg = b.foreground_window()
                if not fg or b.is_own_window(fg) or not b.is_window(fg):
                    raise _End(StopReason.TARGET_UNAVAILABLE)
                self._target = fg
            elif not b.focus_window(self._target) and not b.is_window(self._target):
                raise _End(StopReason.TARGET_UNAVAILABLE)
            self._resolved = True
            self._target_process = b.process_name(self._target)
        elif not b.is_window(self._target):
            raise _End(StopReason.TARGET_UNAVAILABLE)
        if wait_modifiers:  # a modifier-combo hotkey may still be physically held
            b.wait_modifiers_released(0.4)

    def _paused(self, reason: PauseReason) -> int:
        """Block until resumed; returns the countdown (seconds) to run before typing continues."""
        self._set_state(EngineState.PAUSED, reason, reset_requests=True)
        b, s = self._b, self._s
        while True:
            with self._lock:
                self._wake.clear()
                stop, resume = self._stop_req, self._resume_req
                self._resume_req = False
            if stop:
                raise _End(StopReason.USER)
            if self._resolved and not b.is_window(self._target):
                raise _End(StopReason.TARGET_UNAVAILABLE)
            if resume:
                if not self._resolved:
                    return s.countdown  # paused during the initial countdown: start it over
                if reason == PauseReason.MANUAL and (not s.focus_guard or b.foreground_window() == self._target):
                    return 0
                if b.focus_window(self._target):
                    return s.focus_resume_countdown
                if not b.is_window(self._target):
                    raise _End(StopReason.TARGET_UNAVAILABLE)
                reason = PauseReason.FOCUS_LOST  # couldn't focus: stay paused, let the UI say so
                self._set_state(EngineState.PAUSED, reason)
                continue
            self._sleeper.wait(0.25, self._wake)

    def _type(self) -> str:
        b, s, clock = self._b, self._s, self._clock
        self._set_state(EngineState.TYPING)
        self._typing_since = next_at = clock.now()
        try:
            while True:
                if self._poll():
                    return "pause"
                if not self._pending:
                    if self._index >= self._total:
                        return "done"
                    self._pending = self._expand()
                if not b.is_window(self._target):
                    raise _End(StopReason.TARGET_UNAVAILABLE)
                if s.focus_guard and b.foreground_window() != self._target:
                    return "focus"
                act, ok = self._pending[0], True
                if act[0] == "delay":
                    now = clock.now()
                    next_at = now if now - next_at > 0.25 else next_at  # never burst to catch up after a stall
                    next_at += act[1]  # deadline accumulator: per-key overhead does not drift the WPM
                    if self._sleeper.wait(max(0.0, next_at - clock.now()), self._wake):
                        next_at -= act[1]
                        continue
                elif act[0] == "text":
                    ok = b.send_text(act[1])
                elif act[0] == "key":
                    ok = b.send_key(act[1], shift=act[2])
                else:  # "typo": the correction finished
                    self._typos += 1
                if not ok:
                    raise _End(StopReason.INPUT_BLOCKED)
                self._pending.pop(0)
                if not self._pending:  # the index only advances once a character's whole queue is delivered
                    self._index += 1
                    self._progress()
        finally:
            self._typing_total += clock.now() - self._typing_since

    # ------------------------------------------------------------ per-character action queue

    def _expand(self) -> list[tuple]:
        """Actions for text[index]: ("delay", s) | ("text", str) | ("key", Key, shift) | ("typo",)."""
        s, rng, text, i = self._s, self._rng, self._text, self._index
        ch, prev = text[i], text[i - 1] if i else ""
        base = base_interval(s.wpm)
        delay = sample_delay(ch, prev, s, rng)
        if s.burst_mode:
            if self._since_burst >= s.burst_chars:
                delay += s.burst_pause
                self._since_burst = 0
            self._since_burst += 1
        if ch == " " and rng.random() < s.thinking_pause_chance:
            delay += rng.uniform(s.thinking_pause_min, s.thinking_pause_max)
        lead = [("delay", delay)]

        if ch == "\n":
            acts = lead + [("key", Key.ENTER, False)]
            if s.coding_mode and s.strip_ide_auto_indent and self._target_process.lower() not in TERMINAL_PROCESSES:
                gap = ("delay", max(0.03, base * 0.5))  # let the IDE finish its auto-indent first
                acts += [gap, ("key", Key.HOME, True), gap, ("key", Key.SPACE, False), gap,
                         ("key", Key.BACKSPACE, False)]
            return acts
        if ch == "\t":
            return lead + [("key", Key.TAB, False)]
        if ch == " ":
            return lead + [("key", Key.SPACE, False)]
        if typo_eligible(ch, s.coding_mode) and rng.random() < s.error_rate:
            return lead + self._typo(ch, text[i + 1] if i + 1 < self._total else "", base)
        return lead + [("text", ch)]

    def _typo(self, ch: str, nxt: str, base: float) -> list[tuple]:
        s, rng = self._s, self._rng
        T = lambda c: ("text", c)  # noqa: E731
        BS = ("key", Key.BACKSPACE, False)
        corr = ("delay", s.error_correction_delay)
        next_ok = bool(nxt) and typo_eligible(nxt, s.coding_mode)
        kind = rng.choices(("adjacent", "transpose", "double"), (70, 20, 10))[0]
        if kind == "transpose" and not (ch.isalpha() and next_ok and nxt.isalpha() and nxt.lower() != ch.lower()):
            kind = "adjacent"
        if kind == "transpose":
            seq = [T(nxt), T(ch), corr, BS, BS, T(ch)]  # the next char is then typed normally
        elif kind == "double":
            seq = [T(ch), T(ch), corr, BS]
        else:
            wrong = rng.choice(QWERTY_NEIGHBORS[ch.lower()])
            wrong = wrong.upper() if ch.isupper() else wrong
            if next_ok and rng.random() < 0.20:  # overshoot: types on before noticing
                seq = [T(wrong), T(nxt), corr, BS, BS, T(ch)]
            else:
                seq = [T(wrong), corr, BS, T(ch)]
        out: list[tuple] = []
        for k, act in enumerate(seq):
            if k and act[0] != "delay" and seq[k - 1][0] != "delay":
                out.append(("delay", base * rng.uniform(0.6, 1.0)))
            out.append(act)
        return out + [("typo",)]
