"""generate_pbc_blocks.py — author the PBC and PBC-valve sub-blocks as DWG files.

Outputs (overwrites if present):
    blocks/misc/pbc.dwg              — PBC body block with attributes
    blocks/misc/pbc_valve_gex.dwg    — small GEX valve sub-block
    blocks/misc/pbc_valve_hood.dwg   — HOOD sub-block (with FHD spur)
    blocks/misc/pbc_valve_aux.dwg    — AUX sub-block
    blocks/misc/pbc_valve_supply.dwg — SUPPLY sub-block

Each PBC valve sub-block carries two visible attributes:
    ROOM  — room tag (e.g. "LAB 101")
    TAG   — valve tag (e.g. "PSV-1")

The PBC block carries three visible attributes:
    TAG          — PBC tag
    DEVICE_NUM   — device number
    MAC          — MAC address
And one (drawn programmatically each generation, not stored as an attribute):
    NETWORK_NUM  — used as the NET1/NET2/... label above each PBC

Run:
    .venv/Scripts/python tools/generate_pbc_blocks.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pythoncom  # type: ignore
import win32com.client  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "blocks" / "misc"
PROG_IDS = ("BricscadApp.AcadApplication", "AutoCAD.Application")

# Load PBC geometry from the shared config so this generator and the runtime
# drawing code (cad/pbc.py) stay in sync. Fallback values match the historical
# hardcoded constants, so a missing/malformed config still produces blocks.
_CFG_PATH = PROJECT_ROOT / "config" / "product_lines.json"
try:
    with _CFG_PATH.open("r", encoding="utf-8") as _f:
        _PBC_GEOM = json.load(_f).get("pbc", {}) or {}
except Exception:
    _PBC_GEOM = {}

PBC_BODY_W = float(_PBC_GEOM.get("body_w", 100.0))
PBC_BODY_H = float(_PBC_GEOM.get("body_h", 140.0))
PBC_COM1_OVAL_DX = float(_PBC_GEOM.get("com1_oval_dx", 25.0))
PBC_COM2_OVAL_DX = float(_PBC_GEOM.get("com2_oval_dx", 75.0))
PBC_COM_OVAL_BOTTOM_DY = float(_PBC_GEOM.get("com_oval_bottom_dy", 5.25))
PBC_SUB_W = float(_PBC_GEOM.get("sub_w", 50.0))
PBC_SUB_H = float(_PBC_GEOM.get("sub_h", 32.0))


def _pt(x: float, y: float, z: float = 0.0):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (x, y, z))


def connect_app(visible: bool = False):
    last_err = None
    for prog in PROG_IDS:
        try:
            app = win32com.client.Dispatch(prog)
            try:
                app.Visible = visible
            except Exception:  # noqa: BLE001
                pass
            return app
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"COM connect failed. Last error: {last_err}")


def add_rect(ms, x1, y1, x2, y2):
    pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
    for i in range(4):
        a = pts[i]
        b = pts[(i + 1) % 4]
        ms.AddLine(_pt(*a), _pt(*b))


def add_attribute(ms, x: float, y: float, height: float, tag: str, default: str,
                  prompt: str | None = None, mode: int = 0):
    """Add an attribute definition (ATTDEF) to model space.
    Mode bits: 0=visible+editable, 1=invisible, 2=constant, 4=verify, 8=preset.
    """
    return ms.AddAttribute(height, mode, prompt or f"Enter {tag}",
                           _pt(x, y), tag, default)


# ── PBC block ────────────────────────────────────────────────────────────────


def build_pbc(app, out_path: Path):
    doc = app.Documents.Add()
    ms = doc.ModelSpace

    # Block dimensions sourced from config/product_lines.json:pbc
    W, H = PBC_BODY_W, PBC_BODY_H

    # Outer body — split visually into 3 zones (VAC band / PBC body / COM band)
    add_rect(ms, 0, 0, W, H)
    # Horizontal divider above the COM band
    ms.AddLine(_pt(0, 25), _pt(W, 25))
    # Horizontal divider below the VAC band
    ms.AddLine(_pt(0, H - 25), _pt(W, H - 25))

    # ── Top zone left blank (VAC text and 24V indicator removed per user) ───

    # ── Middle zone: "PBC" header + 5 visible attributes ─────────────────────
    # All 5 attributes are visible inside the block. The runtime ALSO renders
    # NET<n> above the block as a network branch label, but the inside-the-
    # block value is what the technician reads up close.
    ms.AddText("PBC", _pt(W / 2.0 - 12, H - 40), 8.0)
    add_attribute(ms, 8, H - 55, 5.0, "TAG", "PBC-TAG")
    ms.AddText("Device #", _pt(8, H - 68), 4.0)
    add_attribute(ms, 40, H - 68, 4.0, "DEVICE_NUM", "1001")
    ms.AddText("MAC", _pt(8, H - 80), 4.0)
    add_attribute(ms, 22, H - 80, 4.0, "MAC", "10")
    ms.AddText("Net #", _pt(8, H - 92), 4.0)
    add_attribute(ms, 30, H - 92, 4.0, "NETWORK_NUM", "1")
    ms.AddText("Name", _pt(8, H - 104), 4.0)
    add_attribute(ms, 30, H - 104, 4.0, "DEVICE_NAME", "PBC")

    # ── Bottom zone: COM1 / COM2 ovals ───────────────────────────────────────
    # AddEllipse(center, major_axis_pt, ratio) — major_axis_pt is the endpoint
    # of the major axis from the center. Use a small flat ellipse.
    ms.AddEllipse(_pt(25, 12), _pt(15, 0), 0.45)
    ms.AddText("COM1", _pt(15, 9.5), 4.0)
    ms.AddEllipse(_pt(75, 12), _pt(15, 0), 0.45)
    ms.AddText("COM2", _pt(65, 9.5), 4.0)

    # Save & close
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    doc.SaveAs(str(out_path))
    print(f"  Saved: {out_path.relative_to(PROJECT_ROOT)}")
    doc.Close(False)


# ── Valve sub-blocks ─────────────────────────────────────────────────────────


def build_valve_sub(app, out_path: Path, type_label: str, with_fhd: bool):
    doc = app.Documents.Add()
    ms = doc.ModelSpace

    # Sub-block dimensions sourced from config/product_lines.json:pbc
    W, H = PBC_SUB_W, PBC_SUB_H

    # Outer rectangle
    add_rect(ms, 0, 0, W, H)

    # ── "RM:" plus ROOM attribute on top half ───────────────────────────────
    ms.AddText("RM:", _pt(3, H - 8), 4.0)
    add_attribute(ms, 13, H - 8, 4.0, "ROOM", "")

    # ── Type label centered (visible static label) ──────────────────────────
    ms.AddText(type_label, _pt(W / 2.0 - len(type_label) * 1.5, H / 2.0 - 4), 5.0)

    # ── TAG attribute on bottom half ────────────────────────────────────────
    add_attribute(ms, 3, 4, 5.0, "TAG", "TAG")

    # ── Hidden TYPE attribute so we know what this is even after insertion ──
    add_attribute(ms, 3, -10, 3.0, "TYPE", type_label, mode=1)

    # ── Optional FHD spur on the right (only for HOOD type) ─────────────────
    if with_fhd:
        # Short horizontal stub from right edge into a small FHD box
        spur_x1, spur_x2 = W, W + 8
        spur_y = H / 2.0
        ms.AddLine(_pt(spur_x1, spur_y), _pt(spur_x2, spur_y))
        # Small FHD box
        bx1, by1, bx2, by2 = W + 8, H / 2.0 - 6, W + 22, H / 2.0 + 6
        add_rect(ms, bx1, by1, bx2, by2)
        # Center "FHD" inside the box (manual centering — AutoCAD's text
        # justification via COM is finicky; manual offset is reliable).
        fhd_text = "FHD"
        fhd_h = 4.0
        fhd_w = len(fhd_text) * fhd_h * 0.6
        ms.AddText(
            fhd_text,
            _pt((bx1 + bx2) / 2.0 - fhd_w / 2.0,
                (by1 + by2) / 2.0 - fhd_h / 2.0),
            fhd_h,
        )

    # Save & close
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    doc.SaveAs(str(out_path))
    print(f"  Saved: {out_path.relative_to(PROJECT_ROOT)}")
    doc.Close(False)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app = connect_app(visible=False)
    try:
        print("Generating PBC + valve sub-block DWGs:")
        build_pbc(app, OUT_DIR / "pbc.dwg")
        build_valve_sub(app, OUT_DIR / "pbc_valve_gex.dwg", "GEX", with_fhd=False)
        build_valve_sub(app, OUT_DIR / "pbc_valve_hood.dwg", "HOOD", with_fhd=True)
        build_valve_sub(app, OUT_DIR / "pbc_valve_aux.dwg", "AUX", with_fhd=False)
        build_valve_sub(app, OUT_DIR / "pbc_valve_supply.dwg", "SUPPLY", with_fhd=False)
    finally:
        try:
            app.Quit()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
