"""measure_ports.py — auto-detect ACM/ACT-BUS port locations per block DWG.

Two modes:

(1) DUMP  — list every horizontal ~1 7/8"-wide LWPOLYLINE in each block
            grouped by layer. Useful to identify which layer the ACT BUS
            lives on for each variant.

(2) MEASURE — once you pass --layer SUP (or whichever), pick the matching
              polyline in each block and emit a config-ready JSON snippet
              with in_offset / out_offset for every variant.

Run:
    .venv/Scripts/python tools/measure_ports.py --product-line cscp                    # DUMP mode
    .venv/Scripts/python tools/measure_ports.py --product-line cscp --layer SUP        # MEASURE mode
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import pythoncom  # type: ignore
import win32com.client  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROG_IDS = ("BricscadApp.AcadApplication", "AutoCAD.Application")

# Tolerance for matching the bus polyline's constant width to the user-measured
# 1.875" reference. Some authors round; allow a window.
BUS_WIDTH_TARGET = 1.875
BUS_WIDTH_TOL = 0.5


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
    raise RuntimeError(
        f"Could not connect to BricsCAD or AutoCAD via COM. Last error: {last_err}"
    )


def open_doc(app, dwg: Path):
    """Open a DWG document. ReadOnly when supported."""
    try:
        return app.Documents.Open(str(dwg), True)
    except TypeError:
        return app.Documents.Open(str(dwg))


def iter_polylines(model_space):
    """Yield every LWPOLYLINE entity in model space."""
    for ent in model_space:
        try:
            name = ent.ObjectName
        except Exception:  # noqa: BLE001
            continue
        if name in ("AcDbPolyline", "AcDb2dPolyline"):
            yield ent


def polyline_points(pl) -> list[tuple[float, float]]:
    """Return [(x,y), ...] for an LWPOLYLINE."""
    coords = list(pl.Coordinates)
    return [(coords[i], coords[i + 1]) for i in range(0, len(coords), 2)]


def doc_extents(doc) -> Optional[tuple[float, float, float, float]]:
    """Return (xmin, ymin, xmax, ymax) of the document's drawn extent.

    Tries SetVariable("EXTMIN") / EXTMAX first (most reliable after a regen),
    then falls back to walking ModelSpace entities.
    """
    try:
        doc.Regen(0)  # acAllViewports
    except Exception:  # noqa: BLE001
        pass
    try:
        emin = doc.GetVariable("EXTMIN")
        emax = doc.GetVariable("EXTMAX")
        return (float(emin[0]), float(emin[1]), float(emax[0]), float(emax[1]))
    except Exception:  # noqa: BLE001
        pass
    # Fallback: walk entities
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")
    for ent in doc.ModelSpace:
        try:
            mn, mx = ent.GetBoundingBox()
            xmin = min(xmin, mn[0]); ymin = min(ymin, mn[1])
            xmax = max(xmax, mx[0]); ymax = max(ymax, mx[1])
        except Exception:  # noqa: BLE001
            continue
    if xmin == float("inf"):
        return None
    return (xmin, ymin, xmax, ymax)


def all_horizontal_bus_candidates(doc) -> list[dict]:
    """Return every horizontal LWPOLYLINE that's near the bus width.

    Each result: {layer, width, xmin, xmax, y, length}
    """
    out: list[dict] = []
    for pl in iter_polylines(doc.ModelSpace):
        try:
            w = float(pl.ConstantWidth)
        except Exception:  # noqa: BLE001
            continue
        if abs(w - BUS_WIDTH_TARGET) > BUS_WIDTH_TOL:
            continue
        pts = polyline_points(pl)
        if len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        # Strictly horizontal — Y must match across all vertices
        if max(ys) - min(ys) > 0.01:
            continue
        try:
            layer = str(pl.Layer)
        except Exception:  # noqa: BLE001
            layer = "?"
        out.append({
            "layer": layer,
            "width": w,
            "xmin": min(xs),
            "xmax": max(xs),
            "y": ys[0],
            "length": max(xs) - min(xs),
        })
    return out


def pick_bus_for_layer(candidates: list[dict], layer: str) -> Optional[dict]:
    """Pick the longest horizontal polyline matching `layer` (case-insensitive)."""
    matching = [c for c in candidates if c["layer"].upper() == layer.upper()]
    if not matching:
        return None
    return max(matching, key=lambda c: c["length"])


def dump_dwg(app, dwg: Path) -> None:
    """Print every horizontal ~1.875\"-wide LWPOLYLINE in `dwg`, grouped by layer."""
    doc = open_doc(app, dwg)
    try:
        extents = doc_extents(doc)
        if extents is None:
            print("    no extents found")
            return
        xmin, ymin, _, _ = extents
        cands = all_horizontal_bus_candidates(doc)
        if not cands:
            print("    (no horizontal ~1.875\" polylines found)")
            return
        # Group by layer
        by_layer: dict[str, list[dict]] = {}
        for c in cands:
            by_layer.setdefault(c["layer"], []).append(c)
        for layer, items in sorted(by_layer.items()):
            print(f"    layer '{layer}' ({len(items)} candidate{'s' if len(items)!=1 else ''}):")
            for c in sorted(items, key=lambda c: -c["length"]):
                in_off = (c["xmin"] - xmin, c["y"] - ymin)
                out_off = (c["xmax"] - xmin, c["y"] - ymin)
                print(f"      length={c['length']:7.2f}\"  width={c['width']:.4f}\"  "
                      f"y_offset={c['y']-ymin:8.2f}  "
                      f"in_offset=({in_off[0]:.2f},{in_off[1]:.2f})  "
                      f"out_offset=({out_off[0]:.2f},{out_off[1]:.2f})")
    finally:
        try:
            doc.Close(False)
        except Exception:  # noqa: BLE001
            pass


def measure_dwg(app, dwg: Path, layer: str) -> Optional[dict]:
    """Open `dwg`, find the bus polyline on `layer`, return offsets from bbox-min."""
    doc = open_doc(app, dwg)
    try:
        extents = doc_extents(doc)
        if extents is None:
            return None
        xmin, ymin, _, _ = extents
        cands = all_horizontal_bus_candidates(doc)
        bus = pick_bus_for_layer(cands, layer)
        if bus is None:
            return None
        return {
            "in_offset": [round(bus["xmin"] - xmin, 4), round(bus["y"] - ymin, 4)],
            "out_offset": [round(bus["xmax"] - xmin, 4), round(bus["y"] - ymin, 4)],
            "_diagnostic": {
                "bus_width_in_dwg": round(bus["width"], 4),
                "rail_length": round(bus["length"], 4),
                "layer": bus["layer"],
            },
        }
    finally:
        try:
            doc.Close(False)
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product-line", default=None,
                    help="Limit to one product line id (e.g. cscp). Default: all.")
    ap.add_argument("--layer", default=None,
                    help="Filter polylines to this layer name (MEASURE mode). "
                         "Omit to DUMP all candidate layers.")
    ap.add_argument("--visible", action="store_true",
                    help="Show BricsCAD while it works.")
    args = ap.parse_args()

    blocks_root = PROJECT_ROOT / "blocks"
    product_lines = (
        [args.product_line] if args.product_line
        else [d.name for d in blocks_root.iterdir() if d.is_dir()]
    )

    app = connect_app(visible=args.visible)

    if args.layer is None:
        # DUMP mode
        print(f"DUMP mode — listing all horizontal ~1.875\" polylines, grouped by layer.\n")
        for pl in product_lines:
            pl_dir = blocks_root / pl
            if not pl_dir.is_dir():
                continue
            print(f"\n=== {pl} ===")
            for cat_dir in sorted(pl_dir.iterdir()):
                if not cat_dir.is_dir():
                    continue
                for dwg in sorted(cat_dir.glob("*.dwg")):
                    print(f"  {dwg.relative_to(PROJECT_ROOT)}:")
                    try:
                        dump_dwg(app, dwg)
                    except Exception as exc:  # noqa: BLE001
                        print(f"    ERROR: {exc}", file=sys.stderr)
        try:
            app.Quit()
        except Exception:  # noqa: BLE001
            pass
        return 0

    # MEASURE mode
    print(f"MEASURE mode — picking longest horizontal ~1.875\" polyline on layer "
          f"'{args.layer}' per block.\n")
    results: dict[str, dict] = {}
    for pl in product_lines:
        pl_dir = blocks_root / pl
        if not pl_dir.is_dir():
            continue
        print(f"\n=== {pl} ===")
        for cat_dir in sorted(pl_dir.iterdir()):
            if not cat_dir.is_dir():
                continue
            for dwg in sorted(cat_dir.glob("*.dwg")):
                print(f"  {dwg.relative_to(PROJECT_ROOT)}:")
                try:
                    out = measure_dwg(app, dwg, args.layer)
                except Exception as exc:  # noqa: BLE001
                    print(f"    ERROR: {exc}", file=sys.stderr)
                    continue
                if out is None:
                    print(f"    no polyline on layer '{args.layer}'")
                    continue
                variant_id = dwg.stem
                diag = out.pop("_diagnostic")
                print(f"    in={out['in_offset']}  out={out['out_offset']}  "
                      f"(rail length={diag['rail_length']}\", width={diag['bus_width_in_dwg']}\")")
                results[variant_id] = out

    print("\n--- paste under mstp.ports in config/product_lines.json ---")
    print(json.dumps(results, indent=2))
    try:
        app.Quit()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
