"""Tests for ETA estimator, O(1) SessionEstimator, and duration formatting."""

from __future__ import annotations

import time
import unittest

from typesim.config import TypingSettings
from typesim.estimator import SessionEstimator, estimate_remaining, estimate_session_seconds, format_duration


class TestEstimator(unittest.TestCase):
    def test_eta_responds_to_wpm_punctuation_typos_bursts_and_thinking(self) -> None:
        base = TypingSettings(wpm=60, error_rate=0.0, thinking_pause_chance=0.0, burst_mode=False)
        plain = "hello world hello world"
        punct = "Hello, world! Next line?\nParagraph two."

        t_plain = estimate_session_seconds(plain, base)
        t_punct = estimate_session_seconds(punct, base)
        self.assertGreater(t_punct, t_plain)

        faster = TypingSettings(wpm=180, error_rate=0.0, thinking_pause_chance=0.0, burst_mode=False)
        self.assertLess(estimate_session_seconds(plain, faster), t_plain)

        with_typos = TypingSettings(wpm=60, error_rate=0.10, thinking_pause_chance=0.0)
        self.assertGreater(estimate_session_seconds(plain, with_typos), t_plain)

        with_burst = TypingSettings(
            wpm=60, error_rate=0.0, thinking_pause_chance=0.0, burst_mode=True, burst_chars=5, burst_pause=1.0
        )
        self.assertGreater(estimate_session_seconds(plain, with_burst), t_plain)

        with_think = TypingSettings(
            wpm=60, error_rate=0.0, thinking_pause_chance=0.15, thinking_pause_min=1.0, thinking_pause_max=2.0
        )
        self.assertGreater(estimate_session_seconds(plain, with_think), t_plain)

    def test_coding_mode_skips_symbol_typo_overhead(self) -> None:
        symbols = "{}[]()<>:=+-*/"
        code_no_err = TypingSettings(wpm=60, error_rate=0.0, thinking_pause_chance=0.0, coding_mode=True)
        code_hi_err = TypingSettings(wpm=60, error_rate=0.2, thinking_pause_chance=0.0, coding_mode=True)
        self.assertEqual(estimate_session_seconds(symbols, code_hi_err), estimate_session_seconds(symbols, code_no_err))

    def test_session_estimator_is_o1_and_consistent_on_long_text(self) -> None:
        text = ("The quick brown fox jumps over the lazy dog. " * 400).strip()  # ~18k chars
        s = TypingSettings(wpm=80, error_rate=0.03, burst_mode=True, burst_chars=10, burst_pause=0.4)
        est = SessionEstimator(text, s)
        self.assertAlmostEqual(est.remaining(0, 80), estimate_session_seconds(text, s), places=6)
        self.assertAlmostEqual(est.remaining(500, 80), estimate_remaining(text, 500, s), places=6)
        self.assertLess(est.remaining(500, 160), est.remaining(500, 80))

        t0 = time.perf_counter()
        for idx in range(len(text)):
            est.remaining(idx, 80)
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.25)

    def test_format_duration(self) -> None:
        self.assertEqual(format_duration(0), "0:00")
        self.assertEqual(format_duration(42), "0:42")
        self.assertEqual(format_duration(725), "12:05")
        self.assertEqual(format_duration(3753), "1:02:33")
