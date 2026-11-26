"""System tray icon and live-synced standby menu."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from ..engine import EngineState
from ..hotkeys import display_hotkey
from .icons import tray_app_icon, tray_dot_class
from .theme import DARK_PALETTE, ThemePalette


class TrayController(QSystemTrayIcon):
    """Persistent tray icon for background launch, pause/resume, stop, and exit."""

    openRequested = pyqtSignal()
    startRequested = pyqtSignal()
    pauseToggleRequested = pyqtSignal()
    stopRequested = pyqtSignal()
    quitRequested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._palette = DARK_PALETTE
        self._state = EngineState.IDLE
        self._dot_class = ""
        self._hk_start = "F9"
        self._hk_pause = "F10"
        self._hk_stop = "F11"

        self._menu = QMenu()
        self._act_open = QAction("Open TypeSim", self._menu)
        self._act_start = QAction("Start Typing (F9)", self._menu)
        self._act_pause = QAction("Pause (F10)", self._menu)
        self._act_stop = QAction("Stop (F11)", self._menu)
        self._act_quit = QAction("Quit", self._menu)

        self._act_open.triggered.connect(self.openRequested.emit)
        self._act_start.triggered.connect(self.startRequested.emit)
        self._act_pause.triggered.connect(self.pauseToggleRequested.emit)
        self._act_stop.triggered.connect(self.stopRequested.emit)
        self._act_quit.triggered.connect(self.quitRequested.emit)

        self._menu.addAction(self._act_open)
        self._menu.addSeparator()
        self._menu.addAction(self._act_start)
        self._menu.addAction(self._act_pause)
        self._menu.addAction(self._act_stop)
        self._menu.addSeparator()
        self._menu.addAction(self._act_quit)

        self.setContextMenu(self._menu)
        self.setToolTip("TypeSim")
        self.activated.connect(self._on_activated)
        self.set_palette(DARK_PALETTE)
        self.update_state(EngineState.IDLE)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.openRequested.emit()

    def set_palette(self, p: ThemePalette) -> None:
        self._palette = p
        self._menu.setStyleSheet(
            f"QMenu {{ background: {p.bg_elevated}; color: {p.text_primary}; "
            f"border: 1px solid {p.border}; border-radius: 8px; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 20px 6px 10px; border-radius: 5px; }}"
            f"QMenu::item:selected {{ background: {p.accent_tint}; }}"
            f"QMenu::item:disabled {{ color: {p.text_muted}; }}"
            f"QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 6px; }}"
        )

    def set_hotkeys(self, start: str, pause: str, stop: str) -> None:
        self._hk_start = display_hotkey(start)
        self._hk_pause = display_hotkey(pause)
        self._hk_stop = display_hotkey(stop)
        self.update_state(self._state)

    def update_state(self, state: EngineState) -> None:
        self._state = state
        dot_cls = tray_dot_class(state)
        if dot_cls != self._dot_class:
            self._dot_class = dot_cls
            self.setIcon(tray_app_icon(self._palette, state))
        active = state in (EngineState.COUNTDOWN, EngineState.TYPING, EngineState.PAUSED)
        self._act_start.setEnabled(not active)
        self._act_pause.setEnabled(active)
        self._act_stop.setEnabled(active)
        self._act_start.setText(f"Start Typing ({self._hk_start})")
        self._act_pause.setText(
            f"{'Resume' if state == EngineState.PAUSED else 'Pause'} ({self._hk_pause})"
        )
        self._act_stop.setText(f"Stop ({self._hk_stop})")
