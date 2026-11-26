"""Frameless non-activating Compact Dynamic Pill HUD with Magnetic Edge-Snap and living motion."""

from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import (
    QAbstractAnimation, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer,
    pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from ..engine import EngineState, PauseReason, SessionStats
from ..estimator import format_duration, normalize_text
from ..win32_input import set_no_activate
from .bridge import format_summary_message
from .icons import svg_icon
from .motion import (
    animate_property, attach_tactile, cleanup_snapshot_overlay, detach_effect, ease_in_out_curve,
    ease_out_curve, fresh_opacity_effect, is_reduced_motion, should_animate, snapshot_overlay, stop_animation,
)
from .theme import DARK_PALETTE, ThemePalette, mono_font, ui_font

HUD_WIDTH = 600
HUD_HEIGHT = 64
HUD_RADIUS = 16


def preview_slice(text: str, index: int, before: int = 18, after: int = 30) -> tuple[str, str]:
    """Return `(done, upcoming)` around `index` with newlines as ↵ and tabs as ⇥."""
    norm = normalize_text(text)
    idx = max(0, min(len(norm), index))
    done = norm[max(0, idx - before):idx].replace("\n", "↵").replace("\t", "⇥")
    upcoming = norm[idx:idx + after].replace("\n", "↵").replace("\t", "⇥")
    return done, upcoming


def anchor_pos(anchor: str, hud_size: QSize, avail: QRect, margin: int = 16) -> QPoint:
    """Compute top-left position for one of the 6 screen edge anchors inside `avail`."""
    v, _, h = anchor.partition("-")
    if h == "left":
        x = avail.x() + margin
    elif h == "right":
        x = avail.x() + avail.width() - hud_size.width() - margin
    else:
        x = avail.x() + (avail.width() - hud_size.width()) // 2
    if v == "bottom":
        y = avail.y() + avail.height() - hud_size.height() - margin
    else:
        y = avail.y() + margin
    return QPoint(x, y)


def snap_anchor(hud_rect: QRect, avail: QRect, threshold: int = 24) -> str | None:
    """Return nearest edge anchor if within `threshold` px of top/bottom edge, else None."""
    top_dist = abs(hud_rect.y() - avail.y())
    bottom_dist = abs((hud_rect.y() + hud_rect.height()) - (avail.y() + avail.height()))
    if min(top_dist, bottom_dist) > threshold:
        return None
    v = "top" if top_dist <= bottom_dist else "bottom"
    rel_x = (hud_rect.center().x() - avail.x()) / max(1, avail.width())
    h = "left" if rel_x < (1.0 / 3.0) else "right" if rel_x > (2.0 / 3.0) else "center"
    return f"{v}-{h}"


class _PreviewStrip(QWidget):
    """Single-line monospace live text preview (`done` muted | living caret | `upcoming` primary)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._done = ""
        self._upcoming = ""
        self._has_prefix = False
        self._palette = DARK_PALETTE
        self._caret_color = DARK_PALETTE.accent
        self._typing_active = False
        self._caret_x = 8.0
        self._caret_initialized = False
        self._caret_alpha = 1.0

        self._caret_pulse = QPropertyAnimation(self, b"caretAlpha", self)
        self._caret_pulse.setDuration(1400)
        self._caret_pulse.setStartValue(1.0)
        self._caret_pulse.setKeyValueAt(0.5, 0.35)
        self._caret_pulse.setEndValue(1.0)
        self._caret_pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._caret_pulse.setLoopCount(-1)

        self.setMinimumWidth(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(26)

    @pyqtProperty(float)
    def caretX(self) -> float:
        return self._caret_x

    @caretX.setter
    def caretX(self, val: float) -> None:
        self._caret_x = val
        self.update()

    @pyqtProperty(float)
    def caretAlpha(self) -> float:
        return self._caret_alpha

    @caretAlpha.setter
    def caretAlpha(self, val: float) -> None:
        self._caret_alpha = val
        self.update()

    def set_palette(self, p: ThemePalette, caret_color: str | None = None) -> None:
        self._palette = p
        self._caret_color = caret_color or p.accent
        self.update()

    def set_typing_active(self, active: bool) -> None:
        self._typing_active = active
        if active:
            self._caret_pulse.stop()
            self._caret_alpha = 1.0
            stop_animation(self, b"caretX")
            self._caret_x = self._compute_target_caret_x()[0]
        elif should_animate(self):
            if self._caret_pulse.state() != QAbstractAnimation.State.Running:
                self._caret_pulse.start()
        else:
            self._caret_pulse.stop()
            self._caret_alpha = 1.0
        self.update()

    def stop_motion(self) -> None:
        self._caret_pulse.stop()
        self._caret_alpha = 1.0
        stop_animation(self, b"caretX")

    def _compute_target_caret_x(self) -> tuple[float, str]:
        font = mono_font(12, QFont.Weight.Medium)
        fm = QFontMetrics(font)
        inner = self.rect().adjusted(8, 0, -8, 0)
        prefix_done = ("…" if self._has_prefix else "") + self._done
        max_done_w = max(1, int(inner.width() * 0.42))
        elided_done = fm.elidedText(prefix_done, Qt.TextElideMode.ElideLeft, max_done_w)
        done_w = fm.horizontalAdvance(elided_done)
        cx = float(inner.left() + (done_w + 2 if elided_done else 0))
        return cx, elided_done

    def set_slice(self, done: str, upcoming: str, *, has_prefix: bool = False, glide: bool = False) -> None:
        self._done = done
        self._upcoming = upcoming
        self._has_prefix = has_prefix
        target_cx, _ = self._compute_target_caret_x()
        if glide and not self._typing_active and self._caret_initialized and should_animate(self):
            if abs(target_cx - self._caret_x) > 0.5:
                animate_property(self, b"caretX", target_cx, 110, ease_out_curve())
        else:
            stop_animation(self, b"caretX")
            self._caret_x = target_cx
            self._caret_initialized = True
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        stop_animation(self, b"caretX")
        self._caret_x = self._compute_target_caret_x()[0]

    def paintEvent(self, _event) -> None:
        p = self._palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        painter.setPen(QPen(QColor(p.border), 1.0))
        painter.setBrush(QColor(p.bg_canvas))
        painter.drawRoundedRect(QRectF(0.5, 0.5, rect.width() - 1.0, rect.height() - 1.0), 7.0, 7.0)

        font = mono_font(12, QFont.Weight.Medium)
        painter.setFont(font)
        fm = QFontMetrics(font)
        inner = rect.adjusted(8, 0, -8, 0)
        painter.setClipRect(inner)

        target_cx, elided_done = self._compute_target_caret_x()
        baseline_y = (rect.height() + fm.ascent() - fm.descent()) // 2

        if elided_done:
            painter.setPen(QColor(p.text_muted))
            painter.drawText(inner.left(), baseline_y, elided_done)

        # Spec 0ms guarantee while TYPING: snap caret_x directly to target_cx
        caret_x = target_cx if self._typing_active else self._caret_x
        caret_col = QColor(self._caret_color)
        caret_col.setAlphaF(1.0 if self._typing_active else self._caret_alpha)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(caret_col)
        painter.drawRoundedRect(QRectF(caret_x, 5.0, 2.0, rect.height() - 10.0), 1.0, 1.0)

        up_x = int(round(caret_x)) + 5
        rem_w = max(0, inner.right() - up_x)
        if self._upcoming and rem_w > 4:
            elided_up = fm.elidedText(self._upcoming, Qt.TextElideMode.ElideRight, rem_w)
            painter.setPen(QColor(p.text_primary))
            painter.drawText(up_x, baseline_y, elided_up)
        elif not elided_done and not self._upcoming:
            painter.setPen(QColor(p.text_muted))
            painter.drawText(up_x, baseline_y, "Ready")
        painter.end()


class _StatusDot(QWidget):
    """8px status dot with gentle 1600ms sine breathing pulse strictly while TYPING."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._color = QColor(DARK_PALETTE.state_active)
        self._dot_opacity = 1.0
        self._pulse = QPropertyAnimation(self, b"dotOpacity", self)
        self._pulse.setDuration(1600)
        self._pulse.setStartValue(1.0)
        self._pulse.setKeyValueAt(0.5, 0.42)
        self._pulse.setEndValue(1.0)
        self._pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse.setLoopCount(-1)

    @pyqtProperty(float)
    def dotOpacity(self) -> float:
        return self._dot_opacity

    @dotOpacity.setter
    def dotOpacity(self, val: float) -> None:
        self._dot_opacity = val
        self.update()

    def set_status(self, color: str, *, pulsing: bool) -> None:
        self._color = QColor(color)
        if pulsing and not is_reduced_motion():
            if self._pulse.state() != QPropertyAnimation.State.Running:
                self._pulse.start()
        else:
            self._pulse.stop()
            self._dot_opacity = 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = QColor(self._color)
        c.setAlphaF(self._dot_opacity)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c)
        painter.drawEllipse(QRectF(2.0, 2.0, 8.0, 8.0))
        painter.end()


class FloatingHUD(QWidget):
    """Non-activating Compact Dynamic Pill HUD with edge-snap and integrated living progress."""

    pauseClicked = pyqtSignal()
    resumeClicked = pyqtSignal()
    stopClicked = pyqtSignal()
    wpmStep = pyqtSignal(int)
    anchorSnapped = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(HUD_WIDTH, HUD_HEIGHT)

        self._palette = DARK_PALETTE
        self._anchor = "top-center"
        self._text = ""
        self._total = 0
        self._done = 0
        self._progress = 0.0
        self._display_progress = 0.0
        self._sweep_pos = -0.2
        self._sweeping = False
        self._state = EngineState.IDLE
        self._reason = PauseReason.NONE
        self._summary_mode = False
        self._mode_key = "normal"
        self._last_countdown = -1
        self._no_activate_applied = False
        self._drag_offset: QPoint | None = None
        self._border_color = QColor(self._palette.hud_border)
        self._bar_color = QColor(self._palette.accent)

        self._summary_timer = QTimer(self)
        self._summary_timer.setSingleShot(True)
        self._summary_timer.timeout.connect(self.hide_animated)

        self._build_ui()
        self.set_palette(self._palette)

    def _build_ui(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 12, 13)
        row.setSpacing(8)

        self._dot = _StatusDot(self)
        row.addWidget(self._dot)

        self._status_lbl = QLabel("Starting")
        self._status_lbl.setFont(ui_font(12, QFont.Weight.DemiBold))
        self._status_lbl.setMinimumWidth(74)
        row.addWidget(self._status_lbl)

        self._preview = _PreviewStrip(self)
        row.addWidget(self._preview, 1)

        self._eta_lbl = QLabel("--")
        self._eta_lbl.setFont(mono_font(11, QFont.Weight.Medium))
        self._eta_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._eta_lbl.setFixedWidth(42)
        row.addWidget(self._eta_lbl)

        self._btn_minus = self._make_btn("", 24, 24, self._on_minus, "Decrease WPM (-10)")
        row.addWidget(self._btn_minus)

        self._wpm_lbl = QLabel("65 WPM")
        self._wpm_lbl.setFont(mono_font(11, QFont.Weight.Medium))
        self._wpm_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._wpm_lbl.setFixedWidth(52)
        row.addWidget(self._wpm_lbl)

        self._btn_plus = self._make_btn("", 24, 24, self._on_plus, "Increase WPM (+10)")
        row.addWidget(self._btn_plus)

        self._btn_primary = self._make_btn("Pause", 0, 28, self._on_primary, "Pause or resume typing")
        self._btn_primary.setMinimumWidth(68)
        row.addWidget(self._btn_primary)

        self._btn_stop = self._make_btn("", 28, 28, self.stopClicked.emit, "Stop typing")
        row.addWidget(self._btn_stop)

        for b in (self._btn_minus, self._btn_plus, self._btn_primary, self._btn_stop):
            attach_tactile(b, radius=6.0, tone="auto")

    def _make_btn(self, text: str, w: int, h: int, slot, tip: str) -> QPushButton:
        btn = QPushButton(text, self)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tip)
        if w:
            btn.setFixedSize(w, h)
        else:
            btn.setFixedHeight(h)
        btn.clicked.connect(slot)
        return btn

    def _on_minus(self) -> None:
        self.wpmStep.emit(-10)

    def _on_plus(self) -> None:
        self.wpmStep.emit(10)

    def _on_primary(self) -> None:
        if self._state == EngineState.PAUSED:
            self.resumeClicked.emit()
        else:
            self.pauseClicked.emit()

    @pyqtProperty(QColor)
    def borderColor(self) -> QColor:
        return self._border_color

    @borderColor.setter
    def borderColor(self, c: QColor) -> None:
        self._border_color = c
        self.update()

    @pyqtProperty(float)
    def displayProgress(self) -> float:
        return self._display_progress

    @displayProgress.setter
    def displayProgress(self, val: float) -> None:
        self._display_progress = val
        self.update()

    @pyqtProperty(float)
    def sweepPos(self) -> float:
        return self._sweep_pos

    @sweepPos.setter
    def sweepPos(self, val: float) -> None:
        self._sweep_pos = val
        self.update()

    def set_anchor(self, anchor: str) -> None:
        self._anchor = anchor

    def set_palette(self, p: ThemePalette) -> None:
        self._palette = p
        self._status_lbl.setStyleSheet(f"color: {p.text_primary}; background: transparent;")
        self._eta_lbl.setStyleSheet(f"color: {p.text_secondary}; background: transparent;")
        self._wpm_lbl.setStyleSheet(f"color: {p.text_primary}; background: transparent;")
        self._btn_minus.setIcon(svg_icon("minus", p.text_primary, 12))
        self._btn_plus.setIcon(svg_icon("plus", p.text_primary, 12))
        self._btn_stop.setIcon(svg_icon("stop", p.state_danger_text, 12))
        step_ss = (
            f"QPushButton {{ background: {p.bg_subtle}; color: {p.text_primary}; "
            f"border: 1px solid {p.border}; border-radius: 6px; padding: 0; }}"
        )
        self._btn_minus.setStyleSheet(step_ss)
        self._btn_plus.setStyleSheet(step_ss)
        self._btn_stop.setStyleSheet(
            f"QPushButton {{ background: {p.state_danger_tint}; border: 1px solid {p.border}; "
            "border-radius: 6px; padding: 0; }}"
        )
        self._refresh_visual_state()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._no_activate_applied and QGuiApplication.platformName() == "windows":
            set_no_activate(int(self.winId()))
            self._no_activate_applied = True

    def _current_avail(self) -> QRect:
        screen = QGuiApplication.screenAt(self.geometry().center()) if self.isVisible() else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)

    def _compute_mode_key(self) -> str:
        if self._summary_mode:
            return "summary"
        if self._state == EngineState.PAUSED and self._reason == PauseReason.FOCUS_LOST:
            return "focus_lost"
        return "normal"

    def _begin_mode_crossfade(self, next_key: str) -> bool:
        if next_key == self._mode_key:
            return False
        self._mode_key = next_key
        if not should_animate(self):
            return False
        ov = snapshot_overlay(self)
        eff = fresh_opacity_effect(ov, 1.0)
        animate_property(
            eff, b"opacity", 0.0, 180, ease_out_curve(),
            on_finished=lambda: cleanup_snapshot_overlay(self),
        )
        return True

    def _stop_progress_and_sweep(self) -> None:
        stop_animation(self, b"displayProgress")
        stop_animation(self, b"sweepPos")
        self._sweeping = False
        self._sweep_pos = -0.2

    def show_session(self, text: str, total: int, live_wpm: int) -> None:
        self._summary_timer.stop()
        self._stop_progress_and_sweep()
        detach_effect(self._status_lbl)
        self._last_countdown = -1

        was_visible = self.isVisible()
        ov_started = False
        if was_visible and self._mode_key != "normal":
            ov_started = self._begin_mode_crossfade("normal")
        else:
            self._mode_key = "normal"

        self._summary_mode = False
        self._state = EngineState.COUNTDOWN
        self._reason = PauseReason.NONE
        self._status_lbl.setText("Starting")
        self._btn_primary.setText("Pause")
        self._text = normalize_text(text)
        self._total = total
        self._done = 0
        self._progress = 0.0
        self._display_progress = 0.0
        self._wpm_lbl.setText(f"{live_wpm} WPM")
        self._eta_lbl.setText("--")
        self._set_controls_visible(True)
        done, upcoming = preview_slice(self._text, 0)
        self._preview.set_typing_active(False)
        self._preview.set_slice(done, upcoming, has_prefix=False, glide=False)
        self._refresh_visual_state()
        if ov_started:
            ov = getattr(self, "_snapshot_overlay", None)
            if ov is not None and not sip.isdeleted(ov):
                ov.raise_()

        avail = self._current_avail()
        end_pos = anchor_pos(self._anchor, self.size(), avail)
        offset_y = -14 if self._anchor.startswith("top") else 14
        if not was_visible:
            self.setWindowOpacity(0.0)
            self.move(end_pos.x(), end_pos.y() + offset_y if not is_reduced_motion() else end_pos.y())
            self.show()
        if not is_reduced_motion():
            animate_property(self, b"pos", end_pos, 220, ease_out_curve())
        else:
            stop_animation(self, b"pos")
            self.move(end_pos)
        animate_property(self, b"windowOpacity", 0.96, 220, ease_out_curve(), reduced_duration_ms=120)

    def _set_controls_visible(self, visible: bool) -> None:
        for w in (self._preview, self._eta_lbl, self._btn_minus, self._wpm_lbl,
                  self._btn_plus, self._btn_primary, self._btn_stop):
            w.setVisible(visible)

    def set_state(self, state: EngineState, reason: PauseReason, countdown: int) -> None:
        prev_state = self._state
        self._state = state
        self._reason = reason
        if self._summary_mode:
            return

        next_key = self._compute_mode_key()
        ov_started = self._begin_mode_crossfade(next_key)

        if state == EngineState.COUNTDOWN:
            self._status_lbl.setText(f"Starting {countdown}s" if countdown > 0 else "Starting")
            self._btn_primary.setText("Pause")
            self._preview.set_typing_active(False)
            if should_animate(self) and countdown > 0 and countdown != self._last_countdown:
                eff = fresh_opacity_effect(self._status_lbl, 0.55)
                animate_property(
                    eff, b"opacity", 1.0, 160, ease_out_curve(),
                    start_value=0.55,
                    on_finished=lambda: detach_effect(self._status_lbl),
                )
            self._last_countdown = countdown
        else:
            self._last_countdown = -1
            detach_effect(self._status_lbl)
            if state == EngineState.TYPING:
                self._status_lbl.setText("Typing")
                self._btn_primary.setText("Pause")
                self._preview.set_typing_active(True)
            elif state == EngineState.PAUSED:
                self._preview.set_typing_active(False)
                if reason == PauseReason.FOCUS_LOST:
                    self._status_lbl.setText("Focus Lost")
                    self._btn_primary.setText("Focus && Resume")
                else:
                    self._status_lbl.setText("Paused")
                    self._btn_primary.setText("Resume")
            else:
                self._preview.set_typing_active(False)

        self._refresh_visual_state()
        if prev_state != state and not self._preview._typing_active:
            s_done, s_up = preview_slice(self._text, self._done)
            self._preview.set_slice(s_done, s_up, has_prefix=(self._done > 18), glide=True)
        if ov_started:
            ov = getattr(self, "_snapshot_overlay", None)
            if ov is not None and not sip.isdeleted(ov):
                ov.raise_()

    def _refresh_visual_state(self) -> None:
        p = self._palette
        tact = getattr(self._btn_primary, "_tactile_overlay", None)
        if self._summary_mode:
            target_border = QColor(p.state_active)
            self._bar_color = QColor(p.state_active)
            self._dot.set_status(p.state_active, pulsing=False)
            self._status_lbl.setStyleSheet(f"color: {p.state_active_text}; background: transparent;")
        elif self._state == EngineState.PAUSED and self._reason == PauseReason.FOCUS_LOST:
            target_border = QColor(p.state_warning)
            self._bar_color = QColor(p.state_warning)
            self._dot.set_status(p.state_warning, pulsing=False)
            self._status_lbl.setStyleSheet(f"color: {p.state_warning_text}; background: transparent;")
            self._preview.set_palette(p, p.state_warning)
            self._btn_primary.setIcon(svg_icon("play", p.on_warning, 12))
            self._btn_primary.setMinimumWidth(134)
            self._btn_primary.setStyleSheet(
                f"QPushButton {{ background: {p.btn_warning}; color: {p.on_warning}; "
                f"border: 1px solid {p.btn_warning}; border-radius: 6px; padding: 0 10px; "
                "font-size: 12px; font-weight: 600; }"
            )
            if tact is not None:
                tact._tone = "light" if p.mode == "light" else "auto"
        elif self._state == EngineState.PAUSED:
            target_border = QColor(p.hud_border)
            self._bar_color = QColor(p.state_warning)
            self._dot.set_status(p.state_warning, pulsing=False)
            self._status_lbl.setStyleSheet(f"color: {p.text_primary}; background: transparent;")
            self._preview.set_palette(p, p.state_warning)
            self._btn_primary.setIcon(svg_icon("play", p.on_accent, 12))
            self._btn_primary.setMinimumWidth(78)
            self._btn_primary.setStyleSheet(
                f"QPushButton {{ background: {p.btn_primary}; color: {p.on_accent}; "
                f"border: 1px solid {p.btn_primary}; border-radius: 6px; padding: 0 10px; "
                "font-size: 12px; font-weight: 600; }"
            )
            if tact is not None:
                tact._tone = "light"
        elif self._state == EngineState.COUNTDOWN:
            target_border = QColor(p.hud_border)
            self._bar_color = QColor(p.state_warning)
            self._dot.set_status(p.state_warning, pulsing=False)
            self._status_lbl.setStyleSheet(f"color: {p.text_primary}; background: transparent;")
            self._preview.set_palette(p, p.state_warning)
            self._set_neutral_primary_btn()
        else:
            target_border = QColor(p.hud_border)
            self._bar_color = QColor(p.accent)
            self._dot.set_status(p.state_active, pulsing=(self._state == EngineState.TYPING))
            self._status_lbl.setStyleSheet(f"color: {p.text_primary}; background: transparent;")
            self._preview.set_palette(p, p.accent)
            self._set_neutral_primary_btn()

        if self.isVisible():
            animate_property(self, b"borderColor", target_border, 180, ease_out_curve(), reduced_duration_ms=0)
        else:
            stop_animation(self, b"borderColor")
            self._border_color = target_border
            self.update()

    def _set_neutral_primary_btn(self) -> None:
        p = self._palette
        tact = getattr(self._btn_primary, "_tactile_overlay", None)
        if tact is not None:
            tact._tone = "auto"
        self._btn_primary.setIcon(svg_icon("pause", p.text_primary, 12))
        self._btn_primary.setMinimumWidth(68)
        self._btn_primary.setStyleSheet(
            f"QPushButton {{ background: {p.bg_subtle}; color: {p.text_primary}; "
            f"border: 1px solid {p.border}; border-radius: 6px; padding: 0 10px; "
            "font-size: 12px; font-weight: 600; }"
        )

    def set_progress(self, done: int, total: int, live_wpm: int, eta_seconds: float) -> None:
        self._done = done
        self._total = total
        self._progress = (done / total) if total > 0 else 1.0
        self._wpm_lbl.setText(f"{live_wpm} WPM")
        self._eta_lbl.setText(format_duration(eta_seconds) if total > 0 and done < total else "0:00")
        s_done, s_up = preview_slice(self._text, done)
        self._preview.set_slice(s_done, s_up, has_prefix=(done > 18), glide=False)
        if should_animate(self):
            animate_property(self, b"displayProgress", self._progress, 160, ease_out_curve())
        else:
            stop_animation(self, b"displayProgress")
            self._display_progress = self._progress
            self.update()

    def _finish_sweep(self) -> None:
        self._sweeping = False
        self.update()

    def show_summary(self, stats: SessionStats) -> None:
        self._stop_progress_and_sweep()
        detach_effect(self._status_lbl)
        self._preview.stop_motion()
        ov_started = self._begin_mode_crossfade("summary")

        self._summary_mode = True
        self._progress = 1.0
        self._display_progress = 1.0
        self._set_controls_visible(False)
        self._status_lbl.setText(format_summary_message(stats))
        self._refresh_visual_state()
        if ov_started:
            ov = getattr(self, "_snapshot_overlay", None)
            if ov is not None and not sip.isdeleted(ov):
                ov.raise_()

        if not self.isVisible():
            avail = self._current_avail()
            self.move(anchor_pos(self._anchor, self.size(), avail))
            self.setWindowOpacity(0.96)
            self.show()

        if should_animate(self):
            self._sweeping = True
            self._sweep_pos = -0.15
            animate_property(
                self, b"sweepPos", 1.15, 420, ease_in_out_curve(),
                start_value=-0.15, on_finished=self._finish_sweep,
            )
        else:
            self._sweeping = False
        self._summary_timer.start(3000)

    def hide_animated(self) -> None:
        self._summary_timer.stop()
        self._dot.set_status(self._palette.state_active, pulsing=False)
        self._preview.stop_motion()
        self._stop_progress_and_sweep()
        detach_effect(self._status_lbl)
        cleanup_snapshot_overlay(self)
        if not self.isVisible():
            stop_animation(self, b"pos")
            stop_animation(self, b"windowOpacity")
            return
        offset_y = -14 if self.y() < self._current_avail().center().y() else 14
        if not is_reduced_motion():
            animate_property(self, b"pos", QPoint(self.x(), self.y() + offset_y), 220, ease_out_curve())
        else:
            stop_animation(self, b"pos")
        animate_property(
            self,
            b"windowOpacity",
            0.0,
            220,
            ease_out_curve(),
            reduced_duration_ms=120,
            on_finished=self._finish_hide,
        )

    def _finish_hide(self) -> None:
        if self.windowOpacity() <= 0.02:
            self.hide()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            stop_animation(self, b"pos")
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            avail = self._current_avail()
            snapped = snap_anchor(self.geometry(), avail)
            if snapped is not None:
                self._anchor = snapped
                target = anchor_pos(snapped, self.size(), avail)
                animate_property(self, b"pos", target, 220, ease_out_curve())
                self.anchorSnapped.emit(snapped)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        p = self._palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        clip = QPainterPath()
        clip.addRoundedRect(rect, HUD_RADIUS, HUD_RADIUS)

        painter.save()
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(p.bg_elevated))

        # Integrated 3px smooth progress footer + optional completion shimmer sweep.
        bar_y = self.height() - 3.5
        painter.fillRect(QRectF(0.0, bar_y, float(self.width()), 3.5), QColor(p.bg_subtle))
        fill_w = self.width() * min(1.0, max(0.0, self._display_progress))
        if fill_w > 0:
            fill_rect = QRectF(0.0, bar_y, fill_w, 3.5)
            painter.fillRect(fill_rect, self._bar_color)
            if self._sweeping:
                cx = self._sweep_pos * self.width()
                band_w = 72.0
                shimmer = QLinearGradient(QPointF(cx - band_w / 2.0, bar_y), QPointF(cx + band_w / 2.0, bar_y))
                shimmer.setColorAt(0.0, QColor(255, 255, 255, 0))
                shimmer.setColorAt(0.5, QColor(255, 255, 255, 115))
                shimmer.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.fillRect(fill_rect, shimmer)
        painter.restore()

        painter.setPen(QPen(self._border_color, 1.25))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, HUD_RADIUS, HUD_RADIUS)
        painter.end()
