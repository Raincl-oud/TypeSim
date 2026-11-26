# Version Tracker

Current: **2.14.7**

## History
- 2026-11-27 | **2.14.7** (from 2.14.6) | `+0M +0m +1f` | Fix Windows Explorer ICO DIB encoding and icon cache refresh
  - `fix`: Encode sub-256px ICO frames as standard Win32 32-bpp BGRA BITMAPINFOHEADER DIBs with 16px dark-Explorer rim contrast
- 2026-11-27 | **2.14.6** (from 2.9.5) | `+0M +5m +1f` | Tactile 3D Keycap T_ app icon and Smooth & Silky motion overhaul
  - `fix`: Fix missing Windows executable icon and upgrade app brand mark to a 7-size Tactile 3D Keycap "T_" icon (16-256px assets/typesim.ico)
  - `minor`: Add live status dot badges on the System Tray icon for Typing and Paused/Countdown states
  - `minor`: Add directional Workbench-Settings view transitions and non-uniform staggered Settings card cascade
  - `minor`: Add smooth Light-Dark theme crossfade and rotating Sun-Moon and Refresh icon animations
  - `minor`: Add silky preset slider glide, tactile hover/press feedback, collapsible warning banners, hotkey capture pulse, and smooth tray window restore
  - `minor`: Add living Floating HUD animations (interpolated progress bar with completion sweep, breathing/gliding preview caret, countdown tick fade, and mode crossfades)
- 2026-11-26 | **2.9.5** (from 1.1.0) | `+1M +8m +5f` | TypeSim v2 clean-slate overhaul
  - `major`: Replace legacy root modules and pynput dependency with modular typesim package, PyQt6 UI, and native Win32 SendInput/RegisterHotKey
  - `minor`: Add natural human cadence engine with Gaussian timing, contextual punctuation/newline pauses, and QWERTY-adjacent typos
  - `minor`: Add Win32 SendInput UTF-16LE Unicode pipeline supporting non-BMP emojis without modifying the clipboard
  - `minor`: Add HWND-based Focus Guard with auto-pause on focus loss, Focus & Resume countdown, and UIPI elevation warning
  - `minor`: Add Coding / IDE-Safe Mode with symbol/indent typo suppression and terminal-aware IDE auto-indent clearing
  - `minor`: Add Win32 RegisterHotKey global hotkey interception with modifier-combo support and click-to-record Key-Capture
  - `minor`: Add Built-in Presets (Casual, Natural, Fast, Precision Code) and v1.1-compatible atomic profile/config persistence
  - `minor`: Add Adaptive Light & Dark PyQt6 Split Workbench UI with custom SVG icons and O(1) realistic ETA estimator
  - `minor`: Add non-activating Compact Dynamic Pill Floating HUD (live WPM stepper, 1-line preview, Magnetic Edge-Snap, 3s tray summary) and System Tray standby
  - `fix`: Fix Stop action being overwritten by completion callback and jumping progress to 100%
  - `fix`: Fix uninterruptible multi-second sleep calls blocking Pause and Stop via HybridSleeper (<20ms response)
  - `fix`: Fix loading a profile leaving slider value labels and active global hotkeys stale
  - `fix`: Fix F10 and F11 global hotkeys leaking into target applications
  - `fix`: Fix inverted thinking_pause_min/max bounds and per-character clipboard race condition
- 2026-09-08 | **1.1.0** (initial) | `init` | Legacy TypeSim v1.1 Tkinter baseline
