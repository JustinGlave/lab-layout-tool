"""generate_psh500a.py — build a PSH500A power-supply schematic block as a DWG.

Drives BricsCAD via COM to draw the schematic shown in the manufacturer's
reference image, then saves it to blocks/misc/PSH500A.dwg at the same scale
the valve blocks use (roughly 500" wide × 400" tall in drawing units).

Run:
    .venv/Scripts/python tools/generate_psh500a.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pythoncom  # type: ignore
import win32com.client  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = PROJECT_ROOT / "blocks" / "misc" / "PSH500A.dwg"

PROG_IDS = ("BricscadApp.AcadApplication", "AutoCAD.Application")


def _pt(x: float, y: float, z: float = 0.0):
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (x, y, z))


def connect_app():
    last_err = None
    for prog in PROG_IDS:
        try:
            app = win32com.client.Dispatch(prog)
            app.Visible = True
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


def main() -> int:
    app = connect_app()
    doc = app.Documents.Add()
    ms = doc.ModelSpace

    # ── Overall sheet (matches valve-block scale: ~500"×400") ─────────────────
    W, H = 500.0, 420.0

    # Outer enclosure
    add_rect(ms, 0.0, 0.0, W, H)

    # ── Title / subtitle ──────────────────────────────────────────────────────
    ms.AddText("PSH500A", _pt(20, 380), 30.0)
    ms.AddText("500 VA Power Supply, Five 100 VA Class 2 Outputs,", _pt(20, 360), 8.0)
    ms.AddText("480/277/240/120 Vac to 24 Vac, Metal Enclosure", _pt(20, 348), 8.0)

    # Divider line under the title block
    ms.AddLine(_pt(0, 335), _pt(W, 335))

    # ── Transformer (left side) ───────────────────────────────────────────────
    txL, txB, txR, txT = 30.0, 60.0, 200.0, 300.0
    add_rect(ms, txL, txB, txR, txT)
    # Cooling fins — horizontal lines inside
    for y in range(int(txB) + 20, int(txT) - 10, 20):
        ms.AddLine(_pt(txL + 10, y), _pt(txR - 10, y))
    # Mounting hole circles in the four corners
    for cx, cy in [(txL + 12, txB + 12), (txR - 12, txB + 12),
                   (txL + 12, txT - 12), (txR - 12, txT - 12)]:
        ms.AddCircle(_pt(cx, cy), 4.0)

    # Top + bottom wire stubs from transformer to PCB
    ms.AddLine(_pt(txR, txT - 25), _pt(220, txT - 25))
    ms.AddLine(_pt(txR, txB + 25), _pt(220, txB + 25))

    # ── PCB (right side) ──────────────────────────────────────────────────────
    pcbL, pcbB, pcbR, pcbT = 220.0, 50.0, 480.0, 320.0
    add_rect(ms, pcbL, pcbB, pcbR, pcbT)

    # Input voltage taps (top of PCB) — 5 circles, labels to the right
    input_labels = [("480", 295), ("277", 280), ("240", 265), ("120", 250), ("COMM", 235)]
    for label, y in input_labels:
        ms.AddCircle(_pt(pcbL + 18, y), 4.0)
        ms.AddText(label, _pt(pcbL + 28, y - 4), 7.0)

    # ── Output channels ───────────────────────────────────────────────────────
    # 5 horizontal rows. Each row: + terminal, breaker, ON/OFF switch,
    # numbered indicator, 24V/COM terminal labels.
    row_y_start = 200.0
    row_step = 28.0
    for i in range(5):
        y = row_y_start - i * row_step

        # + terminal (small circle with "+" inside)
        ms.AddCircle(_pt(pcbL + 60, y), 4.0)
        ms.AddText("+", _pt(pcbL + 57, y - 3), 6.0)

        # Breaker — small rectangle with vertical switch slot
        add_rect(ms, pcbL + 75, y - 7, pcbL + 100, y + 7)
        # Switch line/handle
        ms.AddLine(_pt(pcbL + 87, y - 5), _pt(pcbL + 87, y + 5))
        # ON / OFF labels stacked next to the breaker
        ms.AddText("ON", _pt(pcbL + 103, y + 1), 4.0)
        ms.AddText("OFF", _pt(pcbL + 103, y - 6), 4.0)

        # Indicator (red dot) with channel number
        ms.AddCircle(_pt(pcbL + 130, y), 4.0)
        ms.AddText(str(i + 1), _pt(pcbL + 128, y - 3), 5.0)

        # 24V and COM terminal labels
        ms.AddText("24V", _pt(pcbL + 150, y + 1), 5.0)
        ms.AddText("COM", _pt(pcbL + 150, y - 7), 5.0)

        # Terminal screws (small circles)
        ms.AddCircle(_pt(pcbL + 180, y + 3), 2.0)
        ms.AddCircle(_pt(pcbL + 180, y - 3), 2.0)

    # ── Bottom labels (callouts pointing to features) ─────────────────────────
    ms.AddText("Breaker", _pt(pcbL + 75, 35), 7.0)
    ms.AddText("Switch", _pt(pcbL + 100, 22), 7.0)
    ms.AddText("Indicator", _pt(pcbL + 125, 9), 7.0)

    # Tiny callout lines from labels up to their feature
    ms.AddLine(_pt(pcbL + 90, 45), _pt(pcbL + 90, pcbB + 5))
    ms.AddLine(_pt(pcbL + 115, 32), _pt(pcbL + 90, pcbB + 5))
    ms.AddLine(_pt(pcbL + 140, 19), _pt(pcbL + 130, pcbB + 5))

    # ── "User Connections" label, rotated 90°, on the right side ─────────────
    user_text = ms.AddText("User Connections", _pt(pcbR + 10, 120), 8.0)
    try:
        user_text.Rotation = math.pi / 2.0
    except Exception:  # noqa: BLE001
        pass

    # ── Save and close ────────────────────────────────────────────────────────
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if OUT_PATH.exists():
        OUT_PATH.unlink()
    doc.SaveAs(str(OUT_PATH))
    print(f"Saved: {OUT_PATH}")
    doc.Close(False)
    try:
        app.Quit()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
