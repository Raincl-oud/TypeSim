"""Reduced-motion-aware QPropertyAnimation, opacity/snapshot lifecycle, and tactile overlay helpers."""

from __future__ import annotations

from typing import Callable

from PyQt6 import sip
from PyQt6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QObject, QPointF, QPropertyAnimation, QRect, QRectF, Qt, pyqtProperty,
)
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QLayout, QPushButton, QWidget

from ..win32_input import system_animations_enabled

_reduced_motion_cache: bool | None = None


def refresh_reduced_motion() -> bool:
    global _reduced_motion_cache
    _reduced_motion_cache = not system_animations_enabled()
    return _reduced_motion_cache


def is_reduced_motion() -> bool:
    if _reduced_motion_cache is None:
        return refresh_reduced_motion()
    return _reduced_motion_cache


def should_animate(w: QWidget) -> bool:
    """Gate visual animations on system animation preference and whether the host window is visible."""
    if sip.isdeleted(w):
        return False
    win = w.window()
    return not is_reduced_motion() and (win is not None and not sip.isdeleted(win) and win.isVisible())


def ease_out_curve() -> QEasingCurve:
    """cubic-bezier(0.23, 1, 0.32, 1) strong ease-out."""
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.23, 1.0), QPointF(0.32, 1.0), QPointF(1.0, 1.0))
    return curve


def ease_in_out_curve() -> QEasingCurve:
    return QEasingCurve(QEasingCurve.Type.InOutCubic)


def _anim_attr_key(prop_name: bytes | str) -> str:
    name = prop_name.decode("ascii", errors="replace") if isinstance(prop_name, (bytes, bytearray)) else str(prop_name)
    return "_anim_" + name


def stop_animation(target: QObject, prop_name: bytes | str) -> bool:
    """Clear, stop, and schedule deletion of a stored property animation on `target`; returns True if it was running."""
    if sip.isdeleted(target):
        return False
    key = _anim_attr_key(prop_name)
    prev: QAbstractAnimation | None = getattr(target, key, None)
    setattr(target, key, None)
    if prev is None or sip.isdeleted(prev):
        return False
    was_running = prev.state() == QAbstractAnimation.State.Running
    prev.stop()
    prev.deleteLater()
    return was_running


def animate_property(
    target: QObject,
    prop_name: bytes,
    end_value,
    duration_ms: int,
    curve: QEasingCurve | None = None,
    *,
    start_value=None,
    reduced_duration_ms: int | None = None,
    on_finished: Callable[[], None] | None = None,
) -> QPropertyAnimation:
    """Start or retarget a QPropertyAnimation on `target`, keeping it interruptible."""
    key = _anim_attr_key(prop_name)
    was_running = stop_animation(target, prop_name)

    dur = reduced_duration_ms if (reduced_duration_ms is not None and is_reduced_motion()) else (
        0 if is_reduced_motion() else duration_ms
    )
    anim = QPropertyAnimation(target, prop_name, target)
    anim.setDuration(max(0, dur))
    anim.setEasingCurve(curve or ease_out_curve())
    if start_value is not None and not was_running:
        anim.setStartValue(start_value)
    else:
        anim.setStartValue(target.property(prop_name.decode("ascii")))
    anim.setEndValue(end_value)
    if on_finished is not None:
        anim.finished.connect(on_finished)
    setattr(target, key, anim)
    anim.start()
    return anim


def detach_effect(w: QWidget, anim: QAbstractAnimation | None = None) -> None:
    """Stop any running animation on `w`'s QGraphicsOpacityEffect before detaching it safely."""
    if anim is not None and not sip.isdeleted(anim):
        anim.stop()
        anim.deleteLater()
    if sip.isdeleted(w):
        return
    eff = w.graphicsEffect()
    if eff is not None and not sip.isdeleted(eff):
        stop_animation(eff, b"opacity")
        w.setGraphicsEffect(None)


def fresh_opacity_effect(w: QWidget, start: float = 1.0) -> QGraphicsOpacityEffect:
    """Stop any previous effect animation and attach a fresh QGraphicsOpacityEffect at `start`."""
    detach_effect(w)
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(start)
    w.setGraphicsEffect(eff)
    return eff


def cleanup_snapshot_overlay(host: QWidget) -> None:
    if sip.isdeleted(host):
        return
    prev: QLabel | None = getattr(host, "_snapshot_overlay", None)
    setattr(host, "_snapshot_overlay", None)
    if prev is not None and not sip.isdeleted(prev):
        stop_animation(prev, b"pos")
        stop_animation(prev, b"opacity")
        detach_effect(prev)
        prev.hide()
        prev.deleteLater()


def snapshot_overlay(host: QWidget, *, rect: QRect | None = None) -> QLabel:
    """Capture `host` first (including any in-flight overlay), clean previous overlay, and mount new one."""
    target_rect = rect or host.rect()
    pm = host.grab(target_rect)
    cleanup_snapshot_overlay(host)
    ov = QLabel(host)
    ov.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    ov.setGeometry(target_rect)
    ov.setPixmap(pm)
    ov.raise_()
    ov.show()
    setattr(host, "_snapshot_overlay", ov)
    return ov


class _TactileOverlay(QWidget):
    """Transparent child overlay painting smooth hover/press tint without shifting geometry."""

    def __init__(self, btn: QPushButton, radius: float, tone: str, settle_layout: QLayout | None) -> None:
        super().__init__(btn)
        self._btn = btn
        self._radius = radius
        self._tone = tone
        self._settle_layout = settle_layout
        self._base_margins = settle_layout.contentsMargins() if settle_layout is not None else None
        self._settled = False
        self._hover = 0.0
        self._press = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setGeometry(btn.rect())
        self.raise_()
        self.show()

    @pyqtProperty(float)
    def hoverProgress(self) -> float:
        return self._hover

    @hoverProgress.setter
    def hoverProgress(self, val: float) -> None:
        self._hover = val
        self.update()

    @pyqtProperty(float)
    def pressProgress(self) -> float:
        return self._press

    @pressProgress.setter
    def pressProgress(self, val: float) -> None:
        self._press = val
        self._sync_settle()
        self.update()

    def _sync_settle(self) -> None:
        if self._settle_layout is None or self._base_margins is None:
            return
        want = self._btn.isEnabled() and self._press >= 0.5
        if want == self._settled:
            return
        self._settled = want
        m = self._base_margins
        if want:
            self._settle_layout.setContentsMargins(m.left(), m.top() + 1, m.right(), max(0, m.bottom() - 1))
        else:
            self._settle_layout.setContentsMargins(m)

    def _is_light_ink(self) -> bool:
        if self._tone == "light":
            return True
        pal = getattr(self._btn.window(), "_palette", None)
        return True if pal is None else (pal.mode == "dark")

    def paintEvent(self, _event) -> None:
        if not self._btn.isEnabled():
            return
        if self._is_light_ink():
            alpha = 0.06 * self._hover + 0.08 * self._press
            color = QColor(255, 255, 255)
        else:
            alpha = 0.04 * self._hover + 0.06 * self._press
            color = QColor(0, 0, 0)
        if alpha <= 0.002:
            return
        color.setAlphaF(min(1.0, alpha))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0), self._radius, self._radius)
        painter.end()


class _TactileFilter(QObject):
    def __init__(self, btn: QPushButton, overlay: _TactileOverlay) -> None:
        super().__init__(btn)
        self._btn = btn
        self._ov = overlay

    def _animate(self, prop: bytes, target: float, dur: int) -> None:
        if sip.isdeleted(self._ov) or sip.isdeleted(self._btn):
            return
        if should_animate(self._btn):
            animate_property(self._ov, prop, target, dur, ease_out_curve())
        else:
            stop_animation(self._ov, prop)
            self._ov.setProperty(prop.decode("ascii"), target)

    def eventFilter(self, obj, event) -> bool:
        if obj is not self._btn:
            return False
        t = event.type()
        if t == QEvent.Type.Resize:
            self._ov.setGeometry(self._btn.rect())
            self._ov.raise_()
        elif t == QEvent.Type.EnabledChange and not self._btn.isEnabled():
            self._animate(b"hoverProgress", 0.0, 0)
            self._animate(b"pressProgress", 0.0, 0)
        elif self._btn.isEnabled():
            if t == QEvent.Type.Enter:
                self._animate(b"hoverProgress", 1.0, 150)
            elif t == QEvent.Type.Leave:
                self._animate(b"hoverProgress", 0.0, 150)
                self._animate(b"pressProgress", 0.0, 160)
            elif t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._animate(b"pressProgress", 1.0, 90)
            elif t == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self._animate(b"pressProgress", 0.0, 160)
        return False


def attach_tactile(
    button: QPushButton,
    *,
    radius: float = 7.0,
    tone: str = "auto",
    settle_layout: QLayout | None = None,
) -> _TactileOverlay:
    """Attach smooth hover/press tint overlay (and optional 1px layout-margin press settle)."""
    ov = _TactileOverlay(button, radius, tone, settle_layout)
    flt = _TactileFilter(button, ov)
    button.installEventFilter(flt)
    setattr(button, "_tactile_overlay", ov)
    setattr(button, "_tactile_filter", flt)
    return ov
