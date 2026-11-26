# TypeSim

**A lightweight, human-like typing simulator for Windows 10 and Windows 11.**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Platform Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)](https://www.microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Build Status](https://img.shields.io/github/actions/workflow/status/Raincl-oud/TypeSim/release.yml?branch=main)](https://github.com/Raincl-oud/TypeSim/actions)

---

## Overview

**TypeSim** types text into any Windows application with realistic human cadence, QWERTY-adjacent error patterns, Focus Guard protection, and native Win32 input & global hotkey interception.

### Key Features

- **Natural Human Cadence Engine**:
  - Configurable typing speed (`10–400 WPM`), clamped Gaussian variation, and context-aware pauses after commas, sentence endings, shifted symbols, and paragraphs.
  - Physical **QWERTY-adjacent typo simulation** preserving casing (adjacent key miss with occasional 1-char overshoot, adjacent letter transposition, and double taps) plus configurable correction delay.
  - Burst-typing cycles and probabilistic thinking pauses.
  - Realistic session **ETA estimator** factoring punctuation cadence, typo corrections, bursts, and thinking pauses.
- **Native Win32 Input & Focus Guard**:
  - Direct Win32 `SendInput` (`KEYEVENTF_UNICODE`) supporting Unicode and non-BMP emojis without touching your clipboard (with an optional clipboard fallback for remote desktops).
  - **HWND-backed target locking** with **Focus Guard**: pauses automatically if focus leaves your target window, surfaces **Focus & Resume** on the Floating HUD, and notifies you if a target runs elevated (Windows UIPI).
- **Coding / IDE-Safe Mode**:
  - Disables typos on symbols, brackets, operators, and leading indentation.
  - Clears IDE-inserted auto-indent safely via `Shift+Home -> Space -> Backspace` after newlines (automatically skipped for terminal processes such as Windows Terminal, PowerShell, `cmd`, Alacritty, and WezTerm).
  - *Note:* IDE auto-closing brackets/quotes (`{}`, `()`, `""`) remain controlled by your IDE settings.
- **Modern PyQt6 Workbench & Dynamic Pill HUD**:
  - Adaptive Light & Dark theme following Windows settings (or toggled in 1 click).
  - Word-processor shortcuts (`Ctrl+A/Z/Y`, `Ctrl+Backspace`, `Ctrl+Delete`, `Shift+Delete`) in an ephemeral compose editor (editor contents are never written to disk).
  - Frameless, non-activating **Floating HUD** (`WS_EX_NOACTIVATE`) with live 1-line preview, session-only `-` / `+` WPM stepper, integrated progress bar, and Magnetic Edge-Snap.
  - **System Tray standby** for triggering typing anytime from the background.
- **Native Global Hotkeys (`RegisterHotKey`)**:
  - Intercepts and consumes hotkeys cleanly at the OS level so keys like `F10` or `F11` never leak into browsers or IDEs.
  - Supports single keys and modifier combinations (`Ctrl+Shift+F9`, etc.) via click-to-record Key Capture in Settings.
- **Presets & Backward-Compatible Profiles**:
  - Built-in presets (**Casual**, **Natural**, **Fast**, **Precision Code**) and custom user profiles stored atomically under `~/.typesim/` (fully compatible with v1.1 `config.json` and `profiles.json`).

---

## Default Hotkeys

| Hotkey | Action | Scope |
| :--- | :--- | :--- |
| **`F9`** | Start / Focus & Resume | Global (`RegisterHotKey`) |
| **`F10`** | Pause / Resume | Global (`RegisterHotKey`) |
| **`F11`** | Stop typing | Global (`RegisterHotKey`) |

---

## Getting Started

### Prerequisites

- **OS**: Windows 10 or Windows 11
- **Python**: Version 3.12 or higher (when running from source)

### Installation

```powershell
git clone https://github.com/Raincl-oud/TypeSim.git
cd TypeSim
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

### Running Tests

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -s tests -v
```

### Building a Standalone Executable

```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --name TypeSim `
  --icon assets/typesim.ico --add-data "assets/typesim.ico;assets" `
  --exclude-module tkinter --exclude-module pynput --exclude-module tests --exclude-module tools `
  --exclude-module PyQt6.QtWebEngineCore --exclude-module PyQt6.QtWebEngineWidgets `
  --exclude-module PyQt6.QtMultimedia --exclude-module PyQt6.QtQml --exclude-module PyQt6.QtQuick `
  main.py
```

The standalone executable will be generated at `dist\TypeSim.exe`.
