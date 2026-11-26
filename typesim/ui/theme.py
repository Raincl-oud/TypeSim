"""Adaptive Light & Dark palette tokens and cohesive Operate-mode QSS generation."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QGuiApplication

from ..win32_input import system_prefers_dark_theme

UI_FAMILIES = ("Segoe UI Variable Text", "Segoe UI", "Sans Serif")
MONO_FAMILIES = ("Cascadia Mono", "Consolas", "Monospace")


@dataclass(frozen=True)
class ThemePalette:
    mode: str
    bg_canvas: str
    bg_surface: str
    bg_elevated: str
    bg_subtle: str
    bg_hover: str
    border: str
    border_strong: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_tint: str
    accent_text: str
    btn_primary: str
    btn_primary_hover: str
    on_accent: str
    state_active: str
    state_active_text: str
    state_active_tint: str
    state_warning: str
    state_warning_text: str
    state_warning_tint: str
    btn_warning: str
    btn_warning_hover: str
    on_warning: str
    state_danger: str
    state_danger_text: str
    state_danger_tint: str
    on_danger: str
    hud_border: str


DARK_PALETTE = ThemePalette(
    mode="dark",
    bg_canvas="#111318",
    bg_surface="#171A21",
    bg_elevated="#1E222B",
    bg_subtle="#232834",
    bg_hover="#2A3040",
    border="#2B3140",
    border_strong="#3B4357",
    text_primary="#ECEFF4",
    text_secondary="#9CA6B8",
    text_muted="#808B9F",  # >= 4.6:1 AA on surface & elevated
    accent="#3B82F6",
    accent_hover="#2563EB",
    accent_tint="#1D2C46",
    accent_text="#60A5FA",  # >= 5.8:1 AA on #1D2C46
    btn_primary="#2563EB",  # >= 5.1:1 AA with #FFFFFF label
    btn_primary_hover="#1D4ED8",
    on_accent="#FFFFFF",
    state_active="#22C55E",
    state_active_text="#4ADE80",
    state_active_tint="#162B22",
    state_warning="#F59E0B",
    state_warning_text="#FBBF24",
    state_warning_tint="#2E2312",
    btn_warning="#F59E0B",
    btn_warning_hover="#FBBF24",
    on_warning="#111318",
    state_danger="#EF4444",
    state_danger_text="#F87171",
    state_danger_tint="#2D181C",
    on_danger="#FFFFFF",
    hud_border="#333B4D",
)

LIGHT_PALETTE = ThemePalette(
    mode="light",
    bg_canvas="#F5F6F8",
    bg_surface="#FFFFFF",
    bg_elevated="#FFFFFF",
    bg_subtle="#ECEFF4",
    bg_hover="#E2E7EF",
    border="#DCE1E9",
    border_strong="#C3CCD9",
    text_primary="#14181F",
    text_secondary="#525E70",
    text_muted="#626E80",  # >= 4.78:1 AA on canvas & white
    accent="#2563EB",
    accent_hover="#1D4ED8",
    accent_tint="#EBF2FE",
    accent_text="#1D4ED8",  # >= 6.1:1 AA on #EBF2FE
    btn_primary="#2563EB",
    btn_primary_hover="#1D4ED8",
    on_accent="#FFFFFF",
    state_active="#16A34A",
    state_active_text="#15803D",
    state_active_tint="#EAF7EE",
    state_warning="#D97706",
    state_warning_text="#B45309",
    state_warning_tint="#FEF5E7",
    btn_warning="#B45309",  # >= 5.02:1 AA with #FFFFFF label
    btn_warning_hover="#92400E",
    on_warning="#FFFFFF",
    state_danger="#DC2626",
    state_danger_text="#B91C1C",
    state_danger_tint="#FDECEC",
    on_danger="#FFFFFF",
    hud_border="#CFD6E2",
)


def resolve_theme(mode: str, app: QGuiApplication | None = None) -> tuple[str, ThemePalette]:
    """Return ('dark'|'light', ThemePalette) for 'system', 'dark', or 'light'."""
    if mode == "dark":
        return "dark", DARK_PALETTE
    if mode == "light":
        return "light", LIGHT_PALETTE
    inst = app or QGuiApplication.instance()
    if inst is not None:
        scheme = inst.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return "dark", DARK_PALETTE
        if scheme == Qt.ColorScheme.Light:
            return "light", LIGHT_PALETTE
    return ("dark", DARK_PALETTE) if system_prefers_dark_theme() else ("light", LIGHT_PALETTE)


def ui_font(px: int = 13, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(list(UI_FAMILIES))
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


def mono_font(px: int = 12, weight: QFont.Weight = QFont.Weight.Medium) -> QFont:
    font = QFont()
    font.setFamilies(list(MONO_FAMILIES))
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


def build_stylesheet(p: ThemePalette) -> str:
    return f"""
    QMainWindow, QWidget#centralRoot {{
        background-color: {p.bg_canvas};
        color: {p.text_primary};
        font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
        font-size: 13px;
    }}
    QWidget#headerBar {{
        background-color: {p.bg_surface};
        border-bottom: 1px solid {p.border};
    }}
    QFrame#controlPanel, QFrame#settingsCard {{
        background-color: {p.bg_surface};
        border: 1px solid {p.border};
        border-radius: 10px;
    }}
    QFrame[divider="true"] {{
        background-color: {p.border};
        border: none;
        min-height: 1px;
        max-height: 1px;
    }}
    QLabel {{
        color: {p.text_primary};
        background: transparent;
    }}
    QLabel[role="title"] {{
        font-size: 14px;
        font-weight: 600;
        color: {p.text_primary};
    }}
    QLabel[role="section"] {{
        font-size: 12px;
        font-weight: 600;
        color: {p.text_secondary};
    }}
    QLabel[role="secondary"] {{
        font-size: 12px;
        color: {p.text_secondary};
    }}
    QLabel[role="muted"] {{
        font-size: 12px;
        color: {p.text_muted};
    }}
    QLabel[role="mono-muted"] {{
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 12px;
        color: {p.text_secondary};
    }}
    QLabel[role="warning"] {{
        font-size: 12px;
        color: {p.state_warning_text};
    }}
    QLabel[role="danger"] {{
        font-size: 12px;
        color: {p.state_danger_text};
    }}
    QPlainTextEdit {{
        background-color: {p.bg_surface};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: 10px;
        padding: 12px 14px;
        font-size: 13px;
        selection-background-color: {p.accent};
        selection-color: {p.on_accent};
    }}
    QPlainTextEdit:focus {{
        border-color: {p.accent};
    }}
    QLineEdit {{
        background-color: {p.bg_canvas};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: 7px;
        padding: 6px 10px;
        min-height: 20px;
        selection-background-color: {p.accent};
        selection-color: {p.on_accent};
    }}
    QLineEdit:focus {{
        border-color: {p.accent};
    }}
    QComboBox {{
        background-color: {p.bg_surface};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: 7px;
        padding: 5px 28px 5px 10px;
        min-height: 20px;
    }}
    QComboBox:hover {{
        border-color: {p.border_strong};
    }}
    QComboBox:focus {{
        border-color: {p.accent};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: right center;
        width: 24px;
        border: none;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p.bg_elevated};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 4px;
        selection-background-color: {p.accent_tint};
        selection-color: {p.text_primary};
        outline: 0;
    }}
    QPushButton {{
        background-color: {p.bg_subtle};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: 7px;
        padding: 6px 12px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton:focus {{
        border-color: {p.accent};
    }}
    QPushButton:disabled {{
        color: {p.text_muted};
        background-color: {p.bg_subtle};
        border-color: {p.border};
    }}
    QPushButton[variant="primary"] {{
        background-color: {p.btn_primary};
        color: {p.on_accent};
        border: 1px solid {p.btn_primary};
    }}
    QPushButton[variant="ghost"] {{
        background-color: transparent;
        border: 1px solid transparent;
        color: {p.text_secondary};
    }}
    QPushButton[variant="icon"] {{
        background-color: {p.bg_subtle};
        border: 1px solid {p.border};
        border-radius: 7px;
        padding: 0px;
    }}
    QPushButton[variant="danger-subtle"] {{
        background-color: transparent;
        border: 1px solid {p.border};
        color: {p.state_danger_text};
    }}
    QPushButton[variant="preset"] {{
        background-color: {p.bg_canvas};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 8px 10px;
        text-align: left;
    }}
    QPushButton[variant="preset"][active="true"] {{
        background-color: {p.accent_tint};
        border: 1px solid {p.accent};
    }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: {p.bg_subtle};
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {p.accent};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {p.bg_surface};
        border: 2px solid {p.accent};
        width: 10px;
        height: 10px;
        margin: -5px 0;
        border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover,
    QSlider::handle:horizontal:pressed {{
        background: {p.accent};
        border: 2px solid {p.accent};
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 4px 1px 4px 1px;
    }}
    QScrollBar::handle:vertical {{
        background: {p.border_strong};
        border-radius: 3px;
        min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p.text_muted};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
        height: 0px;
    }}
    QMenu {{
        background-color: {p.bg_elevated};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 22px 6px 10px;
        border-radius: 5px;
    }}
    QMenu::item:selected {{
        background-color: {p.accent_tint};
    }}
    QMenu::item:disabled {{
        color: {p.text_muted};
    }}
    QMenu::separator {{
        height: 1px;
        background: {p.border};
        margin: 4px 6px;
    }}
    QToolTip {{
        background-color: {p.bg_elevated};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 5px 8px;
        font-size: 12px;
    }}
    """
