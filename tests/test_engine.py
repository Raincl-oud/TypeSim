"""Tests for TypingEngine state machine, realism invariants, coding mode, Focus Guard, and Win32 struct contracts."""

from __future__ import annotations

import ctypes
import random
import subprocess
import sys
import threading
import time
import unittest

from typesim.config import TypingSettings
from typesim.engine import (
    EngineState, HybridSleeper, Key, PauseReason, StopReason, TypingEngine, normalize_text,
)
from typesim.win32_input import INPUT, _unicode_events, _vk_event, KEYEVENTF_EXTENDEDKEY, VK_HOME
from tests.fakes import FakeBackend, FakeClock, FakeSleeper, RecordingListener


class TestEngineAndWin32Contracts(unittest.TestCase):
    def _run_sync(self, text: str, settings: TypingSettings, backend: FakeBackend, *, seed: int = 42, target: int | None = 1001):
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        listener = RecordingListener()
        engine = TypingEngine(
            backend,
            listener,
            clock=clock,
            sleeper=sleeper,
            rng=random.Random(seed),
            spawn=lambda fn: fn(),
        )
        engine.start(text, settings, target)
        return listener, clock, sleeper

    def test_win32_struct_size_and_utf16_surrogate_batch(self) -> None:
        self.assertEqual(ctypes.sizeof(INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        evs = _unicode_events("😀")
        self.assertEqual(len(evs), 4)
        units = [e.ki.wScan for e in evs]
        self.assertEqual(units, [0xD83D, 0xD83D, 0xDE00, 0xDE00])
        home_ev = _vk_event(VK_HOME, False)
        self.assertTrue(home_ev.ki.dwFlags & KEYEVENTF_EXTENDEDKEY)

    def test_500_seeded_typo_runs_reconstruct_exact_text(self) -> None:
        sample = "Hello World! Quick brown fox 123.\r\nSecond Line with CAPS."
        expected = normalize_text(sample)
        settings = TypingSettings(wpm=120, error_rate=0.20, thinking_pause_chance=0.05, countdown=0)
        for seed in range(500):
            backend = FakeBackend(foreground=1001)
            listener, _, _ = self._run_sync(sample, settings, backend, seed=seed)
            self.assertEqual(len(listener.finished), 1)
            self.assertEqual(listener.finished[0].terminal_state, EngineState.COMPLETED)
            self.assertEqual(backend.buffer, expected, f"Mismatch on seed={seed}")

    def test_stop_never_emits_completed(self) -> None:
        backend = FakeBackend(foreground=1001)
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        listener = RecordingListener()
        engine = TypingEngine(backend, listener, clock=clock, sleeper=sleeper, rng=random.Random(1), spawn=lambda fn: fn())

        # Hook stops the engine after 4 ops
        backend.hooks[4] = lambda _b: engine.stop()
        engine.start("abcdefghij", TypingSettings(countdown=0, error_rate=0.0), 1001)
        self.assertEqual(len(listener.finished), 1)
        stats = listener.finished[0]
        self.assertEqual(stats.terminal_state, EngineState.STOPPED)
        self.assertEqual(stats.reason, StopReason.USER)
        self.assertNotIn((EngineState.COMPLETED, PauseReason.NONE, 0), listener.states)

    def test_real_hybrid_sleeper_interrupts_in_under_50ms(self) -> None:
        backend = FakeBackend(foreground=1001)
        listener = RecordingListener()
        typing_started = threading.Event()
        listener.state_events.append((EngineState.TYPING, PauseReason.NONE, typing_started))

        engine = TypingEngine(backend, listener, sleeper=HybridSleeper(), rng=random.Random(7))
        settings = TypingSettings(
            wpm=60,
            countdown=0,
            error_rate=0.0,
            thinking_pause_chance=1.0,  # space triggers 5.0s thinking pause immediately
            thinking_pause_min=5.0,
            thinking_pause_max=5.0,
        )
        engine.start("a b c", settings, 1001)
        self.assertTrue(typing_started.wait(timeout=1.0))
        time.sleep(0.05)  # allow engine to enter the 5s wait
        t0 = time.perf_counter()
        engine.stop()
        self.assertTrue(listener.done_event.wait(timeout=0.5))
        dt = time.perf_counter() - t0
        self.assertLess(dt, 0.05)
        self.assertEqual(listener.finished[0].terminal_state, EngineState.STOPPED)

    def test_coding_mode_gui_ide_clears_auto_indent_and_skips_symbol_typos(self) -> None:
        code = "def f(x):\n    return {x: [1, 2]}"
        settings = TypingSettings(wpm=100, error_rate=0.20, coding_mode=True, strip_ide_auto_indent=True, countdown=0)
        backend = FakeBackend(
            foreground=2001,
            process_names={2001: "Code.exe"},
            auto_indent_on_enter="    ",  # simulates VS Code inserting 4 spaces on Enter
        )
        listener, _, _ = self._run_sync(code, settings, backend, seed=99, target=2001)
        self.assertEqual(listener.finished[0].terminal_state, EngineState.COMPLETED)
        self.assertEqual(backend.buffer, code)
        self.assertIn(("key", Key.HOME.value, True), backend.ops)

    def test_coding_mode_skips_auto_indent_clear_for_terminals(self) -> None:
        code = "echo hi\n  echo bye"
        settings = TypingSettings(wpm=100, error_rate=0.0, coding_mode=True, strip_ide_auto_indent=True, countdown=0)
        for proc in ("powershell.exe", "WindowsTerminal.exe", "cmd.exe"):
            with self.subTest(proc=proc):
                backend = FakeBackend(foreground=3001, process_names={3001: proc})
                listener, _, _ = self._run_sync(code, settings, backend, target=3001)
                self.assertEqual(listener.finished[0].terminal_state, EngineState.COMPLETED)
                self.assertNotIn(("key", Key.HOME.value, True), backend.ops)
                self.assertEqual(backend.buffer, code)

    def test_focus_guard_mid_typo_and_focus_and_resume(self) -> None:
        # Force an overshoot/adjacent typo at index 2 ('c') and drop focus mid-action queue
        text = "abcdef"
        settings = TypingSettings(wpm=60, error_rate=0.20, focus_guard=True, focus_resume_countdown=2, countdown=0)
        backend = FakeBackend(foreground=1001)
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        listener = RecordingListener()
        paused_ev = threading.Event()
        listener.state_events.append((EngineState.PAUSED, PauseReason.FOCUS_LOST, paused_ev))

        engine = TypingEngine(backend, listener, clock=clock, sleeper=sleeper, rng=random.Random(3))

        # Trigger focus loss after 3 ops
        backend.hooks[3] = lambda b: setattr(b, "foreground", 9999)
        engine.start(text, settings, 1001)
        self.assertTrue(paused_ev.wait(timeout=2.0))
        engine.focus_and_resume()
        self.assertTrue(listener.done_event.wait(timeout=2.0))

        stats = listener.finished[0]
        self.assertEqual(stats.terminal_state, EngineState.COMPLETED)
        self.assertEqual(backend.buffer, text)
        # Focus & Resume countdown emitted 2, 1
        cd_vals = [c for st, _r, c in listener.states if st == EngineState.COUNTDOWN]
        self.assertEqual(cd_vals, [2, 1])

    def test_manual_pause_resumes_immediately_when_target_focused(self) -> None:
        backend = FakeBackend(foreground=1001)
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        listener = RecordingListener()
        paused_ev = threading.Event()
        listener.state_events.append((EngineState.PAUSED, PauseReason.MANUAL, paused_ev))
        engine = TypingEngine(backend, listener, clock=clock, sleeper=sleeper, rng=random.Random(1))

        backend.hooks[2] = lambda _b: engine.pause()
        engine.start("hello", TypingSettings(countdown=0, error_rate=0.0, focus_resume_countdown=3), 1001)
        self.assertTrue(paused_ev.wait(timeout=2.0))
        # Simulate long pause wall clock jump: must NOT enter stats.elapsed_seconds
        clock.t += 50.0
        engine.resume()
        self.assertTrue(listener.done_event.wait(timeout=2.0))

        self.assertEqual(listener.finished[0].terminal_state, EngineState.COMPLETED)
        self.assertEqual(backend.buffer, "hello")
        self.assertFalse(any(st == EngineState.COUNTDOWN for st, _, _ in listener.states))
        self.assertLess(listener.finished[0].elapsed_seconds, 10.0)

    def test_missing_target_and_input_blocked_stop_cleanly(self) -> None:
        # 1. Own window foreground with target=None -> TARGET_UNAVAILABLE
        own_backend = FakeBackend(foreground=555, own_windows={555})
        listener, _, _ = self._run_sync("hi", TypingSettings(countdown=0), own_backend, target=None)
        self.assertEqual(listener.finished[0].terminal_state, EngineState.STOPPED)
        self.assertEqual(listener.finished[0].reason, StopReason.TARGET_UNAVAILABLE)

        # 2. SendInput returns False (UIPI block) -> INPUT_BLOCKED
        blocked_backend = FakeBackend(foreground=1001, send_ok=False)
        listener2, _, _ = self._run_sync("hi", TypingSettings(countdown=0, error_rate=0.0), blocked_backend, target=1001)
        self.assertEqual(listener2.finished[0].terminal_state, EngineState.STOPPED)
        self.assertEqual(listener2.finished[0].reason, StopReason.INPUT_BLOCKED)

    def test_set_live_wpm_does_not_mutate_original_settings(self) -> None:
        orig = TypingSettings(wpm=65, countdown=0, error_rate=0.0)
        backend = FakeBackend(foreground=1001)
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        listener = RecordingListener()
        engine = TypingEngine(backend, listener, clock=clock, sleeper=sleeper, rng=random.Random(1), spawn=lambda fn: fn())

        backend.hooks[2] = lambda _b: engine.set_live_wpm(300)
        engine.start("abcdef", orig, 1001)
        self.assertEqual(orig.wpm, 65)
        self.assertTrue(any(w == 300 for _, _, w, _ in listener.progress))

    def test_set_live_wpm_emits_updated_eta_while_paused(self) -> None:
        backend = FakeBackend(foreground=1001)
        clock = FakeClock()
        sleeper = FakeSleeper(clock)
        listener = RecordingListener()
        paused_ev = threading.Event()
        listener.state_events.append((EngineState.PAUSED, PauseReason.MANUAL, paused_ev))
        engine = TypingEngine(backend, listener, clock=clock, sleeper=sleeper, rng=random.Random(1))

        backend.hooks[2] = lambda _b: engine.pause()
        engine.start("abcdefghij" * 5, TypingSettings(wpm=50, countdown=0, error_rate=0.0), 1001)
        self.assertTrue(paused_ev.wait(timeout=2.0))
        prev_eta = listener.progress[-1][3]
        applied = engine.set_live_wpm(200)
        self.assertEqual(applied, 200)
        self.assertEqual(listener.progress[-1][2], 200)
        self.assertLess(listener.progress[-1][3], prev_eta)
        engine.stop()
        self.assertTrue(listener.done_event.wait(timeout=2.0))

    def test_core_modules_do_not_import_pyqt6(self) -> None:
        res = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, typesim.engine, typesim.config, typesim.profiles, typesim.estimator; "
                "assert not any(m.startswith('PyQt6') for m in sys.modules), [m for m in sys.modules if m.startswith('PyQt6')]",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, msg=res.stderr)
