"""TypeSim v2.0 thin PyQt6 entry point."""

from __future__ import annotations

import ctypes
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from typesim import __version__
from typesim.ui.icons import app_icon
from typesim.ui.main_window import MainWindow


def _set_app_user_model_id() -> None:
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = (ctypes.c_wchar_p,)
        shell32.SetCurrentProcessExplicitAppUserModelID(f"TypeSim.Desktop.{__version__}")
    except OSError:
        pass


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    _set_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName("TypeSim")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
