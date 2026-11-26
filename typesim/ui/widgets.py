"""Shared UI controls: AnimatedIconButton, CollapsibleBanner, SliderRow, SegmentedControl, HotkeyCaptureButton, ToastBanner."""

from __future__ import annotations

import math
from typing import Callable

from PyQt6 import sip
from PyQt6.QtCore import (
    QAbstractAnimation, QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer, pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractButton, QComboBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QSlider, QStyle, QStyleOptionSlider, QStylePainter, QVBoxLayout, QWidget,
)

from ..hotkeys import HotkeyError, display_hotkey, format_hotkey, parse_hotkey
from .icons import svg_pixmap
from .motion import (
    animate_property, detach_effect, ease_in_out_curve, ease_out_curve, fresh_opacity_effect,
    is_reduced_motion, should_animate, stop_animation,
)
from .theme import DARK_PALETTE, ThemePalette, mono_font, ui_font

_QT_KEY_NAMES = {
    Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end", Qt.Key.Key_Insert: "insert", Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_PageUp: "pageup", Qt.Key.Key_PageDown: "pagedown", Qt.Key.Key_Pause: "pause",
    Qt.Key.Key_ScrollLock: "scrolllock", Qt.Key.Key_Space: "space", Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter", Qt.Key.Key_Tab: "tab", Qt.Key.Key_Backspace: "backspace",
}
_MOD_ONLY_KEYS = {
    Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr, Qt.Key.Key_Super_L, Qt.Key.Key_Super_R,
}
_QWIDGETSIZE_MAX = 16777215


def qt_key_event_to_hotkey(key: int, modifiers: Qt.KeyboardModifier) -> str | None:
    """Convert a Qt key press to a canonical hotkey string, or None for bare modifier presses."""
    if key in _MOD_ONLY_KEYS:
        return None
    parts: list[str] = []
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        parts.append("win")
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        parts.append("ctrl")
    if modifiers & Qt.KeyboardModifier.AltModifier:
        parts.append("alt")
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        parts.append("shift")
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        parts.append(f"f{key - Qt.Key.Key_F1 + 1}")
    elif key in _QT_KEY_NAMES:
        parts.append(_QT_KEY_NAMES[key])
    elif Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        parts.append(chr(ord("a") + (key - Qt.Key.Key_A)))
    elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        parts.append(chr(ord("0") + (key - Qt.Key.Key_0)))
    else:
        return ""
    return "+".join(parts)


class AnimatedIconButton(QPushButton):
    """Icon button supporting smooth 90-deg swap morph and 360-deg click spin."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pm: QPixmap | None = None
        self._old_pm: QPixmap | None = None
        self._swap = 1.0
        self._angle = 0.0

    @pyqtProperty(float)
    def swapProgress(self) -> float:
        return self._swap

    @swapProgress.setter
    def swapProgress(self, val: float) -> None:
        self._swap = val
        self.update()

    @pyqtProperty(float)
    def spinAngle(self) -> float:
        return self._angle

    @spinAngle.setter
    def spinAngle(self, val: float) -> None:
        self._angle = val
        self.update()

    def set_pixmap(self, pm: QPixmap, *, animate: bool = False) -> None:
        if animate and should_animate(self) and self._pm is not None:
            self._old_pm = self._pm
            self._pm = pm
            self._swap = 0.0
            animate_property(
                self, b"swapProgress", 1.0, 240, ease_out_curve(),
                start_value=0.0, on_finished=self._finish_swap,
            )
        else:
            stop_animation(self, b"swapProgress")
            self._old_pm = None
            self._pm = pm
            self._swap = 1.0
            self.update()

    def _finish_swap(self) -> None:
        self._old_pm = None
        self._swap = 1.0
        self.update()

    def spin(self) -> None:
        if not should_animate(self):
            return
        cur = self._angle
        target = (math.floor(cur / 360.0) + 1) * 360.0
        animate_property(self, b"spinAngle", target, 260, ease_out_curve(), on_finished=self._finish_spin)

    def _finish_spin(self) -> None:
        self._angle = 0.0
        self.update()

    def _draw_rotated(self, painter: QPainter, pm: QPixmap, deg: float, opacity: float) -> None:
        if opacity <= 0.01:
            return
        dpr = max(1.0, pm.devicePixelRatio())
        w, h = pm.width() / dpr, pm.height() / dpr
        painter.save()
        painter.setOpacity(opacity)
        painter.translate(self.width() / 2.0, self.height() / 2.0)
        if abs(deg) > 0.01:
            painter.rotate(deg)
        painter.drawPixmap(QRectF(-w / 2.0, -h / 2.0, w, h), pm, QRectF(0, 0, pm.width(), pm.height()))
        painter.restore()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._pm is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._old_pm is not None and self._swap < 0.999:
            p = self._swap
            self._draw_rotated(painter, self._old_pm, 90.0 * p, 1.0 - p)
            self._draw_rotated(painter, self._pm, -90.0 * (1.0 - p), p)
        else:
            self._draw_rotated(painter, self._pm, self._angle, 1.0)
        painter.end()


class ChevronComboBox(QComboBox):
    """QComboBox with a crisp theme-tinted vector chevron on the right."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._palette = DARK_PALETTE

    def set_palette(self, p: ThemePalette) -> None:
        self._palette = p
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(self._palette.text_secondary), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = self.width() - 14.0
        cy = self.height() / 2.0
        painter.drawLine(QPoint(int(cx - 4), int(cy - 2)), QPoint(int(cx), int(cy + 2)))
        painter.drawLine(QPoint(int(cx), int(cy + 2)), QPoint(int(cx + 4), int(cy - 2)))
        painter.end()


class KeycapBadge(QLabel):
    """Monospace keycap pill for shortcut legends and CTA inline hints."""

    def __init__(self, key_text: str = "", parent=None) -> None:
        super().__init__(key_text, parent)
        self.setFont(mono_font(11, QFont.Weight.Medium))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._on_accent = False
        self.set_palette(DARK_PALETTE)

    def set_key(self, canonical: str) -> None:
        self.setText(display_hotkey(canonical))

    def set_palette(self, p: ThemePalette, *, on_accent: bool = False) -> None:
        self._on_accent = on_accent
        if on_accent:
            self.setStyleSheet(
                "QLabel { background: rgba(255, 255, 255, 0.16); color: #FFFFFF; "
                "border: 1px solid rgba(255, 255, 255, 0.28); border-radius: 4px; "
                "padding: 1px 6px; font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 11px; }"
            )
        else:
            self.setStyleSheet(
                f"QLabel {{ background: {p.bg_subtle}; color: {p.text_secondary}; "
                f"border: 1px solid {p.border}; border-radius: 4px; "
                "padding: 2px 6px; font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 11px; }"
            )


class ToggleSwitch(QAbstractButton):
    """Custom pill switch with smooth retargetable thumb transition."""

    def __init__(self, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(38, 22)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._thumb_pos = 1.0 if checked else 0.0
        self._palette = DARK_PALETTE
        self._hovered = False
        self.toggled.connect(self._animate_toggle)

    @pyqtProperty(float)
    def thumbPos(self) -> float:
        return self._thumb_pos

    @thumbPos.setter
    def thumbPos(self, val: float) -> None:
        self._thumb_pos = val
        self.update()

    def set_palette(self, p: ThemePalette) -> None:
        self._palette = p
        self.update()

    def set_checked_silent(self, checked: bool) -> None:
        stop_animation(self, b"thumbPos")
        blocked = self.blockSignals(True)
        try:
            self.setChecked(checked)
        finally:
            self.blockSignals(blocked)
        self._thumb_pos = 1.0 if checked else 0.0
        self.update()

    def _animate_toggle(self, checked: bool) -> None:
        animate_property(self, b"thumbPos", 1.0 if checked else 0.0, 170, ease_out_curve())

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = self._palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QRectF(1.0, 1.0, 36.0, 20.0)
        if self.isChecked():
            fill = QColor(p.accent_hover if self._hovered else p.accent)
            border = fill
        else:
            fill = QColor(p.bg_hover if self._hovered else p.bg_subtle)
            border = QColor(p.border_strong)
        if self.hasFocus():
            painter.setPen(QPen(QColor(p.accent), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, 37.0, 21.0), 10.5, 10.5)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(fill)
        painter.drawRoundedRect(track, 10.0, 10.0)

        x = 4.0 + self._thumb_pos * 16.0
        thumb = QColor("#FFFFFF") if self.isChecked() else QColor(p.text_secondary if p.mode == "light" else p.text_primary)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(thumb)
        painter.drawEllipse(QRectF(x, 4.0, 14.0, 14.0))
        painter.end()


class _NoWheelSlider(QSlider):
    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class _GlideSlider(_NoWheelSlider):
    """QSlider that smoothly glides visual handle/fill on preset loads while keeping value() immediate."""

    def __init__(self, orientation: Qt.Orientation, parent=None) -> None:
        super().__init__(orientation, parent)
        self._gliding = False
        self._visual = 0.0

    @pyqtProperty(float)
    def visualPos(self) -> float:
        return self._visual

    @visualPos.setter
    def visualPos(self, val: float) -> None:
        self._visual = val
        self.update()

    def stop_glide(self) -> None:
        stop_animation(self, b"visualPos")
        if self._gliding:
            self._gliding = False
            self._visual = float(self.value())
            self.update()

    def glide_to(self, target_raw: int, *, from_raw: int, animate: bool) -> None:
        if animate and should_animate(self) and (from_raw != target_raw or self._gliding):
            start = self._visual if self._gliding else float(from_raw)
            self._visual = start
            self._gliding = True
            animate_property(
                self, b"visualPos", float(target_raw), 220, ease_in_out_curve(),
                start_value=start, on_finished=self._finish_glide,
            )
        else:
            self.stop_glide()

    def _finish_glide(self) -> None:
        self._gliding = False
        self.update()

    def mousePressEvent(self, event) -> None:
        self.stop_glide()
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self.stop_glide()
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            self.stop_glide()
        super().wheelEvent(event)

    def paintEvent(self, event) -> None:
        if not self._gliding:
            super().paintEvent(event)
            return
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        pos = max(self.minimum(), min(self.maximum(), int(round(self._visual))))
        opt.sliderPosition = pos
        opt.sliderValue = pos
        opt.subControls = QStyle.SubControl.SC_SliderGroove | QStyle.SubControl.SC_SliderHandle
        if self.tickPosition() != QSlider.TickPosition.NoTicks:
            opt.subControls |= QStyle.SubControl.SC_SliderTickmarks
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_Slider, opt)
        painter.end()


class SliderRow(QWidget):
    """Labeled horizontal slider with synchronized tabular monospace readout and optional visual glide."""

    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        label: str,
        minimum: float,
        maximum: float,
        *,
        divisor: float = 1.0,
        display: Callable[[float], str] | None = None,
        initial: float | None = None,
        hint: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._divisor = divisor
        self._display = display or (lambda v: f"{v:g}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self._label = QLabel(label)
        self._label.setFont(ui_font(13))
        if hint:
            self.setToolTip(hint)
        top.addWidget(self._label, 1)

        self._readout = QLabel()
        self._readout.setFont(mono_font(12, QFont.Weight.Medium))
        self._readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._readout.setMinimumWidth(68)
        top.addWidget(self._readout)
        layout.addLayout(top)

        self._slider = _GlideSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(int(round(minimum * divisor)), int(round(maximum * divisor)))
        self._slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self._slider)

        self.set_value(minimum if initial is None else initial)

    def _on_slider(self, raw: int) -> None:
        val = raw / self._divisor
        self._readout.setText(self._display(val))
        self.valueChanged.emit(val)

    def value(self) -> float:
        return self._slider.value() / self._divisor

    def set_value(self, value: float, *, animate: bool = False) -> None:
        old_raw = self._slider.value()
        target_raw = max(self._slider.minimum(), min(self._slider.maximum(), int(round(value * self._divisor))))
        blocked = self._slider.blockSignals(True)
        try:
            self._slider.setValue(target_raw)
        finally:
            self._slider.blockSignals(blocked)
        self._readout.setText(self._display(self.value()))
        self._slider.glide_to(target_raw, from_raw=old_raw, animate=animate)

    def set_palette(self, p: ThemePalette) -> None:
        self._readout.setStyleSheet(f"color: {p.text_primary};")


class SegmentedControl(QWidget):
    """Animated segmented pill selector with smooth hover tint (Workbench|Settings, System|Light|Dark)."""

    currentChanged = pyqtSignal(int)

    def __init__(self, items: list[str], initial: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._items = list(items)
        self._index = max(0, min(len(items) - 1, initial))
        self._slide = float(self._index)
        self._hover_alpha = 0.0
        self._palette = DARK_PALETTE
        self._hover_idx = -1
        self._pointer_inside = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        widest = max((fm.horizontalAdvance(t) for t in self._items), default=60)
        return QSize((widest + 26) * len(self._items) + 6, 32)

    @pyqtProperty(float)
    def slidePos(self) -> float:
        return self._slide

    @slidePos.setter
    def slidePos(self, val: float) -> None:
        self._slide = val
        self.update()

    @pyqtProperty(float)
    def hoverAlpha(self) -> float:
        return self._hover_alpha

    @hoverAlpha.setter
    def hoverAlpha(self, val: float) -> None:
        self._hover_alpha = val
        self.update()

    def current_index(self) -> int:
        return self._index

    def set_index(self, idx: int, *, animate: bool = True, emit: bool = False) -> None:
        idx = max(0, min(len(self._items) - 1, idx))
        if idx == self._index and not emit:
            return
        self._index = idx
        if animate:
            animate_property(self, b"slidePos", float(idx), 200, ease_in_out_curve())
        else:
            stop_animation(self, b"slidePos")
            self._slide = float(idx)
            self.update()
        if idx == self._hover_idx:
            self._fade_hover(0.0, 120)
        if emit:
            self.currentChanged.emit(idx)

    def set_palette(self, p: ThemePalette) -> None:
        self._palette = p
        self.update()

    def _segment_idx_at(self, x: float) -> int:
        w = max(1, self.width() - 6)
        slot = w / max(1, len(self._items))
        return max(0, min(len(self._items) - 1, int((x - 3) / slot)))

    def _finish_hover_fade(self) -> None:
        if not self._pointer_inside and self._hover_alpha <= 0.01:
            self._hover_idx = -1
            self.update()

    def _fade_hover(self, target: float, dur: int, *, restart: bool = False) -> None:
        if should_animate(self) and dur > 0:
            animate_property(
                self, b"hoverAlpha", target, dur, ease_out_curve(),
                start_value=0.0 if restart else None,
                on_finished=self._finish_hover_fade,
            )
        else:
            stop_animation(self, b"hoverAlpha")
            self._hover_alpha = target
            if target <= 0.0 and not self._pointer_inside:
                self._hover_idx = -1
            self.update()

    def mouseMoveEvent(self, event) -> None:
        idx = self._segment_idx_at(event.position().x())
        reentered = not self._pointer_inside
        self._pointer_inside = True
        if reentered or idx != self._hover_idx:
            same_slot_reenter = reentered and idx == self._hover_idx and self._hover_alpha > 0.01
            self._hover_idx = idx
            if idx != self._index:
                self._fade_hover(1.0, 150, restart=not same_slot_reenter)
            else:
                self._fade_hover(0.0, 120)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._pointer_inside = False
        if self._hover_idx >= 0 and self._hover_idx != self._index and self._hover_alpha > 0.01:
            self._fade_hover(0.0, 120)
        else:
            self._hover_idx = -1
            self._fade_hover(0.0, 0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._segment_idx_at(event.position().x())
            if idx != self._index:
                self.set_index(idx, animate=True, emit=True)
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.set_index((self._index - 1) % len(self._items), animate=True, emit=True)
            return
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.set_index((self._index + 1) % len(self._items), animate=True, emit=True)
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        p = self._palette
        n = max(1, len(self._items))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        outer = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setPen(QPen(QColor(p.accent if self.hasFocus() else p.border), 1.0))
        painter.setBrush(QColor(p.bg_subtle))
        painter.drawRoundedRect(outer, 8.0, 8.0)

        inner_w = self.width() - 6.0
        slot_w = inner_w / n

        if self._hover_idx >= 0 and self._hover_idx != self._index and self._hover_alpha > 0.01:
            hc = QColor(p.bg_hover)
            hc.setAlphaF(self._hover_alpha)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(hc)
            painter.drawRoundedRect(QRectF(3.0 + self._hover_idx * slot_w, 3.0, slot_w, self.height() - 6.0), 6.0, 6.0)

        pill_x = 3.0 + self._slide * slot_w
        pill_rect = QRectF(pill_x, 3.0, slot_w, self.height() - 6.0)
        painter.setPen(QPen(QColor(p.border_strong if p.mode == "dark" else p.border), 1.0))
        painter.setBrush(QColor(p.bg_surface))
        painter.drawRoundedRect(pill_rect, 6.0, 6.0)

        painter.setFont(ui_font(12, QFont.Weight.DemiBold))
        for i, text in enumerate(self._items):
            rect = QRectF(3.0 + i * slot_w, 3.0, slot_w, self.height() - 6.0)
            if i == self._index or i == self._hover_idx:
                painter.setPen(QColor(p.text_primary))
            else:
                painter.setPen(QColor(p.text_secondary))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class CollapsibleBanner(QWidget):
    """Smooth 200ms height+opacity expand/collapse wrapper (synchronous when host window is hidden)."""

    def __init__(self, content: QWidget, parent=None) -> None:
        super().__init__(parent)
        self._content = content
        self._expanded = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(content)
        self.hide()

    def is_expanded(self) -> bool:
        return self._expanded

    def _stop_height_anim(self) -> None:
        stop_animation(self, b"maximumHeight")

    def set_expanded(self, on: bool) -> None:
        if on == self._expanded and ((on and not self.isHidden() and self.maximumHeight() == _QWIDGETSIZE_MAX)
                                     or (not on and self.isHidden())):
            return
        cur_eff = self.graphicsEffect()
        if isinstance(cur_eff, QGraphicsOpacityEffect) and not sip.isdeleted(cur_eff):
            cur_opacity = float(cur_eff.opacity())
        else:
            cur_opacity = 0.0 if self.isHidden() else 1.0
        self._expanded = on
        self._stop_height_anim()
        detach_effect(self)

        if not should_animate(self):
            self.setMaximumHeight(_QWIDGETSIZE_MAX)
            self.setVisible(on)
            return

        w = self.width() or (self.parentWidget().width() if self.parentWidget() else 400)
        target_h = self._content.heightForWidth(w) if self._content.hasHeightForWidth() else self._content.sizeHint().height()
        target_h = max(1, target_h)

        if on:
            if self.isHidden():
                self.setMaximumHeight(0)
                self.show()
                start_opacity = 0.0
            else:
                start_opacity = cur_opacity
            eff = fresh_opacity_effect(self, start_opacity)
            animate_property(
                self, b"maximumHeight", target_h, 200, ease_out_curve(),
                on_finished=self._finish_expand,
            )
            animate_property(eff, b"opacity", 1.0, 200, ease_out_curve())
        else:
            if self.isHidden():
                self.setMaximumHeight(_QWIDGETSIZE_MAX)
                return
            current_h = min(self.height(), target_h) if self.maximumHeight() == _QWIDGETSIZE_MAX else self.maximumHeight()
            self.setMaximumHeight(max(0, current_h))
            eff = fresh_opacity_effect(self, cur_opacity)
            animate_property(
                self, b"maximumHeight", 0, 200, ease_out_curve(),
                on_finished=self._finish_collapse,
            )
            animate_property(eff, b"opacity", 0.0, 200, ease_out_curve())

    def _finish_expand(self) -> None:
        if self._expanded:
            self.setMaximumHeight(_QWIDGETSIZE_MAX)
            detach_effect(self)

    def _finish_collapse(self) -> None:
        if not self._expanded:
            self.hide()
            self.setMaximumHeight(_QWIDGETSIZE_MAX)
            detach_effect(self)


class HotkeyCaptureButton(QPushButton):
    """Click to capture a single key or modifier combo; subtle 1400ms ring pulse while recording."""

    captureStarted = pyqtSignal()
    captureFinished = pyqtSignal()
    captureRejected = pyqtSignal(str)
    bindingChanged = pyqtSignal(str)

    def __init__(self, binding: str = "f9", parent=None) -> None:
        super().__init__(parent)
        self._binding = binding
        self._capturing = False
        self._glow = 0.0
        self._palette = DARK_PALETTE
        self._glow_anim = QPropertyAnimation(self, b"glow", self)
        self._glow_anim.setDuration(1400)
        self._glow_anim.setKeyValueAt(0.0, 0.0)
        self._glow_anim.setKeyValueAt(0.5, 1.0)
        self._glow_anim.setKeyValueAt(1.0, 0.0)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._glow_anim.setLoopCount(-1)

        self.setMinimumWidth(148)
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self.start_capture)
        self._refresh_text()

    @pyqtProperty(float)
    def glow(self) -> float:
        return self._glow

    @glow.setter
    def glow(self, val: float) -> None:
        self._glow = val
        self.update()

    def binding(self) -> str:
        return self._binding

    def set_binding(self, binding: str) -> None:
        self._binding = binding
        if not self._capturing:
            self._refresh_text()

    def set_palette(self, p: ThemePalette) -> None:
        self._palette = p
        self._refresh_style()

    def _start_glow(self) -> None:
        if should_animate(self):
            if self._glow_anim.state() != QAbstractAnimation.State.Running:
                self._glow_anim.start()
        else:
            self._glow_anim.stop()
            self._glow = 1.0
            self.update()

    def _stop_glow(self) -> None:
        self._glow_anim.stop()
        self._glow = 0.0
        self.update()

    def start_capture(self) -> None:
        if self._capturing:
            return
        self._capturing = True
        self._refresh_text()
        self._refresh_style()
        self._start_glow()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.captureStarted.emit()

    def cancel_capture(self) -> None:
        if not self._capturing:
            return
        self._capturing = False
        self._stop_glow()
        self._refresh_text()
        self._refresh_style()
        self.captureFinished.emit()

    def _refresh_text(self) -> None:
        self.setText("Press keys… (Esc)" if self._capturing else display_hotkey(self._binding))

    def _refresh_style(self) -> None:
        p = self._palette
        if self._capturing:
            self.setStyleSheet(
                f"QPushButton {{ background: {p.accent_tint}; color: {p.text_primary}; "
                "border: 1.5px solid transparent; border-radius: 7px; padding: 4px 10px; "
                "font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 12px; font-weight: 600; }}"
            )
        else:
            self.setStyleSheet(
                f"QPushButton {{ background: {p.bg_canvas}; color: {p.text_primary}; "
                f"border: 1px solid {p.border}; border-radius: 7px; padding: 4px 10px; "
                "font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 12px; font-weight: 600; }}"
                f"QPushButton:hover {{ background: {p.bg_subtle}; border-color: {p.border_strong}; }}"
            )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._capturing:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ring = QColor(self._palette.accent)
        ring.setAlphaF(0.45 + 0.55 * self._glow)
        painter.setPen(QPen(ring, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(0.75, 0.75, self.width() - 1.5, self.height() - 1.5), 7.0, 7.0)
        painter.end()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._capturing:
            super().keyPressEvent(event)
            return
        event.accept()
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_capture()
            return
        raw = qt_key_event_to_hotkey(event.key(), event.modifiers())
        if raw is None:
            return  # wait for the non-modifier key
        if not raw:
            self._capturing = False
            self._stop_glow()
            self._refresh_text()
            self._refresh_style()
            self.captureRejected.emit("Unsupported key — use F1–F11, Home, Insert, or Ctrl/Alt + letter/digit.")
            self.captureFinished.emit()
            return
        try:
            canon = format_hotkey(parse_hotkey(raw))
        except HotkeyError as err:
            self._capturing = False
            self._stop_glow()
            self._refresh_text()
            self._refresh_style()
            self.captureRejected.emit(str(err))
            self.captureFinished.emit()
            return
        self._binding = canon
        self._capturing = False
        self._stop_glow()
        self._refresh_text()
        self._refresh_style()
        self.bindingChanged.emit(canon)
        self.captureFinished.emit()

    def focusOutEvent(self, event) -> None:
        if self._capturing:
            self.cancel_capture()
        super().focusOutEvent(event)


class ToastBanner(QFrame):
    """Non-blocking, retargetable status toast anchored inside MainWindow."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._palette = DARK_PALETTE
        self._kind = "info"
        self._base_y = 0
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 9, 14, 9)
        row.setSpacing(8)
        self._icon = QLabel()
        self._icon.setFixedSize(16, 16)
        row.addWidget(self._icon)

        self._msg = QLabel()
        self._msg.setFont(ui_font(12, QFont.Weight.Medium))
        row.addWidget(self._msg)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self.hide()

    def set_palette(self, p: ThemePalette) -> None:
        self._palette = p
        self._apply_kind()

    def _apply_kind(self) -> None:
        p = self._palette
        if self._kind == "success":
            icon_name, color = "check", p.state_active
        elif self._kind == "warning":
            icon_name, color = "warning", p.state_warning
        elif self._kind == "danger":
            icon_name, color = "warning", p.state_danger
        else:
            icon_name, color = "check", p.accent
        self._icon.setPixmap(svg_pixmap(icon_name, color, 16))
        self.setStyleSheet(
            f"ToastBanner {{ background-color: {p.bg_elevated}; border: 1px solid {p.border_strong}; "
            f"border-radius: 9px; }}"
        )
        self._msg.setStyleSheet(f"color: {p.text_primary}; background: transparent;")

    def reposition(self) -> None:
        parent = self.parentWidget()
        if not parent:
            return
        self.setMaximumWidth(max(280, parent.width() - 32))
        self.adjustSize()
        x = max(12, (parent.width() - self.width()) // 2)
        self._base_y = max(12, parent.height() - self.height() - 16)
        self.move(x, self._base_y)

    def show_toast(self, message: str, kind: str = "info", duration_ms: int = 3800) -> None:
        self._kind = kind
        self._msg.setText(message)
        self._apply_kind()
        self.reposition()
        was_visible = self.isVisible() and self._effect.opacity() > 0.05
        self.show()
        self.raise_()
        if is_reduced_motion():
            stop_animation(self, b"pos")
            self.move(self.x(), self._base_y)
        else:
            if not was_visible:
                self.move(self.x(), self._base_y + 10)
            animate_property(self, b"pos", QPoint(self.x(), self._base_y), 200, ease_out_curve())
        animate_property(self._effect, b"opacity", 1.0, 200, ease_out_curve(), reduced_duration_ms=120)
        self._timer.start(duration_ms)

    def dismiss(self) -> None:
        self._timer.stop()
        if not self.isVisible():
            return
        if is_reduced_motion():
            stop_animation(self, b"pos")
        else:
            animate_property(self, b"pos", QPoint(self.x(), self._base_y + 10), 180, ease_out_curve())
        animate_property(
            self._effect,
            b"opacity",
            0.0,
            180,
            ease_out_curve(),
            reduced_duration_ms=120,
            on_finished=self._finish_hide,
        )

    def _finish_hide(self) -> None:
        if self._effect.opacity() <= 0.02:
            self.hide()
