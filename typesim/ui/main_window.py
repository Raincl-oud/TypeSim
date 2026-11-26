"""Split Workbench and Settings views for TypeSim v2.0."""

from __future__ import annotations

import dataclasses
from typing import Callable

from PyQt6 import sip
from PyQt6.QtCore import (
    QParallelAnimationGroup, QPauseAnimation, QPoint, QPropertyAnimation, QRect, QSequentialAnimationGroup, Qt,
    QTimer, pyqtSignal,
)
from PyQt6.QtGui import QAction, QFont, QKeyEvent, QKeySequence, QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .. import __version__, profiles as prof
from ..config import AppConfig, DEFAULT_HOTKEYS, TypingSettings, load_config, save_config
from ..engine import EngineState, PauseReason, SessionStats
from ..estimator import estimate_session_seconds, format_duration
from ..hotkeys import HotkeyManager, SPI_SETCLIENTAREAANIMATION, display_hotkey
from ..win32_input import WindowInfo, enumerate_windows, is_self_elevated, is_window_elevated
from .bridge import SessionController, format_stop_message, format_summary_message
from .hud import FloatingHUD
from .icons import app_icon, keycap_pixmap, svg_icon, svg_pixmap
from .motion import (
    animate_property, attach_tactile, cleanup_snapshot_overlay, detach_effect, ease_out_curve,
    fresh_opacity_effect, is_reduced_motion, refresh_reduced_motion, should_animate, snapshot_overlay, stop_animation,
)
from .theme import ThemePalette, build_stylesheet, mono_font, resolve_theme, ui_font
from .tray import TrayController
from .widgets import (
    AnimatedIconButton, ChevronComboBox, CollapsibleBanner, HotkeyCaptureButton, KeycapBadge,
    SegmentedControl, SliderRow, ToastBanner, ToggleSwitch,
)


class ComposeEditor(QPlainTextEdit):
    """Word-processor-friendly editor with Ctrl+Y redo, word delete, line delete, and styled menu."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(
            "Paste or write the text you want TypeSim to type...\n\n"
            "Choose a target window below, then press Start or your global hotkey."
        )
        self.setTabChangesFocus(False)
        self.setFont(ui_font(13))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        mods = event.modifiers()
        key = event.key()
        if (mods & Qt.KeyboardModifier.ControlModifier) and key == Qt.Key.Key_Y:
            self.redo()
            return
        if (mods & Qt.KeyboardModifier.ControlModifier) and key == Qt.Key.Key_Backspace:
            self._delete_word(forward=False)
            return
        if (mods & Qt.KeyboardModifier.ControlModifier) and key == Qt.Key.Key_Delete:
            self._delete_word(forward=True)
            return
        if (mods & Qt.KeyboardModifier.ShiftModifier) and key == Qt.Key.Key_Delete:
            self._delete_line()
            return
        super().keyPressEvent(event)

    def _delete_word(self, *, forward: bool) -> None:
        cur = self.textCursor()
        if cur.hasSelection():
            cur.removeSelectedText()
        else:
            mode = QTextCursor.MoveOperation.NextWord if forward else QTextCursor.MoveOperation.PreviousWord
            cur.movePosition(mode, QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()
        self.setTextCursor(cur)

    def _delete_line(self) -> None:
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cur.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        if not cur.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor):
            cur.movePosition(QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor)
        cur.removeSelectedText()
        self.setTextCursor(cur)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        has_sel = self.textCursor().hasSelection()
        has_text = bool(self.toPlainText())
        act_cut = QAction("Cut", menu)
        act_cut.setShortcut(QKeySequence.StandardKey.Cut)
        act_cut.setEnabled(has_sel)
        act_cut.triggered.connect(self.cut)

        act_copy = QAction("Copy", menu)
        act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        act_copy.setEnabled(has_sel)
        act_copy.triggered.connect(self.copy)

        act_paste = QAction("Paste", menu)
        act_paste.setShortcut(QKeySequence.StandardKey.Paste)
        act_paste.setEnabled(self.canPaste())
        act_paste.triggered.connect(self.paste)

        act_del = QAction("Delete", menu)
        act_del.setEnabled(has_sel)
        act_del.triggered.connect(lambda: self.textCursor().removeSelectedText())

        act_all = QAction("Select All", menu)
        act_all.setShortcut(QKeySequence.StandardKey.SelectAll)
        act_all.setEnabled(has_text)
        act_all.triggered.connect(self.selectAll)

        for a in (act_cut, act_copy, act_paste, act_del):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(act_all)
        menu.exec(event.globalPos())


class _PresetButton(QPushButton):
    """Two-line preset button (name + speed descriptor) with clean active state."""

    def __init__(self, name: str, subtitle: str, parent=None) -> None:
        super().__init__(parent)
        self.preset_name = name
        self.setProperty("variant", "preset")
        self.setProperty("active", "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(1)
        self._title = QLabel(name)
        self._title.setFont(ui_font(12, QFont.Weight.DemiBold))
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._sub = QLabel(subtitle)
        self._sub.setFont(mono_font(11, QFont.Weight.Medium))
        self._sub.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._title)
        lay.addWidget(self._sub)

    def sizeHint(self):
        sz = super().sizeHint()
        sz.setHeight(44)
        return sz

    def minimumSizeHint(self):
        sz = super().minimumSizeHint()
        sz.setHeight(44)
        return sz

    def set_active(self, active: bool, p: ThemePalette) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self._title.setStyleSheet(f"color: {p.accent_text if active else p.text_primary}; background: transparent;")
        self._sub.setStyleSheet(f"color: {p.text_secondary}; background: transparent;")


def _divider() -> QFrame:
    line = QFrame()
    line.setProperty("divider", "true")
    return line


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "section")
    return lbl


def _setting_row(title: str, subtitle: str, control: QWidget) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 2, 0, 2)
    lay.setSpacing(12)
    left = QVBoxLayout()
    left.setContentsMargins(0, 0, 0, 0)
    left.setSpacing(2)
    t_lbl = QLabel(title)
    t_lbl.setFont(ui_font(13, QFont.Weight.Medium))
    left.addWidget(t_lbl)
    if subtitle:
        s_lbl = QLabel(subtitle)
        s_lbl.setProperty("role", "muted")
        s_lbl.setWordWrap(True)
        left.addWidget(s_lbl)
    lay.addLayout(left, 1)
    lay.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return row


class MainWindow(QMainWindow):
    """TypeSim v2.0 Split Workbench and Settings application window."""

    themeUpdated = pyqtSignal(str)

    def __init__(
        self,
        *,
        config_path: str | None = None,
        profiles_path: str | None = None,
        hotkey_manager: HotkeyManager | None = None,
        controller: SessionController | None = None,
        tray: TrayController | None = None,
        enumerate_windows_fn: Callable[[], list[WindowInfo]] = enumerate_windows,
        elevation_check_fn: Callable[[int], bool | None] = is_window_elevated,
        self_elevated_fn: Callable[[], bool] = is_self_elevated,
        tray_available: bool | None = None,
    ) -> None:
        super().__init__()
        self._config_path = config_path
        self._profiles_path = profiles_path
        self._enumerate_windows = enumerate_windows_fn
        self._check_elevated = elevation_check_fn
        self._is_self_elevated = self_elevated_fn
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable() if tray_available is None else tray_available
        self._force_quit = False
        self._shutting_down = False
        self._was_visible_on_start = False
        self._card_cascade: QParallelAnimationGroup | None = None
        self._card_rest_pos: dict[QWidget, QPoint] = {}
        self._settings_cards: list[QFrame] = []

        self._config: AppConfig = load_config(self._config_path)
        self._palette: ThemePalette = resolve_theme(self._config.prefs.theme_mode)[1]
        self._hotkey_errors: dict[str, str | None] = {}
        self._switches: list[ToggleSwitch] = []
        self._sliders: list[SliderRow] = []

        self.setWindowTitle("TypeSim")
        self.setWindowIcon(app_icon())
        self.resize(880, 580)
        self.setMinimumSize(740, 500)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._save_now)

        self._setting_coalesce = QTimer(self)
        self._setting_coalesce.setSingleShot(True)
        self._setting_coalesce.setInterval(100)
        self._setting_coalesce.timeout.connect(self._on_system_settings_settled)

        self._controller = controller or SessionController(parent=self)
        self._hotkeys = hotkey_manager or HotkeyManager(parent=self)
        self._hud = FloatingHUD()
        self._tray = tray or TrayController(self)

        self._build_ui()
        self._toast = ToastBanner(self)
        self._wire_signals()
        self._apply_theme(self._config.prefs.theme_mode)
        self._sync_ui_from_config()
        self._refresh_profiles()
        self._refresh_windows()
        self._apply_hotkeys()
        if self._tray_available:
            self._tray.show()

    # ---------------------------------------------------------------- UI build

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("centralRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._stack = QStackedWidget()
        outer.addWidget(self._build_header())
        self._stack.addWidget(self._build_workbench())
        self._stack.addWidget(self._build_settings())
        outer.addWidget(self._stack, 1)

    def _build_header(self) -> QWidget:
        hdr = QWidget()
        hdr.setObjectName("headerBar")
        hdr.setFixedHeight(48)
        lay = QHBoxLayout(hdr)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(10)

        self._brand_icon = QLabel()
        self._brand_icon.setFixedSize(22, 22)
        lay.addWidget(self._brand_icon)

        title = QLabel("TypeSim")
        title.setProperty("role", "title")
        lay.addWidget(title)
        lay.addSpacing(8)

        self._view_tabs = SegmentedControl(["Workbench", "Settings"], initial=0)
        self._view_tabs.setFixedWidth(188)
        self._view_tabs.currentChanged.connect(self._switch_view)
        lay.addWidget(self._view_tabs)

        lay.addStretch(1)

        self._btn_theme = AnimatedIconButton()
        self._btn_theme.setProperty("variant", "icon")
        self._btn_theme.setFixedSize(32, 32)
        self._btn_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_theme.setToolTip("Toggle Light / Dark theme")
        self._btn_theme.clicked.connect(self._toggle_theme_mode)
        attach_tactile(self._btn_theme, radius=7.0, tone="auto")
        lay.addWidget(self._btn_theme)

        self._btn_tray = QPushButton()
        self._btn_tray.setProperty("variant", "icon")
        self._btn_tray.setFixedSize(32, 32)
        self._btn_tray.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_tray.setToolTip("Minimize to system tray")
        self._btn_tray.setVisible(self._tray_available)
        self._btn_tray.clicked.connect(self._minimize_to_tray)
        attach_tactile(self._btn_tray, radius=7.0, tone="auto")
        lay.addWidget(self._btn_tray)

        self._btn_start = QPushButton()
        self._btn_start.setProperty("variant", "primary")
        self._btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_start.setFixedHeight(32)
        cta_lay = QHBoxLayout(self._btn_start)
        cta_lay.setContentsMargins(13, 0, 8, 0)
        cta_lay.setSpacing(7)
        self._start_icon = QLabel()
        self._start_icon.setFixedSize(14, 14)
        self._start_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._start_lbl = QLabel("Start")
        self._start_lbl.setFont(ui_font(12, QFont.Weight.DemiBold))
        self._start_lbl.setStyleSheet("color: #FFFFFF; background: transparent;")
        self._start_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._start_keycap = KeycapBadge("F9")
        self._start_keycap.setFixedHeight(20)
        self._start_keycap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        cta_lay.addWidget(self._start_icon)
        cta_lay.addWidget(self._start_lbl)
        cta_lay.addWidget(self._start_keycap)
        self._btn_start.setMinimumWidth(116)
        self._btn_start.clicked.connect(self._start_typing)
        attach_tactile(self._btn_start, radius=7.0, tone="light", settle_layout=cta_lay)
        lay.addWidget(self._btn_start)
        return hdr

    def _build_workbench(self) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(14)

        # Left column: compose editor, telemetry, target window
        left = QVBoxLayout()
        left.setSpacing(8)
        self._editor = ComposeEditor()
        self._editor.textChanged.connect(self._update_telemetry)
        left.addWidget(self._editor, 1)

        telem = QHBoxLayout()
        telem.setContentsMargins(2, 0, 2, 0)
        self._telem_lbl = QLabel("0 chars · 0 words · ETA --")
        self._telem_lbl.setProperty("role", "mono-muted")
        telem.addWidget(self._telem_lbl)
        telem.addStretch(1)
        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setProperty("variant", "ghost")
        self._btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_clear.setFixedHeight(24)
        self._btn_clear.setEnabled(False)
        self._btn_clear.clicked.connect(self._editor.clear)
        attach_tactile(self._btn_clear, radius=6.0, tone="auto")
        telem.addWidget(self._btn_clear)
        left.addLayout(telem)

        target_row = QHBoxLayout()
        target_row.setSpacing(8)
        target_lbl = QLabel("Target")
        target_lbl.setProperty("role", "section")
        target_row.addWidget(target_lbl)
        self._win_combo = ChevronComboBox()
        self._win_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._win_combo.currentIndexChanged.connect(self._on_target_changed)
        target_row.addWidget(self._win_combo, 1)
        self._btn_refresh_win = AnimatedIconButton()
        self._btn_refresh_win.setProperty("variant", "icon")
        self._btn_refresh_win.setFixedSize(32, 32)
        self._btn_refresh_win.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_refresh_win.setToolTip("Refresh open windows")
        self._btn_refresh_win.clicked.connect(self._on_refresh_windows_clicked)
        attach_tactile(self._btn_refresh_win, radius=7.0, tone="auto")
        target_row.addWidget(self._btn_refresh_win)
        left.addLayout(target_row)

        uipi_row = QWidget()
        uipi_lay = QHBoxLayout(uipi_row)
        uipi_lay.setContentsMargins(2, 0, 2, 0)
        uipi_lay.setSpacing(6)
        self._uipi_icon = QLabel()
        self._uipi_icon.setFixedSize(14, 14)
        self._uipi_lbl = QLabel("Target runs as Administrator — Windows UIPI may block typing.")
        self._uipi_lbl.setProperty("role", "warning")
        uipi_lay.addWidget(self._uipi_icon)
        uipi_lay.addWidget(self._uipi_lbl, 1)
        self._uipi_bar = CollapsibleBanner(uipi_row)
        left.addWidget(self._uipi_bar)
        lay.addLayout(left, 1)

        # Right column: quick control panel
        panel = QFrame()
        panel.setObjectName("controlPanel")
        panel.setFixedWidth(304)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 10, 12, 10)
        pl.setSpacing(5)

        pl.addWidget(_section_label("Presets"))
        grid = QGridLayout()
        grid.setSpacing(6)
        self._preset_btns: dict[str, _PresetButton] = {}
        preset_meta = [
            ("Casual", "45 WPM"),
            ("Natural", "65 WPM"),
            ("Fast", "110 WPM"),
            ("Precision Code", "85 WPM · Code"),
        ]
        for idx, (name, sub) in enumerate(preset_meta):
            btn = _PresetButton(name, sub)
            btn.clicked.connect(lambda _=False, n=name: self._apply_preset(n))
            attach_tactile(btn, radius=8.0, tone="auto", settle_layout=btn.layout())
            self._preset_btns[name] = btn
            grid.addWidget(btn, idx // 2, idx % 2)
        pl.addLayout(grid)

        self._wb_profile_combo = ChevronComboBox()
        self._wb_profile_combo.activated.connect(self._on_workbench_profile_selected)
        pl.addWidget(self._wb_profile_combo)

        pl.addWidget(_divider())
        pl.addWidget(_section_label("Speed"))
        self._wb_wpm = self._make_slider(
            "Words per minute", 10, 400, divisor=1,
            display=lambda v: f"{int(round(v))} WPM",
            on_change=lambda v: self._set_typing("wpm", int(round(v)), debounce=True),
        )
        pl.addWidget(self._wb_wpm)

        pl.addWidget(_divider())
        pl.addWidget(_section_label("Quick Modes"))
        self._wb_coding = self._make_switch(
            lambda on: self._set_typing("coding_mode", on),
            "Disables typos on symbols & indentation and strips IDE auto-indent on newline.\n"
            "IDE auto-closing brackets and quotes remain controlled by your IDE settings.",
        )
        pl.addWidget(self._quick_toggle_row("Coding / IDE-Safe", self._wb_coding))

        self._wb_focus = self._make_switch(
            lambda on: self._set_typing("focus_guard", on),
            "Pauses typing automatically if the target window loses focus.",
        )
        pl.addWidget(self._quick_toggle_row("Focus Guard", self._wb_focus))

        self._wb_burst = self._make_switch(
            lambda on: self._set_typing("burst_mode", on),
            "Types in bursts separated by brief pauses.",
        )
        pl.addWidget(self._quick_toggle_row("Burst Mode", self._wb_burst))

        cd_row = QWidget()
        cd_lay = QHBoxLayout(cd_row)
        cd_lay.setContentsMargins(0, 2, 0, 2)
        cd_lay.setSpacing(6)
        cd_lbl = QLabel("Countdown")
        cd_lbl.setFont(ui_font(13))
        cd_lay.addWidget(cd_lbl, 1)
        self._btn_cd_dec = QPushButton()
        self._btn_cd_dec.setProperty("variant", "icon")
        self._btn_cd_dec.setFixedSize(26, 26)
        self._btn_cd_dec.clicked.connect(lambda: self._step_countdown(-1))
        attach_tactile(self._btn_cd_dec, radius=7.0, tone="auto")
        self._cd_val = QLabel("3s")
        self._cd_val.setFont(mono_font(12, QFont.Weight.Medium))
        self._cd_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cd_val.setFixedWidth(30)
        self._btn_cd_inc = QPushButton()
        self._btn_cd_inc.setProperty("variant", "icon")
        self._btn_cd_inc.setFixedSize(26, 26)
        self._btn_cd_inc.clicked.connect(lambda: self._step_countdown(1))
        attach_tactile(self._btn_cd_inc, radius=7.0, tone="auto")
        cd_lay.addWidget(self._btn_cd_dec)
        cd_lay.addWidget(self._cd_val)
        cd_lay.addWidget(self._btn_cd_inc)
        pl.addWidget(cd_row)

        pl.addStretch(1)
        pl.addWidget(_divider())

        hk_row = QHBoxLayout()
        hk_row.setContentsMargins(0, 2, 0, 0)
        hk_row.setSpacing(6)
        self._legend_badges: dict[str, KeycapBadge] = {}
        for action, label in (("start", "Start"), ("pause", "Pause"), ("stop", "Stop")):
            badge = KeycapBadge()
            self._legend_badges[action] = badge
            lbl = QLabel(label)
            lbl.setProperty("role", "muted")
            hk_row.addWidget(badge)
            hk_row.addWidget(lbl)
            if action != "stop":
                hk_row.addStretch(1)
        pl.addLayout(hk_row)
        lay.addWidget(panel)
        return page

    def _quick_toggle_row(self, title: str, switch: ToggleSwitch) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(8)
        lbl = QLabel(title)
        lbl.setFont(ui_font(13))
        if switch.toolTip():
            row.setToolTip(switch.toolTip())
        lay.addWidget(lbl, 1)
        lay.addWidget(switch)
        return row

    def _build_settings(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        host = QWidget()
        host_lay = QHBoxLayout(host)
        host_lay.setContentsMargins(20, 16, 20, 24)
        host_lay.addStretch(1)

        col = QWidget()
        col.setMaximumWidth(660)
        col.setMinimumWidth(520)
        col.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(14)

        # 1. Realism & Timing
        c1, l1 = self._settings_card("Realism & Timing")
        self._st_wpm = self._make_slider(
            "Typing Speed (WPM)", 10, 400, divisor=1,
            display=lambda v: f"{int(round(v))} WPM",
            on_change=lambda v: self._set_typing("wpm", int(round(v)), debounce=True),
        )
        self._st_var = self._make_slider(
            "Timing Variation", 0.0, 0.60, divisor=100,
            display=lambda v: f"{v * 100:.0f}%",
            on_change=lambda v: self._set_typing("variation", round(v, 3), debounce=True),
        )
        self._st_err = self._make_slider(
            "Typo Rate", 0.0, 0.20, divisor=1000,
            display=lambda v: f"{v * 100:.1f}%",
            on_change=lambda v: self._set_typing("error_rate", round(v, 4), debounce=True),
        )
        self._st_corr = self._make_slider(
            "Correction Delay", 0.02, 2.0, divisor=100,
            display=lambda v: f"{v:.2f}s",
            on_change=lambda v: self._set_typing("error_correction_delay", round(v, 2), debounce=True),
        )
        self._st_think_p = self._make_slider(
            "Thinking Pause Chance", 0.0, 0.20, divisor=1000,
            display=lambda v: f"{v * 100:.1f}%",
            on_change=lambda v: self._set_typing("thinking_pause_chance", round(v, 4), debounce=True),
        )
        self._st_think_min = self._make_slider(
            "Thinking Pause Min", 0.1, 10.0, divisor=10,
            display=lambda v: f"{v:.1f}s",
            on_change=self._on_think_min_changed,
        )
        self._st_think_max = self._make_slider(
            "Thinking Pause Max", 0.1, 10.0, divisor=10,
            display=lambda v: f"{v:.1f}s",
            on_change=self._on_think_max_changed,
        )
        self._st_burst_chars = self._make_slider(
            "Burst Length", 1, 100, divisor=1,
            display=lambda v: f"{int(round(v))} chars",
            on_change=lambda v: self._set_typing("burst_chars", int(round(v)), debounce=True),
        )
        self._st_burst_pause = self._make_slider(
            "Burst Pause", 0.0, 5.0, divisor=20,
            display=lambda v: f"{v:.2f}s",
            on_change=lambda v: self._set_typing("burst_pause", round(v, 2), debounce=True),
        )
        for s in (self._st_wpm, self._st_var, self._st_err, self._st_corr, self._st_think_p,
                  self._st_think_min, self._st_think_max, self._st_burst_chars, self._st_burst_pause):
            l1.addWidget(s)
        cl.addWidget(c1)

        # 2. Input & Coding
        c2, l2 = self._settings_card("Input & Coding")
        self._seg_method = SegmentedControl(["SendInput", "Clipboard"], initial=0)
        self._seg_method.setFixedWidth(200)
        self._seg_method.currentChanged.connect(
            lambda idx: self._set_typing("unicode_method", "clipboard" if idx == 1 else "sendinput")
        )
        l2.addWidget(_setting_row(
            "Unicode Input Method",
            "SendInput injects Unicode & emojis directly without touching your clipboard.",
            self._seg_method,
        ))
        l2.addWidget(_divider())
        self._st_coding = self._make_switch(
            lambda on: self._set_typing("coding_mode", on),
            "IDE auto-closing brackets and quotes remain controlled by your IDE settings.",
        )
        l2.addWidget(_setting_row(
            "Coding / IDE-Safe Mode",
            "Skips typos on symbols and indentation; IDE auto-close brackets stay governed by your IDE.",
            self._st_coding,
        ))
        l2.addWidget(_divider())
        self._st_strip_indent = self._make_switch(lambda on: self._set_typing("strip_ide_auto_indent", on))
        l2.addWidget(_setting_row(
            "Strip IDE auto-indent on newline",
            "Clears editor auto-indent via Shift+Home after Enter (skipped automatically in terminals).",
            self._st_strip_indent,
        ))
        l2.addWidget(_divider())
        self._st_focus_guard = self._make_switch(lambda on: self._set_typing("focus_guard", on))
        l2.addWidget(_setting_row(
            "Focus Guard",
            "Pauses immediately when focus leaves the locked target window.",
            self._st_focus_guard,
        ))
        l2.addWidget(_divider())
        self._st_focus_cd = self._make_slider(
            "Focus & Resume Countdown", 1, 3, divisor=1,
            display=lambda v: f"{int(round(v))}s",
            on_change=lambda v: self._set_typing("focus_resume_countdown", int(round(v)), debounce=True),
        )
        l2.addWidget(self._st_focus_cd)
        cl.addWidget(c2)

        # 3. Typing Profiles
        c3, l3 = self._settings_card("Typing Profiles")
        save_row = QHBoxLayout()
        save_row.setSpacing(8)
        self._prof_name_edit = QLineEdit()
        self._prof_name_edit.setPlaceholderText("New or existing profile name…")
        self._prof_name_edit.setMaxLength(40)
        self._btn_prof_save = QPushButton("Save Profile")
        self._btn_prof_save.clicked.connect(self._save_profile)
        attach_tactile(self._btn_prof_save, radius=7.0, tone="auto")
        save_row.addWidget(self._prof_name_edit, 1)
        save_row.addWidget(self._btn_prof_save)
        l3.addLayout(save_row)

        load_row = QHBoxLayout()
        load_row.setSpacing(8)
        self._prof_combo = ChevronComboBox()
        self._btn_prof_load = QPushButton("Load")
        self._btn_prof_load.clicked.connect(self._load_selected_profile)
        attach_tactile(self._btn_prof_load, radius=7.0, tone="auto")
        self._btn_prof_del = QPushButton("Delete")
        self._btn_prof_del.setProperty("variant", "danger-subtle")
        self._btn_prof_del.clicked.connect(self._delete_selected_profile)
        attach_tactile(self._btn_prof_del, radius=7.0, tone="auto")
        load_row.addWidget(self._prof_combo, 1)
        load_row.addWidget(self._btn_prof_load)
        load_row.addWidget(self._btn_prof_del)
        l3.addLayout(load_row)
        prof_note = QLabel("Custom profiles save all typing, coding, and hotkey settings without changing appearance.")
        prof_note.setProperty("role", "muted")
        prof_note.setWordWrap(True)
        l3.addWidget(prof_note)
        cl.addWidget(c3)

        # 4. Global Hotkeys
        c4, l4 = self._settings_card("Global Hotkeys")
        self._hk_buttons: dict[str, HotkeyCaptureButton] = {}
        self._hk_warn_labels: dict[str, QLabel] = {}
        self._hk_warn_banners: dict[str, CollapsibleBanner] = {}
        for action, title in (("start", "Start / Resume"), ("pause", "Pause / Resume"), ("stop", "Stop / Abort")):
            btn = HotkeyCaptureButton()
            btn.captureStarted.connect(self._hotkeys.suspend)
            btn.captureFinished.connect(self._on_hotkey_capture_finished)
            btn.captureRejected.connect(lambda msg: self._toast.show_toast(msg, "warning"))
            btn.bindingChanged.connect(lambda val, a=action: self._on_hotkey_changed(a, val))
            self._hk_buttons[action] = btn
            l4.addWidget(_setting_row(title, "", btn))
            warn = QLabel()
            warn.setProperty("role", "danger")
            warn.setWordWrap(True)
            banner = CollapsibleBanner(warn)
            self._hk_warn_labels[action] = warn
            self._hk_warn_banners[action] = banner
            l4.addWidget(banner)

        hk_foot = QHBoxLayout()
        hk_hint = QLabel("Click a shortcut button to record a new key or Ctrl/Alt/Shift combo (Esc cancels).")
        hk_hint.setProperty("role", "muted")
        hk_hint.setWordWrap(True)
        hk_foot.addWidget(hk_hint, 1)
        self._btn_hk_reset = QPushButton("Reset Defaults")
        self._btn_hk_reset.clicked.connect(self._reset_hotkeys)
        attach_tactile(self._btn_hk_reset, radius=7.0, tone="auto")
        hk_foot.addWidget(self._btn_hk_reset)
        l4.addLayout(hk_foot)
        cl.addWidget(c4)

        # 5. Application & About
        c5, l5 = self._settings_card("Application & About")
        self._seg_theme = SegmentedControl(["System", "Light", "Dark"], initial=0)
        self._seg_theme.setFixedWidth(210)
        self._seg_theme.currentChanged.connect(self._on_theme_segment_changed)
        l5.addWidget(_setting_row("Appearance", "Follows Windows theme or locks to Light / Dark.", self._seg_theme))
        l5.addWidget(_divider())
        self._st_close_tray = self._make_switch(self._on_close_to_tray_changed)
        l5.addWidget(_setting_row(
            "Close button minimizes to tray",
            "Keep TypeSim in standby when closing the window.",
            self._st_close_tray,
        ))
        l5.addWidget(_divider())
        about = QLabel(f"TypeSim v{__version__} · Native Win32 SendInput & RegisterHotKey · 100% Offline")
        about.setProperty("role", "muted")
        l5.addWidget(about)
        cl.addWidget(c5)

        self._settings_cards = [c1, c2, c3, c4, c5]
        self._settings_scroll = scroll
        scroll.verticalScrollBar().valueChanged.connect(self._cancel_card_cascade)

        host_lay.addWidget(col, 4)
        host_lay.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _settings_card(self, heading: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("settingsCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        lay.addWidget(_section_label(heading))
        return card, lay

    def _make_slider(self, title: str, lo: float, hi: float, *, divisor: float, display, on_change) -> SliderRow:
        row = SliderRow(title, lo, hi, divisor=divisor, display=display)
        row.valueChanged.connect(on_change)
        self._sliders.append(row)
        return row

    def _make_switch(self, on_toggle, tooltip: str = "") -> ToggleSwitch:
        sw = ToggleSwitch()
        if tooltip:
            sw.setToolTip(tooltip)
        sw.toggled.connect(on_toggle)
        self._switches.append(sw)
        return sw

    # ---------------------------------------------------------------- wiring & state

    def _wire_signals(self) -> None:
        self._hotkeys.triggered.connect(self._on_global_hotkey)
        self._hotkeys.settingChanged.connect(self._on_native_setting_change)
        inst = QApplication.instance()
        if inst is not None:
            inst.styleHints().colorSchemeChanged.connect(lambda _s: self._setting_coalesce.start())

        self._controller.stateUpdated.connect(self._on_engine_state)
        self._controller.progressUpdated.connect(self._hud.set_progress)
        self._controller.sessionEnded.connect(self._on_session_ended)
        self._controller.toastRequested.connect(self._toast.show_toast)

        self._hud.pauseClicked.connect(self._controller.pause)
        self._hud.resumeClicked.connect(self._controller.resume)
        self._hud.stopClicked.connect(self._controller.stop)
        self._hud.wpmStep.connect(self._controller.step_wpm)
        self._hud.anchorSnapped.connect(self._on_hud_anchor_snapped)

        self._tray.openRequested.connect(self._restore_window)
        self._tray.startRequested.connect(self._start_typing)
        self._tray.pauseToggleRequested.connect(self._toggle_pause_resume)
        self._tray.stopRequested.connect(self._controller.stop)
        self._tray.quitRequested.connect(self.quit_application)

    def _apply_theme(self, mode: str, *, animate: bool = False) -> None:
        resolved, p = resolve_theme(mode)
        crossfade = animate and self.window().isVisible() and self.centralWidget() is not None
        ov = snapshot_overlay(self.centralWidget()) if crossfade else None
        self._palette = p
        self.setStyleSheet(build_stylesheet(p))
        dpr = self.devicePixelRatioF()
        self._brand_icon.setPixmap(keycap_pixmap(22, dpr))
        self._view_tabs.set_palette(p)
        self._seg_method.set_palette(p)
        self._seg_theme.set_palette(p)
        self._btn_theme.set_pixmap(
            svg_pixmap("sun" if resolved == "dark" else "moon", p.text_primary, 16, dpr),
            animate=animate,
        )
        self._btn_tray.setIcon(svg_icon("tray", p.text_primary, 16))
        self._start_icon.setPixmap(svg_pixmap("play", "#FFFFFF", 13))
        self._start_keycap.set_palette(p, on_accent=True)
        self._btn_refresh_win.set_pixmap(svg_pixmap("refresh", p.text_secondary, 15, dpr), animate=False)
        self._uipi_icon.setPixmap(svg_pixmap("warning", p.state_warning, 14))
        self._btn_cd_dec.setIcon(svg_icon("minus", p.text_primary, 12))
        self._btn_cd_inc.setIcon(svg_icon("plus", p.text_primary, 12))
        self._btn_hk_reset.setIcon(svg_icon("reset", p.text_secondary, 13))
        self._btn_prof_del.setIcon(svg_icon("trash", p.state_danger_text, 13))
        for badge in self._legend_badges.values():
            badge.set_palette(p)
        for sw in self._switches:
            sw.set_palette(p)
        for sl in self._sliders:
            sl.set_palette(p)
        for btn in self._hk_buttons.values():
            btn.set_palette(p)
        for combo in (self._win_combo, self._wb_profile_combo, self._prof_combo):
            combo.set_palette(p)
        self._toast.set_palette(p)
        self._hud.set_palette(p)
        self._tray.set_palette(p)
        self._refresh_preset_buttons()
        if ov is not None:
            eff = fresh_opacity_effect(ov, 1.0)
            animate_property(
                eff, b"opacity", 0.0, 220, ease_out_curve(),
                reduced_duration_ms=120,
                on_finished=lambda: cleanup_snapshot_overlay(self.centralWidget()),
            )
        self.themeUpdated.emit(resolved)

    def _sync_ui_from_config(self, *, animate: bool = False) -> None:
        t = self._config.typing
        pr = self._config.prefs
        self._wb_wpm.set_value(t.wpm, animate=animate)
        self._st_wpm.set_value(t.wpm, animate=animate)
        self._st_var.set_value(t.variation, animate=animate)
        self._st_err.set_value(t.error_rate, animate=animate)
        self._st_corr.set_value(t.error_correction_delay, animate=animate)
        self._st_think_p.set_value(t.thinking_pause_chance, animate=animate)
        self._st_think_min.set_value(t.thinking_pause_min, animate=animate)
        self._st_think_max.set_value(t.thinking_pause_max, animate=animate)
        self._st_burst_chars.set_value(t.burst_chars, animate=animate)
        self._st_burst_pause.set_value(t.burst_pause, animate=animate)
        self._st_focus_cd.set_value(t.focus_resume_countdown, animate=animate)

        self._wb_coding.set_checked_silent(t.coding_mode)
        self._st_coding.set_checked_silent(t.coding_mode)
        self._wb_focus.set_checked_silent(t.focus_guard)
        self._st_focus_guard.set_checked_silent(t.focus_guard)
        self._wb_burst.set_checked_silent(t.burst_mode)
        self._st_strip_indent.set_checked_silent(t.strip_ide_auto_indent)
        self._st_close_tray.set_checked_silent(pr.close_to_tray)

        self._cd_val.setText(f"{t.countdown}s")
        self._seg_method.set_index(1 if t.unicode_method == "clipboard" else 0, animate=False)
        self._seg_theme.set_index({"system": 0, "light": 1, "dark": 2}[pr.theme_mode], animate=False)
        self._hud.set_anchor(pr.hud_anchor)

        for action, attr in (("start", "hotkey_start"), ("pause", "hotkey_pause"), ("stop", "hotkey_stop")):
            val = getattr(t, attr)
            self._hk_buttons[action].set_binding(val)
            self._legend_badges[action].set_key(val)
        self._start_keycap.set_key(t.hotkey_start)
        self._tray.set_hotkeys(t.hotkey_start, t.hotkey_pause, t.hotkey_stop)
        self._refresh_preset_buttons()
        self._update_telemetry()

    def _refresh_preset_buttons(self) -> None:
        for name, btn in self._preset_btns.items():
            btn.set_active(prof.preset_matches(self._config.typing, name), self._palette)

    def _save_now(self) -> None:
        self._save_timer.stop()
        save_config(self._config, self._config_path)

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _set_typing(self, attr: str, value, *, debounce: bool = False) -> None:
        setattr(self._config.typing, attr, value)
        if attr == "wpm":
            self._wb_wpm.set_value(value)
            self._st_wpm.set_value(value)
        elif attr == "coding_mode":
            self._wb_coding.set_checked_silent(value)
            self._st_coding.set_checked_silent(value)
        elif attr == "focus_guard":
            self._wb_focus.set_checked_silent(value)
            self._st_focus_guard.set_checked_silent(value)
        self._refresh_preset_buttons()
        self._update_telemetry()
        if debounce:
            self._schedule_save()
        else:
            self._save_now()

    def _on_think_min_changed(self, v: float) -> None:
        val = round(v, 1)
        self._config.typing.thinking_pause_min = val
        if val > self._config.typing.thinking_pause_max:
            self._config.typing.thinking_pause_max = val
            self._st_think_max.set_value(val)
        self._refresh_preset_buttons()
        self._update_telemetry()
        self._schedule_save()

    def _on_think_max_changed(self, v: float) -> None:
        val = round(v, 1)
        self._config.typing.thinking_pause_max = val
        if val < self._config.typing.thinking_pause_min:
            self._config.typing.thinking_pause_min = val
            self._st_think_min.set_value(val)
        self._refresh_preset_buttons()
        self._update_telemetry()
        self._schedule_save()

    def _step_countdown(self, delta: int) -> None:
        val = min(10, max(0, self._config.typing.countdown + delta))
        self._config.typing.countdown = val
        self._cd_val.setText(f"{val}s")
        self._save_now()

    # ---------------------------------------------------------------- presets & profiles

    def _apply_preset(self, name: str) -> None:
        self._config.typing = prof.apply_preset(self._config.typing, name)
        self._sync_ui_from_config(animate=True)
        self._save_now()

    def _refresh_profiles(self, select: str | None = None) -> None:
        names = prof.list_profiles(self._profiles_path)
        for combo, placeholder in ((self._wb_profile_combo, "Load saved profile…"), (self._prof_combo, "")):
            blocked = combo.blockSignals(True)
            try:
                combo.clear()
                if placeholder:
                    combo.addItem(placeholder, None)
                for n in names:
                    combo.addItem(n, n)
                if select and select in names:
                    combo.setCurrentText(select)
            finally:
                combo.blockSignals(blocked)
        has_profiles = bool(names)
        self._btn_prof_load.setEnabled(has_profiles)
        self._btn_prof_del.setEnabled(has_profiles)

    def _on_workbench_profile_selected(self, idx: int) -> None:
        name = self._wb_profile_combo.itemData(idx)
        if name:
            self._load_profile_by_name(name)

    def _save_profile(self) -> None:
        raw_name = self._prof_name_edit.text()
        try:
            clean = prof.save_profile(raw_name, self._config.typing, self._profiles_path)
        except ValueError as err:
            self._toast.show_toast(str(err), "warning")
            return
        self._prof_name_edit.setText(clean)
        self._refresh_profiles(select=clean)
        self._toast.show_toast(f"Profile “{clean}” saved.", "success")

    def _load_selected_profile(self) -> None:
        name = self._prof_combo.currentData()
        if name:
            self._load_profile_by_name(name)

    def _load_profile_by_name(self, name: str) -> None:
        loaded = prof.load_profile(name, self._profiles_path)
        if loaded is None:
            self._toast.show_toast(f"Profile “{name}” could not be found.", "warning")
            return
        self._config.typing = dataclasses.replace(loaded)
        self._sync_ui_from_config(animate=True)
        self._apply_hotkeys()
        self._save_now()
        self._prof_name_edit.setText(name)
        self._wb_profile_combo.setCurrentText(name)
        self._prof_combo.setCurrentText(name)
        self._toast.show_toast(f"Profile “{name}” loaded.", "success")

    def _delete_selected_profile(self) -> None:
        name = self._prof_combo.currentData()
        if not name:
            return
        if prof.delete_profile(name, self._profiles_path):
            self._refresh_profiles()
            self._toast.show_toast(f"Profile “{name}” deleted.", "info")

    # ---------------------------------------------------------------- view transitions

    def _cancel_card_cascade(self, *_args) -> None:
        group = self._card_cascade
        self._card_cascade = None
        if group is not None and not sip.isdeleted(group):
            group.stop()
            group.deleteLater()
        for card in self._settings_cards:
            detach_effect(card)
            rest = self._card_rest_pos.get(card)
            if rest is not None:
                card.move(rest)
        self._card_rest_pos.clear()

    def _finish_card_cascade(self) -> None:
        self._cancel_card_cascade()

    def _cancel_view_motion(self) -> None:
        self._cancel_card_cascade()
        cleanup_snapshot_overlay(self._stack)
        for i in range(self._stack.count()):
            page = self._stack.widget(i)
            stop_animation(page, b"pos")
            detach_effect(page)
            page.move(0, 0)

    def _finish_incoming_page(self, page: QWidget) -> None:
        stop_animation(page, b"pos")
        detach_effect(page)
        page.move(0, 0)

    def _play_card_cascade(self, direction: int) -> None:
        host = self._settings_scroll.widget()
        if host is not None and host.layout() is not None:
            host.ensurePolished()
            host.layout().activate()
        vp = self._settings_scroll.viewport()
        vp_rect = vp.rect()
        delays = (0, 35, 65, 88, 106)
        offsets = (16, 12, 9, 7, 5)
        group = QParallelAnimationGroup(self)
        self._card_cascade = group
        self._card_rest_pos = {}
        for card, delay, dx in zip(self._settings_cards, delays, offsets):
            mapped = QRect(card.mapTo(vp, QPoint(0, 0)), card.size())
            if not mapped.intersects(vp_rect):
                continue
            rest = card.pos()
            self._card_rest_pos[card] = rest
            eff = fresh_opacity_effect(card, 0.0)
            card.move(rest + QPoint(dx * direction, 0))
            seq = QSequentialAnimationGroup(group)
            if delay > 0:
                seq.addPause(delay)
            par = QParallelAnimationGroup(seq)
            a_pos = QPropertyAnimation(card, b"pos", par)
            a_pos.setDuration(200)
            a_pos.setEasingCurve(ease_out_curve())
            a_pos.setStartValue(card.pos())
            a_pos.setEndValue(rest)
            a_op = QPropertyAnimation(eff, b"opacity", par)
            a_op.setDuration(200)
            a_op.setEasingCurve(ease_out_curve())
            a_op.setStartValue(0.0)
            a_op.setEndValue(1.0)
            par.addAnimation(a_pos)
            par.addAnimation(a_op)
            seq.addAnimation(par)
            group.addAnimation(seq)
        if group.animationCount() == 0:
            self._card_cascade = None
            group.deleteLater()
            return
        group.finished.connect(self._finish_card_cascade)
        group.start()

    def _switch_view(self, idx: int) -> None:
        current = self._stack.currentIndex()
        self._cancel_view_motion()
        if idx == current:
            return
        if not self.window().isVisible():
            self._stack.setCurrentIndex(idx)
            return

        direction = 1 if idx > current else -1
        ov = snapshot_overlay(self._stack)
        self._stack.setCurrentIndex(idx)
        ov.raise_()
        ov_eff = fresh_opacity_effect(ov, 1.0)
        if is_reduced_motion():
            animate_property(
                ov_eff, b"opacity", 0.0, 120, ease_out_curve(),
                reduced_duration_ms=120,
                on_finished=lambda: cleanup_snapshot_overlay(self._stack),
            )
            return

        animate_property(ov, b"pos", QPoint(-16 * direction, 0), 220, ease_out_curve())
        animate_property(
            ov_eff, b"opacity", 0.0, 220, ease_out_curve(),
            on_finished=lambda: cleanup_snapshot_overlay(self._stack),
        )
        if idx == 0:
            page = self._stack.widget(0)
            p_eff = fresh_opacity_effect(page, 0.0)
            page.move(16 * direction, 0)
            animate_property(
                page, b"pos", QPoint(0, 0), 220, ease_out_curve(),
                start_value=page.pos(),
                on_finished=lambda: self._finish_incoming_page(page),
            )
            animate_property(p_eff, b"opacity", 1.0, 220, ease_out_curve(), start_value=0.0)
        else:
            self._play_card_cascade(direction)

    # ---------------------------------------------------------------- target windows & telemetry

    def _update_telemetry(self) -> None:
        text = self._editor.toPlainText()
        chars = len(text)
        words = len(text.split()) if text.strip() else 0
        eta = format_duration(estimate_session_seconds(text, self._config.typing)) if chars else "--"
        self._telem_lbl.setText(f"{chars:,} chars · {words:,} words · ETA {eta}")
        self._btn_clear.setEnabled(chars > 0)

    def _on_refresh_windows_clicked(self) -> None:
        self._btn_refresh_win.spin()
        QTimer.singleShot(0, self._refresh_windows)

    def _refresh_windows(self) -> None:
        current_hwnd = self._win_combo.currentData()
        windows = self._enumerate_windows()
        blocked = self._win_combo.blockSignals(True)
        try:
            self._win_combo.clear()
            self._win_combo.addItem("<Active window when countdown ends>", None)
            for w in windows:
                self._win_combo.addItem(w.label, w.hwnd)
            if current_hwnd is not None:
                idx = self._win_combo.findData(current_hwnd)
                if idx >= 0:
                    self._win_combo.setCurrentIndex(idx)
        finally:
            self._win_combo.blockSignals(blocked)
        self._on_target_changed()

    def _on_target_changed(self) -> None:
        hwnd = self._win_combo.currentData()
        elevated = self._check_elevated(hwnd) if hwnd and not self._is_self_elevated() else None
        self._uipi_bar.set_expanded(elevated is True)

    # ---------------------------------------------------------------- hotkeys & theme

    def _apply_hotkeys(self) -> None:
        t = self._config.typing
        results = self._hotkeys.apply({"start": t.hotkey_start, "pause": t.hotkey_pause, "stop": t.hotkey_stop})
        self._show_hotkey_results(results)

    def _show_hotkey_results(self, results: dict[str, str | None]) -> None:
        self._hotkey_errors = results
        for action, warn_lbl in self._hk_warn_labels.items():
            err = results.get(action)
            banner = self._hk_warn_banners[action]
            if err:
                warn_lbl.setText(err)
                banner.set_expanded(True)
            else:
                banner.set_expanded(False)

    def _on_hotkey_capture_finished(self) -> None:
        self._apply_hotkeys()

    def _on_hotkey_changed(self, action: str, canon: str) -> None:
        attr = f"hotkey_{action}"
        old = getattr(self._config.typing, attr)
        other_vals = {
            getattr(self._config.typing, f"hotkey_{a}") for a in ("start", "pause", "stop") if a != action
        }
        if canon in other_vals:
            self._hk_buttons[action].set_binding(old)
            self._toast.show_toast(f"{display_hotkey(canon)} is already assigned to another action.", "warning")
            return
        setattr(self._config.typing, attr, canon)
        self._sync_ui_from_config()
        self._save_now()

    def _reset_hotkeys(self) -> None:
        for attr, val in DEFAULT_HOTKEYS.items():
            setattr(self._config.typing, attr, val)
        self._sync_ui_from_config()
        self._apply_hotkeys()
        self._save_now()
        self._toast.show_toast("Hotkeys reset to F9 / F10 / F11.", "info")

    def _toggle_theme_mode(self) -> None:
        resolved, _ = resolve_theme(self._config.prefs.theme_mode)
        next_mode = "light" if resolved == "dark" else "dark"
        self._config.prefs.theme_mode = next_mode
        self._seg_theme.set_index({"system": 0, "light": 1, "dark": 2}[next_mode], animate=True)
        self._apply_theme(next_mode, animate=True)
        self._save_now()

    def _on_theme_segment_changed(self, idx: int) -> None:
        mode = ("system", "light", "dark")[idx]
        self._config.prefs.theme_mode = mode
        self._apply_theme(mode, animate=True)
        self._save_now()

    def _on_close_to_tray_changed(self, on: bool) -> None:
        self._config.prefs.close_to_tray = on
        self._save_now()

    def _on_hud_anchor_snapped(self, anchor: str) -> None:
        self._config.prefs.hud_anchor = anchor
        self._save_now()

    def _on_native_setting_change(self, wparam: int, area: str) -> None:
        if area == "ImmersiveColorSet" or wparam == SPI_SETCLIENTAREAANIMATION:
            self._setting_coalesce.start()

    def _on_system_settings_settled(self) -> None:
        refresh_reduced_motion()
        if self._config.prefs.theme_mode == "system":
            self._apply_theme("system", animate=True)

    # ---------------------------------------------------------------- session control

    def _on_global_hotkey(self, action: str) -> None:
        if action == "start":
            if self._controller.state == EngineState.PAUSED:
                self._controller.resume()
            elif not self._controller.is_running():
                self._start_typing()
        elif action == "pause":
            self._toggle_pause_resume()
        elif action == "stop":
            self._controller.stop()

    def _toggle_pause_resume(self) -> None:
        st = self._controller.state
        if st == EngineState.PAUSED:
            self._controller.resume()
        elif st in (EngineState.COUNTDOWN, EngineState.TYPING):
            self._controller.pause()

    def _start_typing(self) -> None:
        if self._controller.is_running():
            return
        text = self._editor.toPlainText()
        if not text.strip():
            if not self.isVisible():
                self._restore_window()
                if self._tray_available:
                    self._tray.showMessage("TypeSim", "Enter or paste text before starting.",
                                           QSystemTrayIcon.MessageIcon.Warning, 3000)
            self._toast.show_toast("Enter or paste text before starting.", "warning")
            self._editor.setFocus()
            return
        target_hwnd = self._win_combo.currentData()
        self._was_visible_on_start = self.isVisible()
        self._hud.set_anchor(self._config.prefs.hud_anchor)
        self._hud.show_session(text, len(text), self._config.typing.wpm)
        if self._was_visible_on_start:
            self._stop_restore_motion()
            self.hide()
        self._controller.start(
            text,
            self._config.typing,
            target_hwnd,
            from_tray=not self._was_visible_on_start,
        )

    def _on_engine_state(self, state: EngineState, reason: PauseReason, countdown: int) -> None:
        self._hud.set_state(state, reason, countdown)
        self._tray.update_state(state)
        self._btn_start.setEnabled(state in (EngineState.IDLE, EngineState.COMPLETED, EngineState.STOPPED))

    def _on_session_ended(self, stats: SessionStats, launched_from_tray: bool) -> None:
        self._tray.update_state(stats.terminal_state)
        self._btn_start.setEnabled(True)

        if stats.terminal_state == EngineState.COMPLETED and launched_from_tray:
            self._hud.show_summary(stats)
            return

        self._hud.hide_animated()
        if self._was_visible_on_start:
            self._restore_window()

        if stats.terminal_state == EngineState.COMPLETED:
            self._toast.show_toast(format_summary_message(stats), "success", duration_ms=4500)
        else:
            info = format_stop_message(stats.reason)
            if info is not None:
                msg, kind = info
                if launched_from_tray and self._tray_available:
                    self._tray.showMessage("TypeSim", msg, QSystemTrayIcon.MessageIcon.Warning, 4000)
                else:
                    self._toast.show_toast(msg, kind, duration_ms=4500)

    def _stop_restore_motion(self) -> None:
        stop_animation(self, b"pos")
        stop_animation(self, b"windowOpacity")
        self.setWindowOpacity(1.0)

    def _minimize_to_tray(self) -> None:
        if self._tray_available:
            self._stop_restore_motion()
            self._cancel_view_motion()
            if self.centralWidget() is not None:
                cleanup_snapshot_overlay(self.centralWidget())
            self.hide()

    def _restore_window(self) -> None:
        self._stop_restore_motion()
        if not self.isVisible() and not is_reduced_motion():
            self.setWindowOpacity(0.0)
            self.showNormal()
            self.raise_()
            self.activateWindow()
            end = self.pos()
            self.move(end + QPoint(0, 8))
            animate_property(self, b"pos", end, 200, ease_out_curve())
            animate_property(self, b"windowOpacity", 1.0, 200, ease_out_curve())
        else:
            self.setWindowOpacity(1.0)
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _shutdown_resources(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._stop_restore_motion()
        self._cancel_view_motion()
        if self.centralWidget() is not None:
            cleanup_snapshot_overlay(self.centralWidget())
        self._save_now()
        self._controller.stop()
        self._hud.hide()
        self._hotkeys.shutdown()
        self._tray.hide()

    def quit_application(self) -> None:
        self._force_quit = True
        self._shutdown_resources()
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ---------------------------------------------------------------- Qt events

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._cancel_view_motion()
        if self.centralWidget() is not None:
            cleanup_snapshot_overlay(self.centralWidget())
        if self._toast.isVisible():
            self._toast.reposition()

    def closeEvent(self, event) -> None:
        if not self._force_quit and self._config.prefs.close_to_tray and self._tray_available:
            event.ignore()
            self._minimize_to_tray()
            return
        self._shutdown_resources()
        event.accept()
        if not self._force_quit:
            app = QApplication.instance()
            if app is not None:
                app.quit()
