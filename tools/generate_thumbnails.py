"""generate_thumbnails.py — bake a PNG preview next to every DWG in blocks/.

For each `blocks/<line>/<CATEGORY>/*.dwg` (and `blocks/misc/*.dwg`), opens
the DWG in BricsCAD, ZOOMs to extents, and exports a PNG of the current
view alongside the DWG (`<stem>.png`). The runtime UI picks these up
automatically — `cad/blocks.py:list_variants` looks for a sibling .png
when populating each BlockVariant, and the variant dropdown in the form
displays the icon when present.

Run when you add or modify a block DWG:

    .venv/Scripts/python tools/generate_thumbnails.py

Optional flags:
    --product LINE_ID   Only process blocks/<LINE_ID>/. Default: all lines.
    --misc              Also process blocks/misc/*.dwg.
    --force             Re-render even if a PNG already exists and is newer.
    --visible           Show the BricsCAD window during render. Default off
                        (BricsCAD still needs to launch — PNGOUT uses the
                        active viewport — but window stays minimized).

Implementation notes:
    BricsCAD's _PNGOUT command exports the current screen viewport as a
    PNG. Resolution follows the viewport's pixel size, which is why the
    tool sets a fixed window size before rendering. FILEDIA is toggled
    off so PNGOUT runs non-interactively.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pythoncom  # type: ignore
import win32com.client  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BLOCKS_DIR = PROJECT_ROOT / "blocks"
PROG_IDS = ("BricscadApp.AcadApplication", "AutoCAD.Application")

# Window size used while rendering. ~768×512 gives a clear preview that's
# crisp at the 48×32 dropdown size and reasonable in larger contexts.
RENDER_W, RENDER_H = 768, 512


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


def find_dwgs(product_id: "str | None", include_misc: bool) -> list[Path]:
    """List DWG files to process."""
    out: list[Path] = []
    if product_id:
        roots = [BLOCKS_DIR / product_id]
    else:
        # All product-line directories: any subdir of blocks/ except misc and _reference
        roots = [
            d for d in BLOCKS_DIR.iterdir()
            if d.is_dir() and d.name not in ("misc", "_reference") and not d.name.startswith("_")
        ]
    if include_misc:
        roots.append(BLOCKS_DIR / "misc")
    for root in roots:
        if not root.is_dir():
            continue
        out.extend(sorted(root.rglob("*.dwg")))
    return out


def needs_render(dwg: Path, force: bool) -> bool:
    if force:
        return True
    png = dwg.with_suffix(".png")
    if not png.is_file():
        return True
    try:
        return png.stat().st_mtime < dwg.stat().st_mtime
    except Exception:  # noqa: BLE001
        return True


def render_one(app, dwg: Path) -> bool:
    """Open `dwg`, zoom to extents, export `<dwg>.png`. Returns True on success."""
    png = dwg.with_suffix(".png")
    if png.is_file():
        try:
            png.unlink()
        except Exception:  # noqa: BLE001
            pass
    try:
        doc = app.Documents.Open(str(dwg))
    except Exception as e:  # noqa: BLE001
        print(f"  ! open failed for {dwg.name}: {e}")
        return False

    # Suppress file dialogs so PNGOUT runs non-interactively.
    try:
        doc.SetVariable("FILEDIA", 0)
    except Exception:  # noqa: BLE001
        pass

    try:
        # ZOOM EXTENTS so the whole block fills the rendered viewport.
        doc.SendCommand('(command "_ZOOM" "_E") ')
        try:
            _ = doc.GetVariable("CDATE")  # flush command queue
        except Exception:  # noqa: BLE001
            pass
        # Export the active view as PNG. PNGOUT in BricsCAD takes
        # filename then a selection — _A means all entities visible
        # in the viewport.
        doc.SendCommand(
            f'(command "_PNGOUT" "{str(png).replace(chr(92), chr(92)*2)}" "_A" "") '
        )
        try:
            _ = doc.GetVariable("CDATE")
        except Exception:  # noqa: BLE001
            pass
        try:
            pythoncom.PumpWaitingMessages()
        except Exception:  # noqa: BLE001
            pass
        # Brief pause for the file to land on disk
        for _ in range(20):
            if png.is_file():
                break
            time.sleep(0.1)
    finally:
        try:
            doc.SetVariable("FILEDIA", 1)
        except Exception:  # noqa: BLE001
            pass
        try:
            doc.Close(False)
        except Exception:  # noqa: BLE001
            pass

    if not png.is_file():
        print(f"  ! no PNG produced for {dwg.name}")
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--product", default=None,
                    help="Only process blocks/<id>/ (cscp, celeris_ii, …)")
    ap.add_argument("--misc", action="store_true",
                    help="Also process blocks/misc/")
    ap.add_argument("--force", action="store_true",
                    help="Re-render even if a fresh PNG already exists")
    ap.add_argument("--visible", action="store_true",
                    help="Show BricsCAD during render (default: hidden)")
    args = ap.parse_args()

    pythoncom.CoInitialize()
    try:
        dwgs = find_dwgs(args.product, args.misc)
        if not dwgs:
            print("No DWG files matched.")
            return 0
        todo = [d for d in dwgs if needs_render(d, args.force)]
        if not todo:
            print(f"All {len(dwgs)} DWGs already have up-to-date thumbnails.")
            return 0
        print(f"Rendering {len(todo)}/{len(dwgs)} thumbnails …")

        app = connect_app(visible=args.visible)
        ok = 0
        for i, dwg in enumerate(todo, 1):
            rel = dwg.relative_to(PROJECT_ROOT)
            print(f"  [{i}/{len(todo)}] {rel}")
            if render_one(app, dwg):
                ok += 1
        print(f"Done. {ok}/{len(todo)} succeeded.")
        return 0 if ok == len(todo) else 1
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
