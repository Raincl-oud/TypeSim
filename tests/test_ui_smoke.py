"""Offscreen PyQt6 smoke and regression tests for icons, motion, MainWindow, FloatingHUD, and hotkeys."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import (
    QAbstractAnimation, QBuffer, QByteArray, QCoreApplication, QEvent, QIODevice, QObject, QPoint, QPointF, QRect,
    QSize, Qt, pyqtProperty,
)
from PyQt6.QtGui import QCloseEvent, QColor, QImageReader, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from typesim.config import TypingSettings
from typesim.engine import EngineState, PauseReason, SessionStats, StopReason
from typesim.hotkeys import HotkeyManager, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT
from typesim.profiles import save_profile
from typesim.ui import motion
from typesim.ui.bridge import SessionController, format_summary_message
from typesim.ui.hud import HUD_HEIGHT, HUD_WIDTH, anchor_pos, preview_slice, snap_anchor
from typesim.ui.icons import ICO_SIZES, app_icon, build_ico_bytes, render_keycap, resource_path, tray_app_icon
from typesim.ui.main_window import MainWindow
from typesim.ui.theme import DARK_PALETTE, build_stylesheet
from typesim.ui.tray import TrayController
from typesim.ui.widgets import SliderRow, ToastBanner, qt_key_event_to_hotkey
from typesim.win32_input import WindowInfo
from tests.fakes import FakeBackend

_APP: QApplication | None = None


def _app() -> QApplication:
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _finish_anim(anim: QAbstractAnimation | None) -> None:
    if anim is not None and anim.state() == QAbstractAnimation.State.Running:
        dur = anim.totalDuration()
        if dur >= 0:
            anim.setCurrentTime(dur)


class _AnimTarget(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._v = 0.0

    @pyqtProperty(float)
    def val(self) -> float:
        return self._v

    @val.setter
    def val(self, v: float) -> None:
        self._v = v


class TestUiSmoke(unittest.TestCase):
    def test_ico_builder_and_committed_asset(self) -> None:
        _app()
        blob = build_ico_bytes()
        reserved, typ, count = struct.unpack_from("<HHH", blob, 0)
        self.assertEqual((reserved, typ, count), (0, 1, len(ICO_SIZES)))

        widths: list[int] = []
        prev_end = 6 + 16 * count
        for idx in range(count):
            w, h, _cc, _r, planes, bpp, size, off = struct.unpack_from("<BBBBHHII", blob, 6 + 16 * idx)
            self.assertEqual(w, h)
            self.assertEqual((planes, bpp), (1, 32))
            self.assertGreaterEqual(off, prev_end)
            self.assertLessEqual(off + size, len(blob))
            actual_w = 256 if w == 0 else w
            if actual_w < 256:
                bi_size, bi_w, bi_h, bi_pl, bi_bpp, bi_comp = struct.unpack_from("<IiiHHI", blob, off)
                self.assertEqual((bi_size, bi_w, bi_h, bi_pl, bi_bpp, bi_comp), (40, actual_w, actual_w * 2, 1, 32, 0))
                and_stride = ((actual_w + 31) // 32) * 4
                self.assertEqual(size, 40 + actual_w * actual_w * 4 + and_stride * actual_w)
            else:
                self.assertEqual(blob[off : off + 8], b"\x89PNG\r\n\x1a\n")
            widths.append(actual_w)
            prev_end = off + size
        self.assertEqual(tuple(widths), ICO_SIZES)

        ba = QByteArray(blob)
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buf, b"ico")
        decoded = []
        for i in range(reader.imageCount()):
            reader.jumpToImage(i)
            decoded.append(reader.read().width())
        self.assertEqual(tuple(decoded), ICO_SIZES)

        ico_file = Path(resource_path("assets/typesim.ico"))
        self.assertTrue(ico_file.is_file())
        disk_blob = ico_file.read_bytes()
        first_off = struct.unpack_from("<I", disk_blob, 6 + 12)[0]
        self.assertEqual(struct.unpack_from("<I", disk_blob, first_off)[0], 40)
        file_reader = QImageReader(str(ico_file))
        self.assertEqual(file_reader.imageCount(), len(ICO_SIZES))
        ic = app_icon()
        self.assertFalse(ic.isNull())
        self.assertEqual(sorted(s.width() for s in ic.availableSizes()), list(ICO_SIZES))
        self.assertEqual(render_keycap(22).size(), QSize(22, 22))

    def test_tray_app_icon_state_badges_and_cache(self) -> None:
        _app()
        ic_idle = tray_app_icon(DARK_PALETTE, EngineState.IDLE)
        ic_done = tray_app_icon(DARK_PALETTE, EngineState.COMPLETED)
        ic_typing = tray_app_icon(DARK_PALETTE, EngineState.TYPING)
        ic_paused = tray_app_icon(DARK_PALETTE, EngineState.PAUSED)
        ic_cd = tray_app_icon(DARK_PALETTE, EngineState.COUNTDOWN)

        self.assertIs(ic_idle, ic_done)
        self.assertIs(ic_paused, ic_cd)
        self.assertIsNot(ic_idle, ic_typing)
        self.assertIsNot(ic_typing, ic_paused)

        # Verify 16px tray badge dot center pixel at (13, 13)
        img_typing = ic_typing.pixmap(16, 16).toImage().pixelColor(13, 13)
        self.assertGreater(img_typing.green(), img_typing.red() + 40)
        self.assertGreater(img_typing.green(), img_typing.blue() + 40)

        img_paused = ic_paused.pixmap(16, 16).toImage().pixelColor(13, 13)
        self.assertGreater(img_paused.red(), img_paused.blue() + 80)
        self.assertGreater(img_paused.green(), img_paused.blue() + 40)

        img_idle = ic_idle.pixmap(16, 16).toImage().pixelColor(13, 13)
        self.assertLess(img_idle.green(), 100)

        tray = TrayController()
        tray.update_state(EngineState.TYPING)
        self.assertEqual(tray._dot_class, "typing")
        tray.update_state(EngineState.COUNTDOWN)
        self.assertEqual(tray._dot_class, "attention")
        tray.update_state(EngineState.IDLE)
        self.assertEqual(tray._dot_class, "idle")
        tray.hide()

    def test_hud_pure_anchor_snap_and_preview_helpers(self) -> None:
        avail = QRect(0, 0, 1920, 1040)
        sz = QSize(HUD_WIDTH, HUD_HEIGHT)

        top_c = anchor_pos("top-center", sz, avail)
        self.assertEqual(top_c, QPoint((1920 - HUD_WIDTH) // 2, 16))
        bot_r = anchor_pos("bottom-right", sz, avail)
        self.assertEqual(bot_r, QPoint(1920 - HUD_WIDTH - 16, 1040 - HUD_HEIGHT - 16))

        self.assertEqual(snap_anchor(QRect(20, 10, HUD_WIDTH, HUD_HEIGHT), avail), "top-left")
        self.assertEqual(snap_anchor(QRect(1300, 1040 - HUD_HEIGHT - 12, HUD_WIDTH, HUD_HEIGHT), avail), "bottom-right")
        self.assertIsNone(snap_anchor(QRect(500, 400, HUD_WIDTH, HUD_HEIGHT), avail))

        done, up = preview_slice("hello\nworld\t!", 6, before=18, after=30)
        self.assertEqual(done, "hello↵")
        self.assertEqual(up, "world⇥!")

    def test_qt_key_event_to_hotkey(self) -> None:
        self.assertIsNone(qt_key_event_to_hotkey(Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier))
        self.assertEqual(qt_key_event_to_hotkey(Qt.Key.Key_F9, Qt.KeyboardModifier.NoModifier), "f9")
        self.assertEqual(
            qt_key_event_to_hotkey(Qt.Key.Key_F9, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier),
            "ctrl+shift+f9",
        )

    def test_animation_retargeting_and_toast_mid_dismiss(self) -> None:
        app = _app()
        with mock.patch.object(motion, "is_reduced_motion", return_value=False):
            target = _AnimTarget()
            anim1 = motion.animate_property(target, b"val", 1.0, 200, start_value=0.0)
            anim1.setCurrentTime(80)
            mid_val = target.property("val")
            self.assertGreater(mid_val, 0.05)
            anim2 = motion.animate_property(target, b"val", 0.0, 200, start_value=1.0)
            self.assertAlmostEqual(anim2.startValue(), mid_val, places=3)
            anim2.stop()

            parent = QWidget()
            parent.resize(800, 560)
            toast = ToastBanner(parent)
            with mock.patch("typesim.ui.widgets.is_reduced_motion", return_value=False):
                toast.show_toast("First", "info")
                toast.dismiss()
                toast._anim_pos.setCurrentTime(90)
                toast.show_toast("Second", "success")
                app.processEvents()
                self.assertEqual(toast._anim_pos.endValue(), QPoint(toast.x(), toast._base_y))
            parent.close()

    def test_visible_window_animations_interruptibility_and_reduced_motion(self) -> None:
        app = _app()
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            prof_path = os.path.join(tmp, "profiles.json")
            hm = HotkeyManager(register=lambda *a: True, unregister=lambda *a: True)
            ctrl = SessionController(backend_factory=lambda _m: FakeBackend(foreground=101))
            windows = [
                WindowInfo(101, "notes.txt - Notepad", "notepad.exe"),
                WindowInfo(202, "Administrator: Windows PowerShell", "powershell.exe"),
            ]
            win = MainWindow(
                config_path=cfg_path,
                profiles_path=prof_path,
                hotkey_manager=hm,
                controller=ctrl,
                enumerate_windows_fn=lambda: windows,
                elevation_check_fn=lambda hwnd: hwnd == 202,
                self_elevated_fn=lambda: False,
                tray_available=True,
            )
            try:
                with mock.patch("typesim.ui.motion.is_reduced_motion", return_value=False), \
                     mock.patch("typesim.ui.widgets.is_reduced_motion", return_value=False), \
                     mock.patch("typesim.ui.main_window.is_reduced_motion", return_value=False), \
                     mock.patch("typesim.ui.hud.is_reduced_motion", return_value=False):
                    win.show()
                    app.processEvents()

                    # (a)+(b) Rapid view switching & Settings card cascade settle cleanly with zero leftover effects
                    win._view_tabs.set_index(1, animate=False, emit=True)
                    self.assertEqual(win._stack.currentIndex(), 1)
                    win._view_tabs.set_index(0, animate=False, emit=True)
                    self.assertEqual(win._stack.currentIndex(), 0)
                    win._view_tabs.set_index(1, animate=False, emit=True)
                    _finish_anim(win._card_cascade)
                    ov = getattr(win._stack, "_snapshot_overlay", None)
                    if ov is not None:
                        _finish_anim(getattr(ov, "_anim_pos", None))
                        eff = ov.graphicsEffect()
                        _finish_anim(getattr(eff, "_anim_opacity", None) if eff else None)
                    app.processEvents()
                    self.assertIsNone(getattr(win._stack, "_snapshot_overlay", None))
                    for card in win._settings_cards:
                        self.assertIsNone(card.graphicsEffect())

                    # (c) Rapid theme crossfade + button swap + refresh spin
                    win._toggle_theme_mode()
                    win._toggle_theme_mode()
                    ov_t = getattr(win.centralWidget(), "_snapshot_overlay", None)
                    if ov_t is not None and ov_t.graphicsEffect() is not None:
                        _finish_anim(getattr(ov_t.graphicsEffect(), "_anim_opacity", None))
                    _finish_anim(getattr(win._btn_theme, "_anim_swapProgress", None))
                    win._on_refresh_windows_clicked()
                    _finish_anim(getattr(win._btn_refresh_win, "_anim_spinAngle", None))
                    app.processEvents()
                    self.assertIsNone(getattr(win.centralWidget(), "_snapshot_overlay", None))
                    self.assertIsNone(win._btn_theme._old_pm)
                    self.assertEqual(win._btn_refresh_win._angle, 0.0)

                    # (d) Slider glide on visible window keeps value() & readout immediate
                    win._apply_preset("Fast")
                    self.assertEqual(win._wb_wpm.value(), 110)
                    self.assertEqual(win._wb_wpm._readout.text(), "110 WPM")
                    self.assertTrue(win._wb_wpm._slider._gliding)
                    _finish_anim(getattr(win._wb_wpm._slider, "_anim_visualPos", None))
                    app.processEvents()
                    self.assertFalse(win._wb_wpm._slider._gliding)

                    # (f) CollapsibleBanner expand/collapse mid-flight
                    win._win_combo.setCurrentIndex(2)
                    self.assertFalse(win._uipi_bar.isHidden())
                    win._win_combo.setCurrentIndex(1)
                    win._win_combo.setCurrentIndex(2)
                    _finish_anim(getattr(win._uipi_bar, "_anim_maximumHeight", None))
                    if win._uipi_bar.graphicsEffect() is not None:
                        _finish_anim(getattr(win._uipi_bar.graphicsEffect(), "_anim_opacity", None))
                    app.processEvents()
                    self.assertEqual(win._uipi_bar.maximumHeight(), 16777215)
                    self.assertIsNone(win._uipi_bar.graphicsEffect())

                    # (g) HotkeyCaptureButton recording pulse starts and stops cleanly
                    hk_btn = win._hk_buttons["start"]
                    hk_btn.start_capture()
                    self.assertEqual(hk_btn._glow_anim.state(), QAbstractAnimation.State.Running)
                    hk_btn.cancel_capture()
                    self.assertEqual(hk_btn._glow_anim.state(), QAbstractAnimation.State.Stopped)
                    self.assertEqual(hk_btn._glow, 0.0)

                    # (h) Tray minimize/restore resets opacity cleanly on mid-restore hide
                    win._minimize_to_tray()
                    self.assertTrue(win.isHidden())
                    win._restore_window()
                    self.assertFalse(win.isHidden())
                    win._minimize_to_tray()
                    self.assertEqual(win.windowOpacity(), 1.0)

                    # (i) FloatingHUD living progress, caret, countdown tick fade, and summary shimmer
                    hud = win._hud
                    hud.show_session("Hello\nWorld", 11, 85)
                    hud.set_state(EngineState.COUNTDOWN, PauseReason.NONE, 2)
                    self.assertEqual(hud._status_lbl.text(), "Starting 2s")
                    if hud._status_lbl.graphicsEffect() is not None:
                        _finish_anim(getattr(hud._status_lbl.graphicsEffect(), "_anim_opacity", None))
                    hud.set_state(EngineState.TYPING, PauseReason.NONE, 0)
                    self.assertTrue(hud._preview._typing_active)
                    self.assertEqual(hud._preview._caret_alpha, 1.0)
                    hud.set_progress(5, 11, 85, 4.0)
                    _finish_anim(getattr(hud, "_anim_displayProgress", None))
                    self.assertAlmostEqual(hud._display_progress, 5 / 11, places=3)
                    hud.show_summary(SessionStats(11, 11, 2.0, 66.0, 0, EngineState.COMPLETED, StopReason.NONE))
                    self.assertTrue(hud._sweeping)
                    _finish_anim(getattr(hud, "_anim_sweepPos", None))
                    self.assertFalse(hud._sweeping)
                    hud.hide_animated()
                    app.processEvents()
                    self.assertIsNone(getattr(hud, "_snapshot_overlay", None))

                # Reduced motion: zero snapshot overlays or card opacity effects created
                with mock.patch("typesim.ui.motion.is_reduced_motion", return_value=True), \
                     mock.patch("typesim.ui.widgets.is_reduced_motion", return_value=True), \
                     mock.patch("typesim.ui.main_window.is_reduced_motion", return_value=True), \
                     mock.patch("typesim.ui.hud.is_reduced_motion", return_value=True):
                    win.show()
                    win._view_tabs.set_index(0, animate=False, emit=True)
                    win._view_tabs.set_index(1, animate=False, emit=True)
                    app.processEvents()
                    self.assertIsNone(win._card_cascade)
                    for card in win._settings_cards:
                        self.assertIsNone(card.graphicsEffect())
                    win._apply_preset("Natural")
                    self.assertFalse(win._wb_wpm._slider._gliding)
            finally:
                win._force_quit = True
                win._hotkeys.shutdown()
                win._hud.hide()
                win._tray.hide()
                win.close()

    def test_glide_slider_renders_pixels_idle_and_mid_glide(self) -> None:
        app = _app()
        host = QWidget()
        host.setObjectName("surfaceCard")
        host.setStyleSheet(build_stylesheet(DARK_PALETTE))
        lay = QVBoxLayout(host)
        row = SliderRow("Speed", 15, 400, initial=85, display=lambda v: f"{int(round(v))} WPM")
        row.set_palette(DARK_PALETTE)
        lay.addWidget(row)
        host.resize(340, 80)
        with mock.patch("typesim.ui.motion.is_reduced_motion", return_value=False), \
             mock.patch("typesim.ui.widgets.is_reduced_motion", return_value=False):
            host.show()
            app.processEvents()
            slider = row._slider
            bg_rgb = QColor(DARK_PALETTE.bg_surface).rgb()

            def _pixel_stats(img) -> tuple[int, int]:
                non_bg = 0
                max_accent_x = -1
                for y in range(img.height()):
                    for x in range(img.width()):
                        px = img.pixelColor(x, y)
                        if px.rgb() != bg_rgb:
                            non_bg += 1
                            if px.blue() > px.red() + 40 and x > max_accent_x:
                                max_accent_x = x
                return non_bg, max_accent_x

            idle_img = slider.grab().toImage()
            idle_non_bg, idle_accent_x = _pixel_stats(idle_img)
            self.assertGreater(idle_non_bg, 150)
            self.assertGreater(idle_accent_x, 0)

            row.set_value(350, animate=True)
            self.assertEqual(row.value(), 350)
            self.assertTrue(slider._gliding)
            anim = getattr(slider, "_anim_visualPos", None)
            self.assertIsNotNone(anim)
            anim.setCurrentTime(140)
            app.processEvents()

            glide_img = slider.grab().toImage()
            glide_non_bg, glide_accent_x = _pixel_stats(glide_img)
            self.assertGreater(glide_non_bg, 150)
            self.assertGreater(glide_accent_x, idle_accent_x + 20)

            _finish_anim(anim)
            app.processEvents()
            self.assertFalse(slider._gliding)
            host.close()

    def test_deferred_delete_safety_and_hover_progress_polish(self) -> None:
        app = _app()

        def _flush() -> None:
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            prof_path = os.path.join(tmp, "profiles.json")
            hm = HotkeyManager(register=lambda *a: True, unregister=lambda *a: True)
            ctrl = SessionController(backend_factory=lambda _m: FakeBackend(foreground=101))
            windows = [
                WindowInfo(101, "notes.txt - Notepad", "notepad.exe"),
                WindowInfo(202, "Administrator: Windows PowerShell", "powershell.exe"),
            ]
            win = MainWindow(
                config_path=cfg_path,
                profiles_path=prof_path,
                hotkey_manager=hm,
                controller=ctrl,
                enumerate_windows_fn=lambda: windows,
                elevation_check_fn=lambda hwnd: hwnd == 202,
                self_elevated_fn=lambda: False,
                tray_available=True,
            )
            try:
                with mock.patch("typesim.ui.motion.is_reduced_motion", return_value=False), \
                     mock.patch("typesim.ui.widgets.is_reduced_motion", return_value=False), \
                     mock.patch("typesim.ui.main_window.is_reduced_motion", return_value=False), \
                     mock.patch("typesim.ui.hud.is_reduced_motion", return_value=False):
                    win.show()
                    app.processEvents()

                    # 1. SegmentedControl preserves hover slot while fading out on leaveEvent
                    tabs = win._view_tabs
                    right_pt = QPointF(tabs.width() * 0.75, tabs.height() * 0.5)
                    tabs.mouseMoveEvent(
                        QMouseEvent(
                            QEvent.Type.MouseMove,
                            right_pt,
                            right_pt,
                            Qt.MouseButton.NoButton,
                            Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier,
                        )
                    )
                    _finish_anim(getattr(tabs, "_anim_hoverAlpha", None))
                    self.assertEqual(tabs._hover_idx, 1)
                    self.assertAlmostEqual(tabs._hover_alpha, 1.0, places=2)
                    tabs.leaveEvent(QEvent(QEvent.Type.Leave))
                    self.assertEqual(tabs._hover_idx, 1)
                    _finish_anim(getattr(tabs, "_anim_hoverAlpha", None))
                    _flush()
                    self.assertEqual(tabs._hover_idx, -1)
                    self.assertAlmostEqual(tabs._hover_alpha, 0.0, places=2)

                    # 2. 2nd HUD session & show_summary cancelling in-flight displayProgress chase
                    hud = win._hud
                    hud.show_session("Alpha", 5, 85)
                    hud.set_state(EngineState.TYPING, PauseReason.NONE, 0)
                    hud.set_progress(2, 5, 85, 2.0)
                    self.assertIsNotNone(getattr(hud, "_anim_displayProgress", None))
                    hud.show_summary(SessionStats(5, 5, 1.5, 85.0, 0, EngineState.COMPLETED, StopReason.NONE))
                    self.assertIsNone(getattr(hud, "_anim_displayProgress", None))
                    self.assertEqual(hud._display_progress, 1.0)
                    _finish_anim(getattr(hud, "_anim_sweepPos", None))
                    hud.hide_animated()
                    _finish_anim(getattr(hud, "_anim_pos", None))
                    _finish_anim(getattr(hud, "_anim_windowOpacity", None))
                    _flush()
                    hud.show_session("Beta", 4, 95)
                    hud.set_progress(2, 4, 95, 1.0)
                    _flush()
                    hud.hide_animated()
                    _flush()

                    # 3. 2nd tray restore & DeferredDelete between hides/restores
                    win._minimize_to_tray()
                    _flush()
                    win._restore_window()
                    win._minimize_to_tray()
                    _flush()
                    win._restore_window()
                    _flush()

                    # 4. 2nd view switch + resizeEvent after DeferredDelete
                    win._view_tabs.set_index(1, animate=True, emit=True)
                    _finish_anim(win._card_cascade)
                    _flush()
                    win._view_tabs.set_index(0, animate=True, emit=True)
                    _finish_anim(getattr(win._stack.widget(0), "_anim_pos", None))
                    _flush()
                    win._view_tabs.set_index(1, animate=True, emit=True)
                    win.resize(900, 600)
                    _flush()
                    win._view_tabs.set_index(0, animate=True, emit=True)
                    win.resize(880, 580)
                    _flush()

                    # 5. Slider mousePress after interrupting glide + DeferredDelete
                    slider = win._wb_wpm._slider
                    win._apply_preset("Fast")
                    slider.stop_glide()
                    _flush()
                    pt = QPointF(slider.width() * 0.5, slider.height() * 0.5)
                    slider.mousePressEvent(
                        QMouseEvent(
                            QEvent.Type.MouseButtonPress,
                            pt,
                            pt,
                            Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier,
                        )
                    )
                    _flush()

                    # 6. CollapsibleBanner non-animated collapse + DeferredDelete + mid-collapse re-expand opacity
                    win._win_combo.setCurrentIndex(2)
                    _finish_anim(getattr(win._uipi_bar, "_anim_maximumHeight", None))
                    _flush()
                    with mock.patch("typesim.ui.motion.is_reduced_motion", return_value=True), \
                         mock.patch("typesim.ui.widgets.is_reduced_motion", return_value=True):
                        win._win_combo.setCurrentIndex(1)
                    _flush()
                    win._win_combo.setCurrentIndex(2)
                    _finish_anim(getattr(win._uipi_bar, "_anim_maximumHeight", None))
                    _flush()

                    win._win_combo.setCurrentIndex(1)
                    h_anim = getattr(win._uipi_bar, "_anim_maximumHeight", None)
                    op_eff = win._uipi_bar.graphicsEffect()
                    op_anim = getattr(op_eff, "_anim_opacity", None) if op_eff is not None else None
                    if h_anim is not None and op_anim is not None:
                        h_anim.setCurrentTime(140)
                        op_anim.setCurrentTime(140)
                        app.processEvents()
                        mid_op = op_eff.opacity()
                        self.assertLess(mid_op, 0.4)
                        win._win_combo.setCurrentIndex(2)
                        new_eff = win._uipi_bar.graphicsEffect()
                        new_op_anim = getattr(new_eff, "_anim_opacity", None) if new_eff is not None else None
                        self.assertIsNotNone(new_op_anim)
                        self.assertAlmostEqual(new_op_anim.startValue(), mid_op, places=3)
            finally:
                win._force_quit = True
                win._hotkeys.shutdown()
                win._hud.hide()
                win._tray.hide()
                win.close()

    def test_main_window_theme_presets_profiles_capture_live_wpm_and_close(self) -> None:
        app = _app()
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            prof_path = os.path.join(tmp, "profiles.json")
            save_profile(
                "CustomTurbo",
                TypingSettings(wpm=145, variation=0.12, coding_mode=True, hotkey_start="ctrl+f9"),
                prof_path,
            )

            reg_calls: list[tuple[int, int, int]] = []
            hm = HotkeyManager(
                register=lambda _h, hid, mods, vk: reg_calls.append((hid, mods, vk)) or True,
                unregister=lambda _h, _hid: True,
            )
            ctrl = SessionController(backend_factory=lambda _m: FakeBackend(foreground=101))
            windows = [
                WindowInfo(101, "notes.txt - Notepad", "notepad.exe"),
                WindowInfo(202, "Administrator: Windows PowerShell", "powershell.exe"),
            ]
            win = MainWindow(
                config_path=cfg_path,
                profiles_path=prof_path,
                hotkey_manager=hm,
                controller=ctrl,
                enumerate_windows_fn=lambda: windows,
                elevation_check_fn=lambda hwnd: hwnd == 202,
                self_elevated_fn=lambda: False,
                tray_available=False,
            )
            try:
                # Theme switching & view tabs
                win._on_theme_segment_changed(1)  # Light
                self.assertEqual(win._palette.mode, "light")
                win._on_theme_segment_changed(2)  # Dark
                self.assertEqual(win._palette.mode, "dark")
                win._view_tabs.set_index(1, animate=False, emit=True)
                self.assertEqual(win._stack.currentIndex(), 1)
                win._view_tabs.set_index(0, animate=False, emit=True)

                # Preset apply updates slider & readout text
                win._apply_preset("Fast")
                self.assertEqual(win._wb_wpm._readout.text(), "110 WPM")
                self.assertEqual(win._st_wpm._readout.text(), "110 WPM")

                # Loading custom profile updates sliders, readouts, toggles, AND re-registers hotkeys
                reg_calls.clear()
                win._load_profile_by_name("CustomTurbo")
                self.assertEqual(win._wb_wpm._readout.text(), "145 WPM")
                self.assertEqual(win._st_var._readout.text(), "12%")
                self.assertTrue(win._wb_coding.isChecked())
                self.assertEqual(win._start_keycap.text(), "Ctrl+F9")
                self.assertTrue(len(reg_calls) >= 3)

                # Regression: Key-Capture re-registers the NEW binding immediately in Win32
                reg_calls.clear()
                hk_btn = win._hk_buttons["start"]
                hk_btn.start_capture()
                hk_btn.keyPressEvent(
                    QKeyEvent(
                        QEvent.Type.KeyPress,
                        Qt.Key.Key_F8,
                        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
                    )
                )
                self.assertEqual(win._config.typing.hotkey_start, "ctrl+shift+f8")
                self.assertEqual(win._start_keycap.text(), "Ctrl+Shift+F8")
                self.assertIn((1, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, 0x77), reg_calls)

                # Target window UIPI warning toggles on elevated HWND (suppressed when self-elevated)
                win._win_combo.setCurrentIndex(2)
                self.assertFalse(win._uipi_bar.isHidden())
                win._is_self_elevated = lambda: True
                win._on_target_changed()
                self.assertTrue(win._uipi_bar.isHidden())
                win._is_self_elevated = lambda: False
                win._win_combo.setCurrentIndex(1)
                self.assertTrue(win._uipi_bar.isHidden())

                # Regression: HUD +/- WPM stepper updates HUD WPM & ETA live during COUNTDOWN
                win._config.typing.wpm = 65
                win._config.typing.countdown = 3
                win._editor.setPlainText("Hello world from TypeSim v2.0! " * 6)
                win._start_typing()
                app.processEvents()
                win._hud._btn_plus.click()
                app.processEvents()
                self.assertEqual(win._hud._wpm_lbl.text(), "75 WPM")
                self.assertNotEqual(win._hud._eta_lbl.text(), "--")
                win._controller.stop()
                for _ in range(40):
                    app.processEvents()
                    if not win._controller.is_running():
                        break
                    import time
                    time.sleep(0.01)

                # FloatingHUD summary and subsequent show_session reset
                stats = SessionStats(120, 120, 22.0, 65.0, 2, EngineState.COMPLETED, StopReason.NONE)
                self.assertIn("2 typos fixed", format_summary_message(stats))
                win._hud.show_summary(stats)
                self.assertIn("2 typos fixed", win._hud._status_lbl.text())
                win._hud.show_session("Hello\nWorld", 11, 145)
                self.assertEqual(win._hud._status_lbl.text(), "Starting")

                win._hud.set_state(EngineState.TYPING, PauseReason.NONE, 0)
                self.assertEqual(win._hud._status_lbl.text(), "Typing")
                win._hud.set_state(EngineState.PAUSED, PauseReason.FOCUS_LOST, 0)
                self.assertEqual(win._hud._status_lbl.text(), "Focus Lost")
                self.assertEqual(win._hud._btn_primary.text(), "Focus && Resume")

                # Toast banner shows and repositions cleanly
                win._toast.show_toast("Profile saved.", "success")
                self.assertFalse(win._toast.isHidden())
                win.resize(740, 500)
                win._toast.reposition()

                # Close behavior respects close_to_tray
                win._tray_available = True
                win._config.prefs.close_to_tray = True
                ev_hide = QCloseEvent()
                win.closeEvent(ev_hide)
                self.assertFalse(ev_hide.isAccepted())
            finally:
                win._force_quit = True
                win._hotkeys.shutdown()
                win._hud.hide()
                win.close()
