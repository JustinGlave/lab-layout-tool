"""anchored_refresh.py — refresh mstp.ports offsets to match the CURRENT
state of each DWG, using the user's original measurements as anchors.

For each variant, we know roughly where the user originally measured each rail
endpoint (the world coords from compute_offsets.py's MEASUREMENTS dict). After
the polyline straightening pass moved some vertex Ys by up to ~0.5", those
hardcoded coords are slightly off. This script re-opens each DWG, finds the
polyline vertex CLOSEST to the original anchor, reads that vertex's CURRENT
coords, and recomputes the offset relative to the file's CURRENT EXTMIN.

The result: offsets that exactly match where each rail's endpoint sits today.

Run dry-run (default):
    .venv/Scripts/python tools/anchored_refresh.py
Apply (writes to config/product_lines.json):
    .venv/Scripts/python tools/anchored_refresh.py --apply
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Optional

import pythoncom  # type: ignore
import win32com.client  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROG_IDS = ("BricscadApp.AcadApplication", "AutoCAD.Application")

# (path, anchor IN world coord or None, anchor OUT world coord or None)
# Coords are pre-straightening; we use them as anchors to locate the rail's
# current endpoints. _START variants have no IN.
ANCHORS: dict[str, dict] = {
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

ANCHOR_TOLERANCE = 5.0  # search within 5" of the original anchor


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
    raise RuntimeError(f"COM connect failed: {last_err}")


def open_doc(app, dwg: Path):
    try:
        return app.Documents.Open(str(dwg), True)  # read-only
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


def find_closest_vertex(doc, anchor_world: tuple[float, float],
                         tolerance: float) -> Optional[tuple[float, float]]:
    """Find any LWPOLYLINE/2dPOLYLINE vertex within `tolerance` of `anchor_world`.
    Returns the closest vertex's (x, y), or None if none in range."""
    best: Optional[tuple[float, float]] = None
    best_dist = float("inf")
    ax, ay = anchor_world
    for ent in doc.ModelSpace:
        try:
            if ent.ObjectName not in ("AcDbPolyline", "AcDb2dPolyline"):
                continue
        except Exception:  # noqa: BLE001
            continue
        try:
            coords = list(ent.Coordinates)
        except Exception:  # noqa: BLE001
            continue
        for i in range(0, len(coords), 2):
            try:
                vx = float(coords[i])
                vy = float(coords[i + 1])
            except (IndexError, TypeError, ValueError):
                continue
            d = math.hypot(vx - ax, vy - ay)
            if d < best_dist:
                best_dist = d
                best = (vx, vy)
    if best is None or best_dist > tolerance:
        return None
    return best


def measure_one(app, variant_id: str, m: dict) -> Optional[dict]:
    path = PROJECT_ROOT / m["path"]
    if not path.is_file():
        print(f"  {variant_id}: missing file", file=sys.stderr)
        return None
    for attempt in (1, 2, 3):
        try:
            doc = open_doc(app, path)
            break
        except Exception as exc:  # noqa: BLE001
            if attempt < 3:
                time.sleep(2.0)
                continue
            print(f"  {variant_id}: open failed — {exc}", file=sys.stderr)
            return None
    try:
        extmin = doc_extmin(doc)
        if extmin is None:
            return None
        ex, ey = extmin
        entry: dict = {}
        details = []
        if m["in"] is not None:
            v = find_closest_vertex(doc, m["in"], ANCHOR_TOLERANCE)
            if v is not None:
                entry["in_offset"] = [round(v[0] - ex, 4), round(v[1] - ey, 4)]
                drift = math.hypot(v[0] - m["in"][0], v[1] - m["in"][1])
                details.append(f"in drift={drift:.3f}\"")
            else:
                print(f"  {variant_id}: IN anchor not found within "
                      f"{ANCHOR_TOLERANCE}\"", file=sys.stderr)
        if m["out"] is not None:
            v = find_closest_vertex(doc, m["out"], ANCHOR_TOLERANCE)
            if v is not None:
                entry["out_offset"] = [round(v[0] - ex, 4), round(v[1] - ey, 4)]
                drift = math.hypot(v[0] - m["out"][0], v[1] - m["out"][1])
                details.append(f"out drift={drift:.3f}\"")
            else:
                print(f"  {variant_id}: OUT anchor not found within "
                      f"{ANCHOR_TOLERANCE}\"", file=sys.stderr)
        if details:
            print(f"  {variant_id}: {', '.join(details)}")
        return entry if entry else None
    finally:
        try:
            doc.Close(False)
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Write the new offsets directly into config/product_lines.json. "
                         "Default is dry-run.")
    args = ap.parse_args()

    app = connect_app(visible=False)
    new_ports: dict[str, dict] = {}
    for variant_id, m in ANCHORS.items():
        entry = measure_one(app, variant_id, m)
        if entry:
            new_ports[variant_id] = entry

    print()
    if args.apply:
        cfg_path = PROJECT_ROOT / "config" / "product_lines.json"
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg.setdefault("mstp", {})["ports"] = new_ports
        with cfg_path.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        print(f"Wrote {len(new_ports)} variants to {cfg_path.relative_to(PROJECT_ROOT)}")
    else:
        print("--- new mstp.ports (use --apply to commit) ---")
        print(json.dumps(new_ports, indent=2))

    try:
        app.Quit()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
