"""compute_offsets.py — convert hand-measured world coords into bbox-relative
offsets per block by reading each DWG's EXTMIN via BricsCAD COM.

For each block, hardcoded below: the world-coordinate IN endpoint and OUT
endpoint as measured by the user with LIST in BricsCAD. This script opens the
DWG, queries EXTMIN/EXTMAX (after REGEN), and emits offsets relative to the
file's bbox bottom-left — the same coordinate system the runtime uses to
position each insert.

Output is the `mstp.ports` block ready to paste into config/product_lines.json.

Run:
    .venv/Scripts/python tools/compute_offsets.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import pythoncom  # type: ignore
import win32com.client  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROG_IDS = ("BricscadApp.AcadApplication", "AutoCAD.Application")

# variant_id → (relative path under blocks/, IN endpoint world, OUT endpoint world)
# IN may be None for chain-starter variants (no IN port — the comm trunk begins there).
MEASUREMENTS: dict[str, dict] = {
    # SAV variants — comm bus on layer SUP
    "SAV_SINGLE_PBC_ACM_START": {
        "path": "blocks/cscp/SAV/SAV_SINGLE_PBC_ACM_START.dwg",
        "in":  None,
        "out": (1165.1875, 486.125),
    },
    "SAV_DOUBLE_PBC_ACM_START": {
        "path": "blocks/cscp/SAV/SAV_DOUBLE_PBC_ACM_START.dwg",
        "in":  None,
        "out": (1165.375, 486.1875),
    },
    "SAV_SINGLE_ACM_START": {
        "path": "blocks/cscp/SAV/SAV_SINGLE_ACM_START.dwg",
        "in":  None,
        "out": (1159.125, 498.75),
    },
    "SAV_DOUBLE_ACM_START": {
        "path": "blocks/cscp/SAV/SAV_DOUBLE_ACM_START.dwg",
        "in":  None,
        "out": (1159.125, 498.6875),
    },
    "SAV_SINGLE_ACM": {
        "path": "blocks/cscp/SAV/SAV_SINGLE_ACM.dwg",
        "in":  (825.375, 503.5625),
        "out": (1159.125, 498.75),
    },
    "SAV_DOUBLE_ACM": {
        "path": "blocks/cscp/SAV/SAV_DOUBLE_ACM.dwg",
        "in":  (825.375, 503.5),
        "out": (1159.125, 498.6875),
    },
    # GEX variants — comm bus on layer GEX
    "GEX_SINGLE": {
        "path": "blocks/cscp/GEX/GEX_SINGLE.dwg",
        "in":  (768.5625, 495.375),
        "out": (1077.6875, 495.0),
    },
    "GEX_DOUBLE": {
        "path": "blocks/cscp/GEX/GEX_DOUBLE.dwg",
        "in":  (768.5625, 495.9375),
        "out": (1077.6875, 495.0),
    },
    # FEV variants — comm bus on layer HOOD
    "FEV_SINGLE": {
        "path": "blocks/cscp/FEV/FEV_SINGLE.dwg",
        "in":  (971.4375, 416.3125),
        "out": (1125.75, 527.375),
    },
    "FEV_DOUBLE": {
        "path": "blocks/cscp/FEV/FEV_DOUBLE.dwg",
        "in":  (973.375, 429.1875),
        "out": (1128.0, 540.25),
    },
    # AUX variants — comm bus on layer GEX
    "CAGE_SINGLE": {
        "path": "blocks/cscp/AUX/CAGE_SINGLE.dwg",
        "in":  (636.5625, 469.0625),
        "out": (945.6875, 469.125),
    },
    "CAGE_DOUBLE": {
        "path": "blocks/cscp/AUX/CAGE_DOUBLE.dwg",
        "in":  (636.5625, 469.0625),
        "out": (945.6875, 469.125),
    },
    "SNORKEL_SINGLE": {
        "path": "blocks/cscp/AUX/SNORKEL_SINGLE.dwg",
        "in":  (635.875, 513.75),
        "out": (945.0, 513.75),
    },
    "SNORKEL_DOUBLE": {
        "path": "blocks/cscp/AUX/SNORKEL_DOUBLE.dwg",
        "in":  (639.1875, 512.75),
        "out": (948.3125, 512.8125),
    },
}


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


def open_doc(app, dwg: Path):
    try:
        return app.Documents.Open(str(dwg), True)
    except TypeError:
        return app.Documents.Open(str(dwg))


def doc_extmin(doc) -> Optional[tuple[float, float]]:
    try:
        doc.Regen(0)
    except Exception:  # noqa: BLE001
        pass
    try:
        emin = doc.GetVariable("EXTMIN")
        return (float(emin[0]), float(emin[1]))
    except Exception:  # noqa: BLE001
        return None


def _is_rpc_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return "rpc" in s or "remote procedure call" in s or "-2147023174" in s or "-2147023170" in s


def measure_one(app, variant_id: str, m: dict) -> Optional[tuple[object, dict]]:
    """Returns (app, entry) on success — app may have been replaced if a reconnect happened."""
    import time
    path = PROJECT_ROOT / m["path"]
    if not path.is_file():
        print(f"  {variant_id}: MISSING {path}", file=sys.stderr)
        return None

    for attempt in (1, 2, 3):
        try:
            doc = open_doc(app, path)
        except Exception as exc:  # noqa: BLE001
            if _is_rpc_error(exc) and attempt < 3:
                print(f"  {variant_id}: RPC failure (attempt {attempt}) — reconnecting…", file=sys.stderr)
                time.sleep(2.0)
                try:
                    app = connect_app(visible=False)
                except Exception as exc2:  # noqa: BLE001
                    print(f"    reconnect failed: {exc2}", file=sys.stderr)
                    time.sleep(3.0)
                continue
            print(f"  {variant_id}: open failed — {exc}", file=sys.stderr)
            return None

        try:
            extmin = doc_extmin(doc)
            if extmin is None:
                print(f"  {variant_id}: no EXTMIN", file=sys.stderr)
                return (app, {})
            ex, ey = extmin
            entry: dict = {}
            if m["in"] is not None:
                ix, iy = m["in"]
                entry["in_offset"] = [round(ix - ex, 4), round(iy - ey, 4)]
            if m["out"] is not None:
                ox, oy = m["out"]
                entry["out_offset"] = [round(ox - ex, 4), round(oy - ey, 4)]
            print(f"  {variant_id}:  EXTMIN=({ex:8.2f},{ey:8.2f})  -> {entry}")
            return (app, entry)
        finally:
            try:
                doc.Close(False)
            except Exception:  # noqa: BLE001
                pass
    return None


def main() -> int:
    app = connect_app(visible=False)

    ports: dict[str, dict] = {}
    for variant_id, m in MEASUREMENTS.items():
        result = measure_one(app, variant_id, m)
        if result is None:
            continue
        app, entry = result
        if entry:
            ports[variant_id] = entry

    print()
    print("--- paste under mstp.ports in config/product_lines.json ---")
    print(json.dumps(ports, indent=2))

    try:
        app.Quit()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
