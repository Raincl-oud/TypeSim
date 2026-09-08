# TypeSim ⌨️

**An advanced, human-like typing simulation utility for Windows.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)](https://www.microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Build Status](https://img.shields.io/github/actions/workflow/status/Raincl-oud/TypeSimhttps://github.com/Raincl-oud/TypeSim/workflows//release.yml?branch=main)](https://github.com/Raincl-oud/TypeSim/actions)

## 📌 Overview

*TypeSim* simulates natural, human keyboard input directly into any active Windows application. Unlike rudimentary auto-typers that inject bulk text instantaneously, TypeSim accurately mirrors natural typing patterns, including keystroke latency jitter, periodic cognitive pauses, configurable bursts, simulated typographic errors with automatic backspace corrections, and non-BMP Unicode / Emoji fallback handling.

## ✨ Key Features
- **Natural Human Behavior Emulation**:
  - Configurable Words Per Minute (WPM: 10 - 400).
  - Keystroke latency variance (Jitter).
  - Simulates typos and correction delays.
  - Burst-typing cycles and randomized cognitive thinking pauses.
- **Robust Input Pipeline**:
  - Raw hardware scan-code typing via `pynput`.
  - Automated clipboard fallback for emojis, non-BMP characters, and international unicode.
- **Word-Processor-Grade Editor**:
  - Context menu (`Cut`, `Copy`, `Paste`, `Select All`).
  - Word navigation & deletions (`Ctrl + Backspace`, `Ctrl + Delete`).
  - Integrated Undo/Redo (`Ctrl + Z`, `Ctrl + Y`).
  - Instant line deletion (`Shift + Delete`).
- **Floating HUD & Minimalist Execution**:
  - Minimizes main application upon start.
  - Displays a top-level, non-intrusive floating progress bar with real-time ETA and Pause/Stop controls.
- **Profile Management**:
  - Save, load, and switch between customized speed and behavioral configurations.
- **Global Hotkeys**:
  - Control simulations in background applications using customizable global shortcuts.
---
## ⌨️ Default Hotkeys
| Hotkey | Action | Scope |
| :--- | :--- | :--- |
| **`F9`** | Start / Resume typing | System-wide Global |
| **`F10`** | Pause typing | System-wide Global |
| **`F11`** | Abort / Stop typing | System-wide Global |

---
## 🚀 Getting Started
### Prerequisites
- **OS**: Windows 10 or Windows 11
- **Python**: Version 3.10 or higher
### Installation
