"""straighten_polylines.py — snap near-horizontal / near-vertical segments of
LWPOLYLINEs in every valve block DWG to be exactly straight.

The hand-drawn rails in some block DWGs have segments that are off-axis by tiny
amounts (e.g. ΔY = 0.4375" on a "horizontal" run, or ΔX = 0.75" on a "vertical"
run). That causes weird rendering at the wire-width and small visible gaps when
the bus is composed across blocks. This script finds segments where the off-axis
delta is below a threshold and snaps them to exact horizontal or vertical.

Run dry-run first:
    .venv/Scripts/python tools/straighten_polylines.py
Apply changes (with .bak backups):
    .venv/Scripts/python tools/straighten_polylines.py --apply

Threshold default 1.0". Tweak with --threshold N.

Backups: every modified .dwg is copied to <name>.dwg.bak before the save.
Re-running will OVERWRITE the previous .bak — back up your blocks elsewhere
if you need a deeper rollback history.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

import pythoncom  # type: ignore
import win32com.client  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROG_IDS = ("BricscadApp.AcadApplication", "AutoCAD.Application")


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
        return app.Documents.Open(str(dwg), False)  # not read-only — we may save
    except TypeError:
        return app.Documents.Open(str(dwg))


def _is_rpc_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return ("rpc" in s or "remote procedure call" in s
            or "-2147023174" in s or "-2147023170" in s)


def straighten_polyline(pl, threshold: float) -> int:
    """Returns count of segments straightened in this polyline."""
    try:
        coords = list(pl.Coordinates)
    except Exception:  # noqa: BLE001
        return 0
    if len(coords) < 4:
        return 0

    n = len(coords) // 2
    pts = [(coords[2 * i], coords[2 * i + 1]) for i in range(n)]
    new_pts = list(pts)
    fixed = 0

    for i in range(len(new_pts) - 1):
        x1, y1 = new_pts[i]
        x2, y2 = new_pts[i + 1]
        dx, dy = (x2 - x1), (y2 - y1)
        if dx == 0 and dy == 0:
            continue
        # Nearly horizontal: dy small, dx significant
        if abs(dy) > 1e-9 and abs(dy) < threshold and abs(dx) > threshold:
            avg_y = (y1 + y2) / 2.0
            new_pts[i] = (x1, avg_y)
            new_pts[i + 1] = (x2, avg_y)
            fixed += 1
        # Nearly vertical: dx small, dy significant
        elif abs(dx) > 1e-9 and abs(dx) < threshold and abs(dy) > threshold:
            avg_x = (x1 + x2) / 2.0
            new_pts[i] = (avg_x, y1)
            new_pts[i + 1] = (avg_x, y2)
            fixed += 1

    if fixed == 0:
        return 0

    # Write back
    flat = []
    for x, y in new_pts:
        flat.append(float(x))
        flat.append(float(y))
    new_var = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8, flat
    )
    try:
        pl.Coordinates = new_var
    except Exception as exc:  # noqa: BLE001
        print(f"      WARN couldn't write coords: {exc}", file=sys.stderr)
        return 0
    return fixed


def process_dwg(app, dwg: Path, threshold: float, apply: bool) -> Optional[int]:
    """Open the DWG, straighten polylines. Returns number of segments fixed
    (or None on error)."""
    for attempt in (1, 2, 3):
        try:
            doc = open_doc(app, dwg)
            break
        except Exception as exc:  # noqa: BLE001
            if _is_rpc_error(exc) and attempt < 3:
                print(f"  RPC failure (attempt {attempt}) — reconnecting…", file=sys.stderr)
                time.sleep(2.0)
                try:
                    app = connect_app()
                except Exception:  # noqa: BLE001
                    time.sleep(2.0)
                continue
            print(f"  open failed: {exc}", file=sys.stderr)
            return None
    else:
        return None

    total_fixed = 0
    poly_changed = 0
    try:
        for ent in doc.ModelSpace:
            try:
                name = ent.ObjectName
            except Exception:  # noqa: BLE001
                continue
            if name not in ("AcDbPolyline", "AcDb2dPolyline"):
                continue
            n = straighten_polyline(ent, threshold)
            if n > 0:
                total_fixed += n
                poly_changed += 1
        if apply and total_fixed > 0:
            doc.Save()
        # Always close (with discard if not applying)
        doc.Close(True if apply and total_fixed > 0 else False)
    except Exception as exc:  # noqa: BLE001
        print(f"  process error: {exc}", file=sys.stderr)
        try:
            doc.Close(False)
        except Exception:  # noqa: BLE001
            pass
        return None

    return total_fixed if poly_changed else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually save changes. Default is dry-run (logs only).")
    ap.add_argument("--threshold", type=float, default=1.0,
                    help="Off-axis delta tolerance in inches (default 1.0).")
    ap.add_argument("--product-line", default=None,
                    help="Limit to one product line. Default: all.")
    args = ap.parse_args()

    blocks_root = PROJECT_ROOT / "blocks"
    dwgs: list[Path] = []
    pls = ([args.product_line] if args.product_line
           else [d.name for d in blocks_root.iterdir()
                 if d.is_dir() and d.name not in ("misc",)])
    for pl in pls:
        pl_dir = blocks_root / pl
        if not pl_dir.is_dir():
            continue
        for cat_dir in pl_dir.iterdir():
            if not cat_dir.is_dir():
                continue
            dwgs.extend(sorted(cat_dir.glob("*.dwg")))

    if not dwgs:
        print("No DWGs found.")
        return 1

    print(f"{'APPLY' if args.apply else 'DRY-RUN'} mode | threshold={args.threshold}\"\n")

    app = connect_app(visible=False)
    grand_total = 0
    files_changed = 0

    for dwg in dwgs:
        rel = dwg.relative_to(PROJECT_ROOT)
        if args.apply:
            backup = dwg.with_suffix(".dwg.bak")
            shutil.copy2(dwg, backup)

        fixed = process_dwg(app, dwg, args.threshold, args.apply)
        if fixed is None:
            print(f"  {rel}  ERROR")
            continue
        if fixed > 0:
            print(f"  {rel}  {fixed} segments {'fixed' if args.apply else 'WOULD be fixed'}")
            files_changed += 1
            grand_total += fixed
        else:
            print(f"  {rel}  clean")

    print()
    print(f"{'Applied' if args.apply else 'Would apply'}: {grand_total} segment(s) "
          f"across {files_changed} file(s).")
    if not args.apply and grand_total > 0:
        print("Re-run with --apply to commit changes (creates .dwg.bak first).")

    # Quit BricsCAD so it doesn't linger after the script.
    try:
        app.Quit()
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
