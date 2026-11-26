# TypeSim v2.0 — Clean-Slate Overhaul Design Specification

**Date:** 2026-11-26  
**Project:** TypeSim (Windows Human-Like Typing Simulator)  
**Scope Size:** Full Project Overhaul (v1.1 → v2.0)  
**Status:** Approved & Grilled — Ready for Implementation Plan

---

## 1. General (Core Vision, Users & Boundaries)

### Core Purpose & Value
Rebuild **TypeSim** from the ground up while preserving its exact core working mechanism (*compose or paste text → select target window & countdown → simulate natural human typing → control via Floating HUD & global hotkeys + profile management*), upgrading three pillars simultaneously:
1. **Typing Realism:** Replace uniform random jitter and naive `a-z` typos with natural human cadence, QWERTY-adjacent error patterns, and instant interruptibility.
2. **Input Safety & Reliability:** Eliminate v1.1 bugs (Stop overwritten by Done, stale profile slider labels/hotkeys, blocking sleeps, clipboard race conditions, `F10`/`F11` leaking into apps) and introduce Win32 `SendInput` Unicode, Win32 `RegisterHotKey` interception, and Focus Guard protection.
3. **Modern Desktop Craft:** Replace the monolithic Tkinter UI with a modular, crisp, HiDPI PyQt6 workbench featuring Adaptive Light & Dark theming, a non-activating Compact Dynamic Pill HUD, System Tray standby, and purposeful tactile motion.

### Target Use Cases
- **Long-form documents & web editors:** Google Docs, Microsoft Word, Notion, browser forms, and textareas.
- **Live coding & technical demos:** IDEs (VS Code, JetBrains) and terminals involving indentation, symbols, brackets, and structured code blocks.

### Non-Goals & Anti-Goals
- **No Electron / heavy web runtime:** Must remain lightweight, start quickly, and bundle into a single portable Windows `.exe` via PyInstaller (~30–45 MB).
- **No Queue / Multi-Snippet macro sequencer:** Explicitly deferred outside v2 scope to keep the workflow lean.
- **No IDE auto-closing bracket/quote emulation:** Handling IDE auto-inserted closing brackets/quotes (`{}`, `()`, `""`) or auto-comment continuations is explicitly out of scope and left to the user's IDE settings (documented clearly in UI tooltip and README).
- **No mixed-language UI:** Strictly 100% English across every label, tooltip, toast, HUD state, and dialog.
- **No telemetry, network access, or mandatory Administrator privilege:** 100% offline; runs normally as a standard Windows user (warns clearly if targeting an elevated window blocked by Windows UIPI).
- **No breaking existing user data:** Must read and preserve compatibility with existing `~/.typesim/config.json` and `~/.typesim/profiles.json` files from v1.1.
- **No unnecessary visual clutter:** No dual-mode code editor (line-number gutter toggle) and no decorative rhythm-curve sparklines.

---

## 2. More Specific (Features, Flows, Edge Cases & Architecture)

### 2.1 Core (MVP) Capabilities

#### A. Modular Architecture
Replace the flat 5-file v1.1 layout with a cleanly decoupled package while keeping `main.py` as the thin entry point (preserving PyInstaller compatibility) and **removing `pynput` completely** in favor of native Win32 APIs:

```text
TypeSim/
├── main.py                     # Thin launcher (HiDPI, Qt app bootstrap)
├── typesim/
│   ├── __init__.py
│   ├── config.py               # TypingSettings + AppPreferences + v1.1-compatible atomic persistence
│   ├── profiles.py             # Built-in read-only presets + user custom profile CRUD
│   ├── win32_input.py          # Win32 SendInput Unicode/VK, window enumeration, focus, UIPI/terminal/OS checks
│   ├── engine.py               # Pure-Python TypingEngine state machine & realism engine (zero Qt dependency)
│   ├── estimator.py            # Realistic ETA calculator (WPM + cadence + typos + bursts + thinking pauses)
│   ├── hotkeys.py              # Win32 RegisterHotKey manager via QAbstractNativeEventFilter (WM_HOTKEY)
│   └── ui/
│       ├── theme.py            # Adaptive Light/Dark token palettes & QSS generator
│       ├── icons.py            # Authored monochrome SVG icon renderer tinted by active palette
│       ├── motion.py           # Reduced-motion-aware QPropertyAnimation & easing helpers
│       ├── widgets.py          # Shared switches, sliders, keycap badges, segmented controls, toast banner
│       ├── main_window.py      # Split Workbench + Settings views
│       ├── hud.py              # Frameless non-activating Compact Dynamic Pill HUD + Magnetic Edge-Snap
│       └── tray.py             # System Tray icon & standby menu
└── tests/                      # Unit tests for config/profile migration, engine state machine, realism, estimator, hotkeys
```

#### B. Advanced Human Realism Engine (`typesim/engine.py`)
- **Explicit State Machine:** `IDLE → COUNTDOWN → TYPING ↔ PAUSED → COMPLETED | STOPPED` (with `PAUSED → COUNTDOWN → TYPING` supported for Focus Guard resume countdowns).
  - Distinct terminal states (`COMPLETED` vs `STOPPED`) eliminate the v1.1 bug where clicking Stop caused the worker thread to emit `on_done` and jump the UI to `100% Done`.
  - Runs on an **isolated per-session `TypingSettings` snapshot** copied at `start()`, so live HUD speed tweaks never mutate or corrupt saved configuration.
- **Instant Interruptibility (<20 ms):** All countdown ticks, inter-key delays, burst pauses, and thinking pauses wait via `threading.Event.wait(timeout)` (never raw uninterruptible `time.sleep()`). Pause, Stop, and Focus Guard respond immediately.
- **Natural Cadence Timing Model:**
  - Base interval `60.0 / (max(10, wpm) * 5)` perturbed with a clamped Gaussian distribution (controlled by `variation`) instead of flat uniform noise.
  - Context-aware cadence multipliers: slight slowdown on shifted/uppercase/symbol keys (`+15–25%`), word boundaries/spaces (`+10–20%`), commas/semicolons (`+120–250 ms`), sentence-ending punctuation `.!?` (`+250–500 ms`), and paragraph newlines (`+350–700 ms`).
  - Preserves burst mode (`burst_chars`, `burst_pause`) and probabilistic thinking pauses (`thinking_pause_chance`, `thinking_pause_min..max` with `min <= max` enforced).
- **QWERTY-Adjacent Typo Simulator:**
  - Uses a physical QWERTY adjacency map preserving character casing for letters.
  - Weighted human error patterns: adjacent-key press + backspace (70%), adjacent-letter transposition `ab → ba` + 2 backspaces (20%), double-key tap `a → aa` + 1 backspace (10%).
  - Occasional realistic 1-character overshoot (~20% of adjacent-key typos: types the wrong key, types the next intended key before noticing, backspaces twice, retypes cleanly).
  - Never injects typos on whitespace, newlines, or control characters.
- **Coding / IDE-Safe Mode (`coding_mode: bool` + `strip_ide_auto_indent: bool`):**
  - Disables typos on non-alphanumeric symbols, brackets, quotes, operators, and leading indentation.
  - Normalizes `\r\n` and `\r` line endings to `\n` before execution.
  - **Terminal-Safe Auto-Indent Clearing (`strip_ide_auto_indent`, default `True` when `coding_mode` is ON, toggleable in Settings):**
    - Inspects `target_process_name` of the locked `target_hwnd`. If it matches a known terminal (`windowsterminal.exe`, `wt.exe`, `powershell.exe`, `pwsh.exe`, `cmd.exe`, `conhost.exe`, `mintty.exe`, `alacritty.exe`, `wezterm-gui.exe`), **skips** auto-indent clearing automatically.
    - For GUI IDEs/editors, right after sending `Enter` (`\n`), clears any IDE-inserted leading whitespace safely via `Shift+Home` → `Space` → `Backspace` before emitting the source line's exact indentation. *(Replacing any selected leading whitespace with `Space` followed by `Backspace` is a safe no-op even when the line is already at column 0 — never deleting the newline or the next line.)*
  - IDE auto-closing brackets/quotes remain out of scope and are documented cleanly in the Coding Mode tooltip and README.
- **Injectable Backend:** `TypingEngine` depends on an abstract `InputBackend` protocol, allowing fast, deterministic unit tests without sending real OS keystrokes.

#### C. Win32 Input Pipeline & Focus Guard (`typesim/win32_input.py`)
- **Primary Input Method — Win32 `SendInput` (`KEYEVENTF_UNICODE`):**
  - Encodes each character as UTF-16LE code units and dispatches `INPUT_KEYBOARD` events via `user32.SendInput`. Handles standard Unicode AND non-BMP emojis (UTF-16 surrogate pairs) directly **without touching or overwriting the Windows clipboard**.
  - Explicit virtual-key dispatch for `Enter`, `Tab`, `Space`, `Backspace`, and `Shift+Home`.
  - When a modifier-combo hotkey triggers typing with `countdown == 0`, briefly waits (up to 400 ms) for physical `Ctrl`/`Alt`/`Shift` keys (`GetAsyncKeyState`) to release before sending the first keystroke so modifiers don't collide with typed characters.
- **Optional Clipboard Fallback (`unicode_method == "clipboard"`):**
  - Retained as an explicit fallback option for legacy apps/remote desktops that ignore `KEYEVENTF_UNICODE`. Uses safer paste synchronization delay and best-effort text restore.
- **HWND-Based Window Tracking & Elevation Detection:**
  - Enumerates visible top-level windows as `WindowInfo(hwnd, title, process_name)` so duplicate window titles remain unambiguous.
  - Best-effort `is_window_elevated(hwnd)` check detects Administrator targets when TypeSim runs standard-privileged and displays a non-blocking inline warning explaining Windows UIPI restrictions.
- **Focus Guard Exact Semantics (`focus_guard: bool`, default `True`):**
  - When targeting a specific window, locks onto its `hwnd`. When using `<Active window when countdown ends>`, captures `target_hwnd = get_foreground_hwnd()` as countdown finishes.
  - **Missing/Invalid Target Guard:** If countdown finishes with no valid external foreground window (e.g., `countdown == 0` while TypeSim itself is focused), or if `target_hwnd` is closed/destroyed (`not IsWindow(target_hwnd)`) during typing or pause, aborts cleanly to `STOPPED` and shows an explanatory toast (*"Target window unavailable — typing stopped"*).
  - **Focus-Lost Detection:** Before dispatching keystrokes, checks `get_foreground_hwnd() == target_hwnd`. If focus leaves `target_hwnd`, immediately pauses (`PAUSE_REASON_FOCUS_LOST`), turns HUD status amber (**"Focus Lost"**), and highlights **"Focus & Resume"**.
  - **Resume Rules:**
    - Manually clicking back into `target_hwnd` keeps the session safely `PAUSED` (never surprise-types without user action).
    - Clicking HUD **"Focus & Resume"** or pressing `Start/Resume` (`F9`) while `PAUSE_REASON_FOCUS_LOST` calls robust Win32 `focus_window(target_hwnd)` (`SW_RESTORE` if minimized + foreground-lock fallback), verifies focus succeeded (aborting cleanly to `STOPPED` if window closed), runs `focus_resume_countdown` (default `2s`, configurable `1–3s`) via `PAUSED → COUNTDOWN → TYPING`, and resumes at the exact next character index.
    - Resuming from a **manual pause** (`F10` / HUD Pause) while `target_hwnd` is already foreground resumes **immediately (`0s` countdown)**; if focus moved while manually paused, runs the same Focus & Resume sequence (`focus_window` + `focus_resume_countdown`).

#### D. Global Hotkeys via Win32 `RegisterHotKey` (`typesim/hotkeys.py`)
- Uses native Win32 `RegisterHotKey` / `UnregisterHotKey` integrated with PyQt6 via `QAbstractNativeEventFilter` listening for `WM_HOTKEY` — **intercepts and consumes** hotkey presses so `F11` never triggers browser/VS Code fullscreen and `F10` never traps focus in menu bars.
- **Drops `pynput` dependency completely** (no low-level keyboard hook thread, leaner `.exe`, fewer antivirus false positives).
- Supports both single keys (`F9`, `F10`, `F11`, `Home`, `Insert`, `Pause`) and modifier combinations (`Ctrl+Shift+F9`, `Alt+F10`, etc.), remaining backward-compatible with v1.1 single-key lowercase strings (`"f9"`, `"f10"`, `"f11"`).
- Validates format, rejects duplicate bindings across Start/Pause/Stop, immediately re-registers when changed or when loading a profile, and displays a clear inline conflict warning in Settings if another Windows app already claimed a requested hotkey.

#### E. Config, Built-in Presets & Profile Persistence Contract (`typesim/config.py`, `typesim/profiles.py`)
- **Strict Separation of Domains (Our Call — Resolved from Builder Check):**
  - **`TypingSettings` (saved in Custom Profiles & `~/.typesim/config.json`):** `wpm`, `variation`, `error_rate`, `error_correction_delay`, `thinking_pause_chance`, `thinking_pause_min`, `thinking_pause_max`, `burst_mode`, `burst_chars`, `burst_pause`, `unicode_method`, `countdown`, `coding_mode`, `strip_ide_auto_indent`, `focus_guard`, `focus_resume_countdown`, `hotkey_start`, `hotkey_pause`, `hotkey_stop`.
  - **`AppPreferences` (saved in `~/.typesim/config.json`, NEVER overwritten by Profiles or Presets):** `theme_mode` (`"system" | "light" | "dark"`), `close_to_tray` (`bool`), `hud_anchor` (`str`, e.g., `"top-center"`).
- **Immediate Auto-Save:** All edits in Workbench and Settings auto-save directly to `~/.typesim/config.json` via atomic temp-file + `os.replace` (slider drags debounced ~250 ms; toggles/combos/hotkeys/theme/HUD anchor saved immediately). No redundant "Save All Settings" button is required.
- **4 Built-in Read-Only Presets** (apply full cohesive realism parameters including resetting `burst_mode=False`, `error_correction_delay`, `thinking_pause_min/max`, `coding_mode`; never touch hotkeys or `AppPreferences`):
  - `Casual`: 45 WPM, 28% variation, 4.0% typo, 0.22s correction, 3.0% thinking pause (0.7–2.5s), burst off, coding off.
  - `Natural` *(default)*: 65 WPM, 20% variation, 2.5% typo, 0.15s correction, 2.0% thinking pause (0.5–2.0s), burst off, coding off.
  - `Fast`: 110 WPM, 15% variation, 1.5% typo, 0.10s correction, 1.0% thinking pause (0.3–1.2s), burst off, coding off.
  - `Precision Code`: 85 WPM, 12% variation, 0.0% typo, 0.10s correction, 0.5% thinking pause (0.3–1.0s), burst off, **Coding Mode ON** (`strip_ide_auto_indent=True`).
- **Custom User Profiles (`~/.typesim/profiles.json`):** Save, load, overwrite, and delete user profiles (saving only `TypingSettings`). Loading a profile syncs every slider, readout label, toggle, **and reloads `RegisterHotKey`**.
- **v1.1 Backward Compatibility:**
  - Reads flat v1.1 `~/.typesim/config.json` and `~/.typesim/profiles.json` directly on startup.
  - Preserves all 15 v1.1 keys in JSON output; transparently accepts legacy `unicode_method: "pynput"` as Win32 `SendInput` (`"sendinput"`) while keeping `"clipboard"` intact.
  - When loading a legacy v1.1 profile missing v2 fields (`coding_mode`, `strip_ide_auto_indent`, `focus_guard`, `focus_resume_countdown`), fills those with safe v2 defaults (`False`, `True`, `True`, `2`) without touching `AppPreferences`.

---

### 2.2 Selected Expansion Features (In Scope for v2.0)

1. **Session-Only Live Speed Control & 1-Line Preview in Floating HUD:**
   - `-` / `+` WPM stepper (±10 WPM per click, range `10–400`) adjusts only the active `TypingEngine` session snapshot — never mutating or persisting the user's saved preset or Workbench WPM slider.
   - Single-line live text preview shows recent typed context (muted) + current/upcoming slice (high contrast), rendering `\n` as `↵` and `\t` as `⇥` so HUD height never shifts.
2. **Realistic ETA Estimator & Session Summary (`typesim/estimator.py`):**
   - Calculates realistic duration factoring in WPM, punctuation/newline cadence weights, expected typo correction overhead, burst pauses, and expected thinking pauses.
   - Live ETA recalculates immediately when live WPM changes on the HUD.
   - On `COMPLETED`, displays a non-blocking **Session Summary** toast (characters typed, actual elapsed time, effective WPM, typos corrected).
3. **System Tray Icon & Background Standby (`typesim/ui/tray.py`):**
   - Persistent tray icon with context menu (*Open TypeSim*, *Start Typing (F9)*, *Pause / Resume*, *Stop*, *Quit*).
   - Enables standby workflow: user can keep TypeSim minimized to tray and trigger typing anytime with `F9`; Floating HUD appears during typing, and after completion TypeSim returns cleanly to tray standby (if launched from tray) or restores the main window (if launched from visible window).

---

### 2.3 Technical Approaches Considered & Chosen Decision

| Approach | Summary | Verdict |
|---|---|---|
| **Python + PyQt6 + Win32 `SendInput` & `RegisterHotKey` (`ctypes`)** | Native HiDPI desktop UI, true frameless rounded HUD with `WindowDoesNotAcceptFocus` + `WS_EX_NOACTIVATE`, hotkey interception without `pynput`, smooth `QPropertyAnimation`, native tray icon, 1-file `.exe` ~35–45 MB (`PyQt6 6.12.1` already installed). | **Chosen (Recommended)** |
| **Python + Tkinter/ttk refactor** | Smallest `.exe` (~15 MB), zero GUI dependencies, but lacks native rounded HUD, clean HiDPI scaling, smooth animations, and modern controls. | Rejected |
| **Python + `pywebview` (WebView2)** | Full HTML/CSS styling (~20 MB `.exe`), but JS↔Python IPC overhead and non-activating always-on-top multi-window Floating HUD focus behavior are brittle on Windows. | Rejected |

**Runtime Dependencies (`requirements.txt`):** `PyQt6>=6.6.0`, `pywin32>=306`, `pyperclip>=1.8.2` (`pynput` removed).

---

## 3. Themes & Design (Operate Mode — Impeccable Craft)

### Visual Direction & Mode
- **Surface Mode:** **Operate** — scanability, earned familiarity, precision, and restraint. The tool disappears into the user's document or coding session.
- **Theme Strategy:** **Adaptive Light & Dark** — automatically reads Windows `AppsUseLightTheme` on launch, with a 1-click theme toggle in the header and full `System` / `Light` / `Dark` selector in Settings.

### Color System (WCAG AA ≥ 4.5:1 Verified Targets)

| Token | Dark Mode | Light Mode | Role |
|---|---|---|---|
| `bg_canvas` | `#111318` | `#F5F6F8` | Primary window canvas |
| `bg_surface` | `#171A21` | `#FFFFFF` | Right control panel, settings sections, editor container |
| `bg_elevated` | `#1E222B` | `#FFFFFF` | Floating HUD pill, dropdown popups, toasts |
| `bg_subtle` | `#232834` | `#ECEFF4` | Hover fills, keycap badges, slider troughs |
| `border` | `#2B3140` | `#DCE1E9` | 1px crisp structural hairlines |
| `text_primary` | `#ECEFF4` | `#14181F` | Headings, editor text, active controls |
| `text_secondary` | `#9CA6B8` | `#525E70` | Labels, telemetry, inactive tabs |
| `text_muted` | `#6E788B` | `#7A8699` | Placeholders, typed HUD preview prefix |
| `accent` | `#3B82F6` | `#2563EB` | Primary CTA (Start), active toggles, progress fill |
| `accent_hover` | `#2563EB` | `#1D4ED8` | Primary CTA hover |
| `state_active` | `#22C55E` | `#16A34A` | Actively typing indicator, completion toast |
| `state_warning` | `#F59E0B` | `#D97706` | Paused, Countdown, Focus Lost highlight |
| `state_danger` | `#EF4444` | `#DC2626` | Stop action, destructive delete |

*Design discipline:* No neon shadows, no gradient borders (removes v1.1 `GradientCanvas`), no nested card stacks, no kickers/eyebrows, no colored left-border callouts >1px.

### Typography
- **UI Sans:** `Segoe UI Variable Text`, fallback `Segoe UI`.
- **Monospace (Data & Keycaps Only):** `Cascadia Mono`, fallback `Consolas` — strictly for keycap badges (`F9`, `F10`, `F11`), tabular numeric readouts (WPM, char/word counts, ETA), and the 1-line HUD text preview.
- **Scale:** Brand `14px SemiBold`, section labels `12px SemiBold`, body/editor/controls `13px Regular`, badges/captions `11px Medium`.

### Layout Architecture — Split Workbench
- **Window Dimensions:** Default `880×580`, minimum `740×500`.
- **Top Header Bar (`48px`):**
  - Left: Custom SVG TypeSim mark + `TypeSim` title + segmented view switcher (`Workbench` | `Settings`).
  - Right: Instant Light/Dark toggle button, Tray standby button, primary **Start** button with inline `F9` keycap badge.
- **Workbench View (2-Column Split, ~64% Left / ~36% Right):**
  - **Left Column (Compose & Target):**
    - Full-height `QPlainTextEdit` with word-processor shortcuts (`Ctrl+A/Z/Y`, `Ctrl+Backspace`, `Ctrl+Delete`, `Shift+Delete`, native styled context menu) and helpful empty-state placeholder.
    - Compact telemetry bar directly beneath editor (`0 chars · 0 words · ETA: --` in tabular numerals + `Clear` button).
    - Target Window bar (`<Active window when countdown ends>` or `Title — process.exe` combobox + SVG Refresh button + conditional UIPI elevation warning).
  - **Right Column (Quick Control Panel):**
    - **Presets:** 2×2 preset grid (`Casual`, `Natural`, `Fast`, `Precision Code`) + compact Saved Profile dropdown.
    - **Typing Speed:** WPM slider (`10–400`) with tabular numeric readout.
    - **Quick Modes:** Toggle switches for `Coding / IDE-Safe`, `Focus Guard`, and `Burst Mode`, plus compact `Countdown` stepper (`0–10s`).
    - **Hotkeys Strip:** Read-only keycap reference (`F9 Start` · `F10 Pause` · `F11 Stop`).
- **Settings View (Organized Scroll Area — Scroll Isolated to Viewport):**
  - Grouped sections separated by crisp hairlines (all auto-saving cleanly): **Realism & Timing**, **Input & Coding** (`SendInput` vs `Clipboard`, *Strip IDE auto-indent on newline*, Focus Guard resume countdown), **Typing Profiles** (Save / Load / Delete), **Global Hotkeys** (with inline conflict warnings), and **Application & About**.

### Floating HUD — Compact Dynamic Pill
- **Geometry & Window Flags:** Frameless, rounded (`16px` radius), ~`560×62px`, `Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus`, `Qt.WidgetAttribute.WA_ShowWithoutActivating`, reinforced with Win32 `GWL_EXSTYLE |= WS_EX_NOACTIVATE` so clicking any HUD button never steals focus from the target application.
- **Contents:**
  - Left: Status dot + concise state label (`Starting 2s` / `Typing` / `Paused` / `Focus Lost`).
  - Center: Single-line clipped live text preview (`...done` muted | `next...` primary).
  - Right: Compact `-` `65 WPM` `+` session-only stepper, `Pause` / `Resume` / **`Focus & Resume`** (amber emphasis on focus loss), and `Stop` icon button.
  - Footer: Integrated `3px` edge-to-edge progress bar + compact tabular ETA tag.
- **Iconography:** Custom monochrome SVG icons (`1.5px` stroke) stored inline in `typesim/ui/icons.py` and recolored dynamically per theme token — zero emoji/Unicode icons.

---

## 4. Animation & Motion (Emil Kowalski Philosophy)

### Personality & Restraint
- **Personality:** **Tactile & Fluid** (`180–240 ms` UI transitions using custom strong ease-out `cubic-bezier(0.23, 1, 0.32, 1)` and `InOutCubic` for on-screen glides).
- **Strict Non-Animated Paths (0 ms Delay):**
  - Global hotkey triggers (`F9` / `F10` / `F11`) invoke engine state changes immediately.
  - Live HUD text preview character advancement and slider value drag updates render instantaneously without lag.
  - No startup splash or choreographed window-load animation.

### Authored Motion Moments
1. **[Core] Floating HUD Entry & Exit:** Symmetric vertical slide (`14px` from/toward nearest edge) + window opacity (`0.0 → 0.96`), `220 ms`, strong ease-out (`0.23, 1, 0.32, 1`). Fully interruptible if Stop is triggered mid-entry.
2. **[Core] Focus Guard State Cue:** `180 ms` border/accent tint transition to semantic amber + smooth reveal of the **Focus & Resume** pill action when focus is lost (no blocking modal dialogs).
3. **[Core] Non-Blocking Toast Banner:** Slides `10px` upward + fades in (`200 ms` ease-out) for status notifications (*Profile saved*, *Target unavailable*, **Session Summary**); retargets smoothly from current animation value if triggered rapidly.
4. **[Expansion] Magnetic Edge-Snap (HUD Drag):** Dragging the HUD follows the pointer 1:1; on mouse release within `24px` of screen edges/corners (using current `QScreen.availableGeometry()`), smoothly animates `pos` to the nearest anchor (`220 ms`, strong ease-out), immediately interruptible if grabbed again. Persists last anchor in `AppPreferences`.
5. **[Expansion] Active Control Indicator & Typing Pulse:** Smooth sliding highlight (`200 ms` `InOutCubic`) for segmented `Workbench`/`Settings` switch and active preset button; subtle breathing opacity pulse (`1600 ms` sine) on the green HUD status dot strictly while `TYPING` (halts immediately when paused, focus-lost, or stopped).

### Accessibility & Reduced Motion
- Queries Windows `SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION)` at startup and updates on `WM_SETTINGCHANGE`.
- When Windows animations are disabled: all slides, edge-snap glides, and dot pulses automatically degrade to gentle `120 ms` opacity fades or instant switches.

---

## 5. Settled `/grill-me` Decisions
- **Close Button (`X`) & Tray Standby Summary:** Default `close_to_tray = False` (clicking `X` exits cleanly; dedicated *Minimize to Tray* button in header + `Close to Tray` toggle in Settings). When a session completes from Tray Standby, the Floating HUD morphs into a brief 3-second green summary pill (`Done · N chars · duration · avg WPM`) before sliding out; when triggered from a visible window, the HUD slides out immediately, the main window restores, and the non-blocking Session Summary toast appears.
- **Global Hotkey Editing UX:** Settings uses a **Key-Capture Recorder** button per binding (click → press single key or `Ctrl/Alt/Shift + Key`; `Esc` cancels; includes *Reset Defaults*). Active Win32 `RegisterHotKey` bindings pause temporarily while capturing so pressing `F9` records `"f9"` instead of firing Start.
- **Editor Text Persistence & Privacy:** Editor text remains intact in memory across runs during a session, but is **never persisted to disk** — TypeSim always opens with a clean, empty editor on restart to protect sensitive text/code.

## 6. Open / Left to Builder
- Exact PyInstaller `.spec` / CLI exclusion flags (`--exclude-module` for unused Qt modules like `QtWebEngine`, `QtMultimedia`, `QtSql`, `QtQml`, `QtQuick`) to keep single-file `.exe` compact.
- Exact QWERTY neighbor tables and per-punctuation cadence tuning constants (validated via deterministic seeded unit tests).
- Updating [.github/workflows/release.yml](file:///c:/Users/Muhamad%20Rafif%20I/Documents/antigravity/TypeSim/.github/workflows/release.yml) for Python 3.12 + PyQt6 packaging (removing `pynput`) and completing the truncated [README.md](file:///c:/Users/Muhamad%20Rafif%20I/Documents/antigravity/TypeSim/README.md).
- Unit test fixtures and mock `InputBackend` design under `tests/`.
