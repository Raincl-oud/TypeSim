"""Generate committed multi-resolution assets/typesim.ico from typesim.ui.icons."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtGui import QGuiApplication

from typesim.ui.icons import ICO_SIZES, write_ico_file


def main() -> int:
    _app = QGuiApplication(sys.argv)
    out = write_ico_file(ROOT / "assets" / "typesim.ico", ICO_SIZES)
    print(f"Wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
