"""refresh_offsets.py — re-compute mstp.ports offsets directly from current
DWG contents, no manual measurements needed.

For each block in blocks/cscp/{SAV,GEX,FEV,AUX}/, opens the DWG via BricsCAD
COM, finds polylines on the bus-specific layer for that category, and takes
the LEFTMOST and RIGHTMOST vertices across those polylines as the IN and OUT
ports respectively. Offsets are stored relative to the file's EXTMIN.

Variants whose name contains "_START" don't get an in_offset — those are
chain-starters with no incoming wire.

Layer mapping per category (configured via VARIANT_LAYER below):
    SAV_*       → layer SUP
    GEX_*       → layer GEX
    FEV_*       → layer HOOD
    CAGE_*      → layer GEX
    SNORKEL_*   → layer GEX

Run:
    # Dry-run — prints the new JSON, doesn't modify config:
    .venv/Scripts/python tools/refresh_offsets.py
    # Update config/product_lines.json in place:
    .venv/Scripts/python tools/refresh_offsets.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

import pythoncom  # type: ignore
import win32com.client  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROG_IDS = ("BricscadApp.AcadApplication", "AutoCAD.Application")

# Prefix → bus layer name. Variant ids start with one of these prefixes.
VARIANT_LAYER: list[tuple[str, str]] = [
    ("SAV_",     "SUP"),
    ("GEX_",     "GEX"),
    ("FEV_",     "HOOD"),
    ("CAGE_",    "GEX"),
    ("SNORKEL_", "GEX"),
]


def layer_for(variant_id: str) -> Optional[str]:
    for prefix, layer in VARIANT_LAYER:
        if variant_id.startswith(prefix):
            return layer
    return None


def has_in_port(variant_id: str) -> bool:
    """_START variants begin the comm trunk and have no IN port."""
    return "_START" not in variant_id


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


BUS_WIDTH = 1.875        # the rail polyline's constant width (1 7/8")
BUS_WIDTH_TOL = 0.05     # tight tolerance — only accept "the bus", not other thick lines


def find_bus_endpoints(doc, layer: str) -> tuple[Optional[tuple[float, float]], Optional[tuple[float, float]]]:
    """Return (leftmost_vertex, rightmost_vertex) across polylines on `layer`
    whose ConstantWidth matches the bus width (1 7/8")."""
    vertices: list[tuple[float, float]] = []
    for ent in doc.ModelSpace:
        try:
            if ent.ObjectName not in ("AcDbPolyline", "AcDb2dPolyline"):
                continue
            if str(ent.Layer).upper() != layer.upper():
                continue
            w = float(ent.ConstantWidth)
        except Exception:  # noqa: BLE001
            continue
        if abs(w - BUS_WIDTH) > BUS_WIDTH_TOL:
            continue
        try:
            coords = list(ent.Coordinates)
        except Exception:  # noqa: BLE001
            continue
        for i in range(0, len(coords), 2):
            try:
                vertices.append((float(coords[i]), float(coords[i + 1])))
            except (IndexError, TypeError, ValueError):
                continue
    if not vertices:
        return None, None
    in_v = min(vertices, key=lambda v: v[0])
    out_v = max(vertices, key=lambda v: v[0])
    return in_v, out_v


def measure_one(app, variant_id: str, dwg: Path) -> Optional[dict]:
    layer = layer_for(variant_id)
    if not layer:
        return None
    for attempt in (1, 2, 3):
        try:
            doc = open_doc(app, dwg)
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
        in_v, out_v = find_bus_endpoints(doc, layer)
        if out_v is None:
            print(f"  {variant_id}: no polylines on layer '{layer}'", file=sys.stderr)
            return None
        entry: dict = {}
        if has_in_port(variant_id) and in_v is not None:
            entry["in_offset"] = [round(in_v[0] - ex, 4), round(in_v[1] - ey, 4)]
        entry["out_offset"] = [round(out_v[0] - ex, 4), round(out_v[1] - ey, 4)]
        return entry
    finally:
        try:
            doc.Close(False)
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Write the new offsets directly into config/product_lines.json. "
                         "Default is dry-run (just print JSON).")
    args = ap.parse_args()

    # Find every block DWG (skip *.bak, *_recover.dwg, and the misc folder).
    blocks_root = PROJECT_ROOT / "blocks" / "cscp"
    dwgs: list[tuple[str, Path]] = []
    for cat_dir in sorted(blocks_root.iterdir()):
        if not cat_dir.is_dir():
            continue
        for dwg in sorted(cat_dir.glob("*.dwg")):
            if "recover" in dwg.stem.lower():
                continue
            dwgs.append((dwg.stem, dwg))

    if not dwgs:
        print("No DWGs found under blocks/cscp/")
        return 1

    app = connect_app(visible=False)
    new_ports: dict[str, dict] = {}
    for variant_id, dwg in dwgs:
        rel = dwg.relative_to(PROJECT_ROOT)
        entry = measure_one(app, variant_id, dwg)
        if entry is None:
            print(f"  {rel}  SKIPPED")
            continue
        new_ports[variant_id] = entry
        in_part = f"in={entry.get('in_offset')}" if 'in_offset' in entry else "(no IN — _START)"
        print(f"  {rel}  {in_part}  out={entry['out_offset']}")

    print()
    if args.apply:
        cfg_path = PROJECT_ROOT / "config" / "product_lines.json"
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
        # Preserve the comment field if present, replace ports.
        ports_block = cfg.setdefault("mstp", {}).setdefault("ports", {})
        # Wipe out the old port entries (but keep comment-style underscored keys
        # in mstp itself).
        new_ports_block = dict(new_ports)  # only the new auto-detected ones
        cfg["mstp"]["ports"] = new_ports_block
        with cfg_path.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        print(f"Wrote {len(new_ports)} variants to {cfg_path.relative_to(PROJECT_ROOT)}")
    else:
        print("--- new mstp.ports (use --apply to write to config) ---")
        print(json.dumps(new_ports, indent=2))

    try:
        app.Quit()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
