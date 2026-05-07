"""inspect_template.py — open a DWG and dump every block reference along with
its attribute tags + current values, so we know what attribute names to target
when auto-filling on generation.

Usage:
    .venv/Scripts/python tools/inspect_template.py
        # default — inspects templates/Background.dwg
    .venv/Scripts/python tools/inspect_template.py blocks/misc/pbc_network.dwg
        # inspect any DWG by path
"""

from __future__ import annotations

import sys
from pathlib import Path

import pythoncom  # type: ignore
import win32com.client  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = PROJECT_ROOT / "templates" / "Background.dwg"
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
    raise RuntimeError(f"COM connect failed: {last_err}")


def main() -> int:
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        if not target.is_absolute():
            target = PROJECT_ROOT / target
    else:
        target = DEFAULT_TEMPLATE
    if not target.is_file():
        print(f"File not found: {target}", file=sys.stderr)
        return 1

    app = connect_app(visible=False)
    try:
        try:
            doc = app.Documents.Open(str(target), True)
        except TypeError:
            doc = app.Documents.Open(str(target))

        try:
            rel = target.relative_to(PROJECT_ROOT)
        except ValueError:
            rel = target
        print(f"Inspecting: {rel}\n")

        def dump_container(label: str, container) -> tuple[int, int, dict[str, int]]:
            n_blocks = 0
            n_with_attrs = 0
            entity_kinds: dict[str, int] = {}
            for ent in container:
                try:
                    name = ent.ObjectName
                except Exception:  # noqa: BLE001
                    continue
                entity_kinds[name] = entity_kinds.get(name, 0) + 1
                if name != "AcDbBlockReference":
                    continue
                n_blocks += 1
                try:
                    block_name = ent.Name
                    handle = ent.Handle
                    ip = ent.InsertionPoint
                    ip_str = f"({ip[0]:.2f},{ip[1]:.2f})"
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{label}] block ref (uninspectable): {exc}", file=sys.stderr)
                    continue
                try:
                    attrs = ent.GetAttributes()
                except Exception:
                    attrs = None
                if not attrs:
                    print(f"  [{label}] block '{block_name}' @ {ip_str}  handle={handle}  (no attributes)")
                    continue
                n_with_attrs += 1
                print(f"  [{label}] block '{block_name}' @ {ip_str}  handle={handle}:")
                for a in attrs:
                    try:
                        tag = a.TagString
                        val = a.TextString
                        print(f"      {tag!r:24s} = {val!r}")
                    except Exception as exc:  # noqa: BLE001
                        print(f"      (attr error: {exc})")
            return n_blocks, n_with_attrs, entity_kinds

        # Model space
        print("=== Model space ===")
        mb, ma, mk = dump_container("MS", doc.ModelSpace)
        print(f"  total entities: {sum(mk.values())}")
        for k, c in sorted(mk.items(), key=lambda x: -x[1]):
            print(f"    {k}: {c}")

        # Paper-space layouts
        print("\n=== Paper-space layouts ===")
        try:
            layouts = doc.Layouts
            for layout in layouts:
                try:
                    layout_name = layout.Name
                except Exception:  # noqa: BLE001
                    layout_name = "?"
                if layout_name.lower() == "model":
                    continue
                try:
                    block = layout.Block
                except Exception:  # noqa: BLE001
                    continue
                print(f"\n--- Layout: {layout_name} ---")
                pb, pa, pk = dump_container(f"PS:{layout_name}", block)
                print(f"  total entities: {sum(pk.values())}")
                for k, c in sorted(pk.items(), key=lambda x: -x[1]):
                    print(f"    {k}: {c}")
        except Exception as exc:  # noqa: BLE001
            print(f"  (could not iterate layouts: {exc})")

        # All block definitions (regardless of whether they're inserted)
        print("\n=== Block definitions in the file ===")
        try:
            for blk in doc.Blocks:
                try:
                    bn = blk.Name
                    if bn.startswith("*"):
                        continue  # anonymous
                    n = sum(1 for _ in blk)
                    print(f"  {bn}  ({n} entities)")
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            print(f"  (could not iterate Blocks: {exc})")
        doc.Close(False)
    finally:
        try:
            app.Quit()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
