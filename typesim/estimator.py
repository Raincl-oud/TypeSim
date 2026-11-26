"""Cadence model (shared by the engine and the ETA estimator) and O(1) suffix session estimation."""

from __future__ import annotations

import random

from .config import TypingSettings

_ROWS = ("1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm")


def _build_neighbors() -> dict[str, str]:
    pos = {c: (r, i + (0.0, 0.5, 0.75, 1.25)[r]) for r, row in enumerate(_ROWS) for i, c in enumerate(row)}
    out = {}
    for c, (r, x) in pos.items():
        near = [o for o, (r2, x2) in pos.items() if o != c and abs(r2 - r) <= 1 and abs(x2 - x) <= 1.0]
        out[c] = "".join(sorted(near))
    return out


QWERTY_NEIGHBORS = _build_neighbors()
SHIFTED_SYMBOLS = frozenset('~!@#$%^&*()_+{}|:"<>?')


def base_interval(wpm: int) -> float:
    return 60.0 / (max(10, wpm) * 5)


def typo_eligible(ch: str, coding_mode: bool) -> bool:
    if ch.lower() not in QWERTY_NEIGHBORS:
        return False
    return ch.isalnum() if coding_mode else True


def _context(ch: str, prev: str) -> tuple[tuple[float, float], tuple[float, float]]:
    """(multiplier range, additive-seconds range) for typing `ch` right after `prev`."""
    mult = (1.15, 1.25) if ch.isupper() or ch in SHIFTED_SYMBOLS else (1.10, 1.20) if ch == " " else (1.0, 1.0)
    if prev == "\n":
        add = (0.35, 0.70)
    elif prev in (".", "!", "?"):
        add = (0.25, 0.50)
    elif prev in (",", ";", ":"):
        add = (0.12, 0.25)
    else:
        add = (0.0, 0.0)
    return mult, add


def expected_delay(ch: str, prev: str, s: TypingSettings) -> float:
    (m0, m1), (a0, a1) = _context(ch, prev)
    return base_interval(s.wpm) * (m0 + m1) / 2 + (a0 + a1) / 2


def sample_delay(ch: str, prev: str, s: TypingSettings, rng: random.Random) -> float:
    (m0, m1), (a0, a1) = _context(ch, prev)
    base = base_interval(s.wpm)
    v = s.variation
    jitter = min(1 + 2 * v, max(1 - 2 * v, rng.gauss(1.0, v)))
    return max(0.25 * base, base * jitter * rng.uniform(m0, m1)) + rng.uniform(a0, a1)


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


class SessionEstimator:
    """Precomputes O(N) suffix costs once so per-character remaining ETA queries run in O(1)."""

    def __init__(self, text: str, s: TypingSettings) -> None:
        norm = normalize_text(text)
        n = len(norm)
        self._n = n
        units = [0.0] * (n + 1)
        fixed = [0.0] * (n + 1)
        think_avg = s.thinking_pause_chance * (s.thinking_pause_min + s.thinking_pause_max) / 2
        for i in range(n - 1, -1, -1):
            ch = norm[i]
            prev = norm[i - 1] if i else ""
            (m0, m1), (a0, a1) = _context(ch, prev)
            u = (m0 + m1) / 2
            f = (a0 + a1) / 2
            if typo_eligible(ch, s.coding_mode):
                u += s.error_rate * 2.3
                f += s.error_rate * s.error_correction_delay
            if ch == " ":
                f += think_avg
            if s.burst_mode and i > 0 and i % s.burst_chars == 0:
                f += s.burst_pause
            units[i] = units[i + 1] + u
            fixed[i] = fixed[i + 1] + f
        self._units = units
        self._fixed = fixed

    def remaining(self, index: int, wpm: int) -> float:
        idx = min(self._n, max(0, index))
        return base_interval(wpm) * self._units[idx] + self._fixed[idx]


def estimate_remaining(text: str, index: int, s: TypingSettings) -> float:
    """Expected seconds to type text[index:], including typo, burst and thinking overhead."""
    return SessionEstimator(text, s).remaining(index, s.wpm)


def estimate_session_seconds(text: str, s: TypingSettings) -> float:
    return estimate_remaining(text, 0, s)


def format_duration(seconds: float) -> str:
    """'0:42', '12:05', '1:02:33'."""
    n = max(0, int(round(seconds)))
    h, rem = divmod(n, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
