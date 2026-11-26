"""Tactile 3D 'T_' keycap icon renderer, .ico builder, tray status badges, and monochrome UI SVGs."""

from __future__ import annotations

import functools
import struct
import sys
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
)
from PyQt6.QtSvg import QSvgRenderer

from ..engine import EngineState

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
_TRAY_SIZES = (16, 20, 24, 32, 40)

# Hand-tuned pixel grids: (margin, base_radius, cap_inset_lr, cap_inset_top, lip, cap_radius, rim_px)
_BASE_GRID: dict[int, tuple[int, float, int, int, int, float, int]] = {
    16: (0, 3.0, 1, 1, 3, 1.5, 0),
    24: (1, 4.5, 2, 2, 4, 2.5, 1),
    32: (1, 6.0, 2, 2, 5, 3.5, 1),
    48: (2, 9.0, 3, 3, 7, 5.5, 1),
    64: (2, 12.0, 4, 4, 9, 7.5, 1),
    128: (4, 24.0, 8, 7, 18, 15.0, 2),
    256: (8, 48.0, 16, 14, 34, 30.0, 3),
}
# Glyph pixel grids: (T_width, stroke, T_height, gap, underscore_width, underscore_thickness); (tw - t) even
_GLYPH_GRID: dict[int, tuple[int, int, int, int, int, int]] = {
    16: (6, 2, 8, 1, 4, 2),
    24: (9, 3, 10, 1, 5, 2),
    32: (12, 4, 14, 2, 7, 3),
    48: (18, 5, 21, 3, 10, 4),
    64: (26, 8, 30, 4, 14, 6),
    128: (52, 16, 60, 8, 28, 12),
    256: (104, 32, 120, 16, 56, 24),
}

_C_BASE_TOP, _C_BASE_BOTTOM = "#1A2438", "#0B1120"
_C_CAP_TOP, _C_CAP_BOTTOM = "#2A3850", "#1E293B"
_C_GLYPH = "#F8FAFC"
_C_CURSOR_A, _C_CURSOR_B = "#3B82F6", "#60A5FA"
_C_RIM_OUTER = QColor(71, 85, 105, 220)
_C_RIM_TOP = QColor(255, 255, 255, 54)
_DOT_COLORS = {"typing": "#22C55E", "attention": "#F59E0B"}

_SVGS: dict[str, tuple[str, str]] = {
    "play": (
        "0 0 16 16",
        '<path d="M4.5 3.3 L12.8 8 L4.5 12.7 Z" stroke="{c}" stroke-width="1.5" '
        'stroke-linejoin="round" fill="{c}"/>',
    ),
    "pause": (
        "0 0 16 16",
        '<rect x="4.2" y="3.2" width="2.4" height="9.6" rx="0.8" fill="{c}"/>'
        '<rect x="9.4" y="3.2" width="2.4" height="9.6" rx="0.8" fill="{c}"/>',
    ),
    "stop": (
        "0 0 16 16",
        '<rect x="3.8" y="3.8" width="8.4" height="8.4" rx="1.6" fill="{c}"/>',
    ),
    "refresh": (
        "0 0 16 16",
        '<path d="M13 8 A5 5 0 1 1 11.5 4.5" stroke="{c}" stroke-width="1.5" stroke-linecap="round" fill="none"/>'
        '<polyline points="11.5,2.2 12.3,4.9 9.5,5.2" stroke="{c}" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
    ),
    "sun": (
        "0 0 16 16",
        '<circle cx="8" cy="8" r="2.8" stroke="{c}" stroke-width="1.5" fill="none"/>'
        '<path d="M8 2 V3.3 M8 12.7 V14 M2 8 H3.3 M12.7 8 H14 '
        'M3.75 3.75 L4.7 4.7 M11.3 11.3 L12.25 12.25 M12.25 3.75 L11.3 4.7 M4.7 11.3 L3.75 12.25" '
        'stroke="{c}" stroke-width="1.5" stroke-linecap="round"/>',
    ),
    "moon": (
        "0 0 16 16",
        '<path d="M12.6 9.8 A5 5 0 0 1 6.2 3.4 A5.2 5.2 0 1 0 12.6 9.8 Z" '
        'stroke="{c}" stroke-width="1.5" stroke-linejoin="round" fill="none"/>',
    ),
    "tray": (
        "0 0 16 16",
        '<path d="M8 2.8 V9.5 M5.4 7.1 L8 9.8 L10.6 7.1" stroke="{c}" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
        '<path d="M3 10.5 V12.3 C3 12.8 3.4 13.2 3.9 13.2 H12.1 C12.6 13.2 13 12.8 13 12.3 V10.5" '
        'stroke="{c}" stroke-width="1.5" stroke-linecap="round" fill="none"/>',
    ),
    "warning": (
        "0 0 16 16",
        '<path d="M8 2.6 L14 13 H2 Z" stroke="{c}" stroke-width="1.5" stroke-linejoin="round" fill="none"/>'
        '<line x1="8" y1="6.4" x2="8" y2="9.4" stroke="{c}" stroke-width="1.5" stroke-linecap="round"/>'
        '<circle cx="8" cy="11.3" r="0.8" fill="{c}"/>',
    ),
    "check": (
        "0 0 16 16",
        '<polyline points="3.3,8.3 6.5,11.5 12.8,4.6" stroke="{c}" stroke-width="1.7" '
        'stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
    ),
    "plus": (
        "0 0 16 16",
        '<path d="M8 3.5 V12.5 M3.5 8 H12.5" stroke="{c}" stroke-width="1.6" stroke-linecap="round"/>',
    ),
    "minus": (
        "0 0 16 16",
        '<path d="M3.5 8 H12.5" stroke="{c}" stroke-width="1.6" stroke-linecap="round"/>',
    ),
    "reset": (
        "0 0 16 16",
        '<path d="M3.2 8 A4.8 4.8 0 1 0 4.7 4.5" stroke="{c}" stroke-width="1.5" stroke-linecap="round" fill="none"/>'
        '<polyline points="4.6,2.2 3.9,4.8 6.6,5.1" stroke="{c}" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
    ),
    "trash": (
        "0 0 16 16",
        '<path d="M3.2 4.5 H12.8 M6 4.5 V3 H10 V4.5 M4.8 4.5 L5.3 13 H10.7 L11.2 4.5" '
        'stroke="{c}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" fill="none"/>',
    ),
}

_TRAY_CACHE: dict[str, QIcon] = {}


def _geometry(px: int):
    if px in _BASE_GRID:
        return _BASE_GRID[px], _GLYPH_GRID[px]
    k = px / 256.0
    m, rb, ci, ct, lip, rc, rim = _BASE_GRID[256]
    base = (
        max(1, round(m * k)), rb * k, max(2, round(ci * k)), max(2, round(ct * k)),
        max(3, round(lip * k)), rc * k, 1 if px < 96 else max(1, round(rim * k)),
    )
    tw, t, gh, gap, uw, ut = (max(1, round(v * k)) for v in _GLYPH_GRID[256])
    t = max(2, t)
    if (tw - t) % 2:
        tw += 1
    return base, (tw, t, gh, max(1, gap), max(2 * ut, uw), max(2, ut))


def render_keycap(px: int) -> QImage:
    """Render the tactile 3D 'T_' keycap icon at `px` x `px`."""
    (m, r_base, ci, ct, lip, r_cap, rim), (tw, t, gh, gap, uw, ut) = _geometry(px)
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    base = QRectF(m, m, px - 2 * m, px - 2 * m)
    g = QLinearGradient(base.topLeft(), base.bottomLeft())
    g.setColorAt(0.0, QColor(_C_BASE_TOP))
    g.setColorAt(1.0, QColor(_C_BASE_BOTTOM))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(base, r_base, r_base)
    p.setPen(QPen(_C_RIM_OUTER, 1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(base.adjusted(0.5, 0.5, -0.5, -0.5), max(1.0, r_base - 0.5), max(1.0, r_base - 0.5))

    cap = QRectF(m + ci, m + ct, px - 2 * (m + ci), px - 2 * m - ct - lip)
    cg = QLinearGradient(cap.topLeft(), cap.bottomLeft())
    cg.setColorAt(0.0, QColor(_C_CAP_TOP))
    cg.setColorAt(1.0, QColor(_C_CAP_BOTTOM))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(cg)
    p.drawRoundedRect(cap, r_cap, r_cap)
    if rim:
        path = QPainterPath()
        path.addRoundedRect(cap, r_cap, r_cap)
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(cap.left(), cap.top(), cap.width(), rim), _C_RIM_TOP)
        p.restore()

    cx, cy, cw, ch = int(cap.left()), int(cap.top()), int(cap.width()), int(cap.height())
    gx = cx + (cw - (tw + gap + uw) + 1) // 2
    gy = cy + (ch - gh) // 2
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.fillRect(gx, gy, tw, t, QColor(_C_GLYPH))
    p.fillRect(gx + (tw - t) // 2, gy, t, gh, QColor(_C_GLYPH))
    ux, uy = gx + tw + gap, gy + gh - ut

    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if px >= 48:
        glow = QRadialGradient(QPointF(ux + uw / 2, uy + ut / 2), uw * 0.9)
        glow.setColorAt(0.0, QColor(96, 165, 250, 90))
        glow.setColorAt(1.0, QColor(96, 165, 250, 0))
        p.fillRect(QRectF(ux - uw * 0.4, uy - uw * 0.6, uw * 1.8, uw * 1.2 + ut), glow)
    ug = QLinearGradient(QPointF(ux, 0), QPointF(ux + uw, 0))
    ug.setColorAt(0.0, QColor(_C_CURSOR_A))
    ug.setColorAt(1.0, QColor(_C_CURSOR_B))
    p.fillRect(QRectF(ux, uy, uw, ut), ug)
    p.end()
    return img


def keycap_pixmap(logical: int, dpr: float = 1.0) -> QPixmap:
    dpr = max(1.0, float(dpr))
    pm = QPixmap.fromImage(render_keycap(max(16, round(logical * dpr))))
    pm.setDevicePixelRatio(dpr)
    return pm


def resource_path(rel: str) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return str(base / rel)


def _png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def _dib_bytes(img: QImage) -> bytes:
    """Encode `<256px` icon frame as standard Win32 32-bpp BGRA BITMAPINFOHEADER DIB (XOR + AND mask)."""
    src = img.convertToFormat(QImage.Format.Format_ARGB32)
    sz = src.width()
    ptr = src.constBits()
    ptr.setsize(src.sizeInBytes())
    raw = bytes(ptr)
    stride = src.bytesPerLine()
    and_stride = ((sz + 31) // 32) * 4

    xor_buf = bytearray()
    and_buf = bytearray()
    for y in range(sz - 1, -1, -1):
        row_off = y * stride
        xor_buf.extend(raw[row_off : row_off + sz * 4])
        mask_row = bytearray(and_stride)
        for x in range(sz):
            if raw[row_off + x * 4 + 3] < 16:
                mask_row[x >> 3] |= 0x80 >> (x & 7)
        and_buf.extend(mask_row)

    bih = struct.pack("<IiiHHIIiiII", 40, sz, sz * 2, 1, 32, 0, len(xor_buf) + len(and_buf), 0, 0, 0, 0)
    return bih + bytes(xor_buf) + bytes(and_buf)


def build_ico_bytes(sizes: tuple[int, ...] = ICO_SIZES) -> bytes:
    entries = [(sz, _png_bytes(render_keycap(sz)) if sz >= 256 else _dib_bytes(render_keycap(sz))) for sz in sizes]
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    dir_bytes = bytearray()
    blobs = bytearray()
    for sz, data in entries:
        wh = 0 if sz >= 256 else sz
        dir_bytes.extend(struct.pack("<BBBBHHII", wh, wh, 0, 0, 1, 32, len(data), offset))
        blobs.extend(data)
        offset += len(data)
    return header + bytes(dir_bytes) + bytes(blobs)


def write_ico_file(path: str | Path, sizes: tuple[int, ...] = ICO_SIZES) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(build_ico_bytes(sizes))
    return dest


@functools.lru_cache(maxsize=1)
def app_icon() -> QIcon:
    ico_path = Path(resource_path("assets/typesim.ico"))
    if ico_path.is_file():
        icon = QIcon(str(ico_path))
        if not icon.isNull():
            return icon
    icon = QIcon()
    for sz in ICO_SIZES:
        icon.addPixmap(QPixmap.fromImage(render_keycap(sz)))
    return icon


def _with_status_dot(img: QImage, color: str) -> QImage:
    px = img.width()
    out = img.copy()
    d = max(6, round(px * 0.40))
    ring = max(1, round(px / 16))
    x = y = px - d
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(Qt.GlobalColor.black)
    p.drawEllipse(QRectF(x - ring, y - ring, d + 2 * ring, d + 2 * ring))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(x, y, d, d))
    p.end()
    return out


def tray_dot_class(state: EngineState) -> str:
    if state == EngineState.TYPING:
        return "typing"
    if state in (EngineState.PAUSED, EngineState.COUNTDOWN):
        return "attention"
    return "idle"


def tray_app_icon(_palette=None, state: EngineState = EngineState.IDLE) -> QIcon:
    """Tray icon for `state` with transparent knock-out status dot, cached by dot class."""
    cls = tray_dot_class(state)
    cached = _TRAY_CACHE.get(cls)
    if cached is not None:
        return cached
    icon = QIcon()
    color = _DOT_COLORS.get(cls)
    for sz in _TRAY_SIZES:
        img = render_keycap(sz)
        if color is not None:
            img = _with_status_dot(img, color)
        icon.addPixmap(QPixmap.fromImage(img))
    _TRAY_CACHE[cls] = icon
    return icon


def svg_pixmap(name: str, color: str, size: int = 16, dpr: float = 2.0) -> QPixmap:
    viewbox, body = _SVGS[name]
    xml = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}">{body.format(c=color)}</svg>'
    renderer = QSvgRenderer(QByteArray(xml.encode("utf-8")))
    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def svg_icon(name: str, color: str, size: int = 16) -> QIcon:
    icon = QIcon()
    icon.addPixmap(svg_pixmap(name, color, size=size, dpr=2.0))
    return icon
