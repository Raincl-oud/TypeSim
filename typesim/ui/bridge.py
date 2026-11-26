"""Thread-safe Engine <-> PyQt6 bridge and session lifecycle controller."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from ..config import TypingSettings
from ..engine import EngineState, InputBackend, PauseReason, SessionStats, StopReason, TypingEngine
from ..estimator import format_duration
from ..win32_input import make_backend


class EngineBridge(QObject):
    """Receives EngineListener callbacks on the worker thread and emits queued Qt signals."""

    stateChanged = pyqtSignal(object, object, int)  # EngineState, PauseReason, countdown_remaining
    progressChanged = pyqtSignal(int, int, int, float)  # done, total, live_wpm, eta_seconds
    finished = pyqtSignal(object)  # SessionStats

    def on_state(self, state: EngineState, reason: PauseReason, countdown_remaining: int) -> None:
        self.stateChanged.emit(state, reason, countdown_remaining)

    def on_progress(self, done: int, total: int, live_wpm: int, eta_seconds: float) -> None:
        self.progressChanged.emit(done, total, live_wpm, eta_seconds)

    def on_finished(self, stats: SessionStats) -> None:
        self.finished.emit(stats)


class SessionController(QObject):
    """Owns the active TypingEngine session and coordinates MainWindow, FloatingHUD, and Tray."""

    stateUpdated = pyqtSignal(object, object, int)
    progressUpdated = pyqtSignal(int, int, int, float)
    sessionEnded = pyqtSignal(object, bool)  # SessionStats, launched_from_tray
    toastRequested = pyqtSignal(str, str)  # message, kind

    def __init__(
        self,
        backend_factory: Callable[[str], InputBackend] = make_backend,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._backend_factory = backend_factory
        self._bridge = EngineBridge(self)
        self._bridge.stateChanged.connect(self._on_state)
        self._bridge.progressChanged.connect(self._on_progress)
        self._bridge.finished.connect(self._on_finished)
        self._engine: TypingEngine | None = None
        self._last_state = EngineState.IDLE
        self._last_reason = PauseReason.NONE
        self._resume_pending = False
        self._launched_from_tray = False
        self._live_wpm = 65

    @property
    def state(self) -> EngineState:
        return self._engine.state if self._engine is not None else EngineState.IDLE

    def is_running(self) -> bool:
        return self.state in (EngineState.COUNTDOWN, EngineState.TYPING, EngineState.PAUSED)

    def start(self, text: str, settings: TypingSettings, target_hwnd: int | None, *, from_tray: bool) -> bool:
        if self.is_running() or not text:
            return False
        self._launched_from_tray = from_tray
        self._live_wpm = settings.wpm
        self._last_state = EngineState.COUNTDOWN
        self._last_reason = PauseReason.NONE
        self._resume_pending = False
        self._engine = TypingEngine(self._backend_factory(settings.unicode_method), self._bridge)
        self._engine.start(text, settings, target_hwnd)
        return True

    def pause(self) -> None:
        if self._engine is not None:
            self._engine.pause()

    def resume(self) -> None:
        if self._engine is not None:
            self._resume_pending = True
            self._engine.resume()

    def stop(self) -> None:
        if self._engine is not None:
            self._engine.stop()

    def step_wpm(self, delta: int) -> int:
        if self._engine is None:
            return 65
        current = getattr(self, "_live_wpm", 65)
        applied = self._engine.set_live_wpm(current + delta)
        self._live_wpm = applied
        return applied

    def set_live_wpm(self, wpm: int) -> int:
        if self._engine is None:
            return wpm
        applied = self._engine.set_live_wpm(wpm)
        self._live_wpm = applied
        return applied

    def _on_state(self, state: EngineState, reason: PauseReason, countdown: int) -> None:
        if (
            self._resume_pending
            and state == EngineState.PAUSED
            and reason == PauseReason.FOCUS_LOST
            and self._last_state == EngineState.PAUSED
        ):
            self.toastRequested.emit("Couldn't focus the target window.", "warning")
        self._resume_pending = False
        self._last_state = state
        self._last_reason = reason
        self.stateUpdated.emit(state, reason, countdown)

    def _on_progress(self, done: int, total: int, live_wpm: int, eta: float) -> None:
        self._live_wpm = live_wpm
        self.progressUpdated.emit(done, total, live_wpm, eta)

    def _on_finished(self, stats: SessionStats) -> None:
        self._resume_pending = False
        self.sessionEnded.emit(stats, self._launched_from_tray)


def format_summary_message(stats: SessionStats) -> str:
    typo_unit = "typo" if stats.typos_corrected == 1 else "typos"
    return (
        f"Done · {stats.chars_typed:,} chars · "
        f"{format_duration(stats.elapsed_seconds)} · {stats.effective_wpm:.0f} WPM · "
        f"{stats.typos_corrected} {typo_unit} fixed"
    )


def format_stop_message(reason: StopReason) -> tuple[str, str] | None:
    if reason == StopReason.TARGET_UNAVAILABLE:
        return "Target window unavailable — typing stopped.", "warning"
    if reason == StopReason.INPUT_BLOCKED:
        return "Input blocked by Windows UIPI (elevated target window).", "danger"
    if reason == StopReason.ERROR:
        return "Typing stopped due to an input error.", "danger"
    return None
