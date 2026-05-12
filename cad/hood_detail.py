"""Per-package fume hood wiring detail pages.

Each FEV (fume hood exhaust valve) carries up to three optional accessories
(FHD500, ZPS, DHV) that attach to the ACM in the real world. The CAD output
includes one wiring schematic page per unique accessory combination across
all FEVs in the project — so a project with N hoods produces at most one
detail page per distinct combo, not N pages.

Layout (in world coords, per page):
  +─────────────────────────────────────────────────────────+
  │  ROOM: HOOD WIRING — TAGS: HOOD 1, HOOD 5 ...  (text)   │
  │                                                          │
  │   ┌──────────────────────┐     ┌─────────────────────┐  │
  │   │   FHD500 (purple)    │     │  ZPS (green)        │  │
  │   └──────────────────────┘     └─────────────────────┘  │
  │           │ wires                       │ wires          │
  │           ▼                             ▼                │
  │   ┌──────────────────────────────────────────────────┐  │
  │   │      ACM (yellow)                                │  │
  │   └──────────────────────────────────────────────────┘  │
  │           │ wires                                        │
  │           ▼                                              │
  │   ┌──────────────────────┐                              │
  │   │   DHV (red)          │                              │
  │   └──────────────────────┘                              │
  +─────────────────────────────────────────────────────────+

Each component lives in its own DWG under `blocks/<product>/HOOD/`:
  HOOD_ACM.dwg, HOOD_FHD500.dwg, HOOD_ZPS.dwg, HOOD_DHV.dwg

All four were saved at the same world origin so inserting each at the same
insertion point reconstructs the original layout (wires terminate exactly
at the ACM ports they're supposed to land on).

The title block on each hood page is filled by the standard
`update_title_block` walk (JOBNAME/JOBNUM/DRAFTER/DATE). The "REFERENCED
BY:" tag list is written into the page's ROOM: text slot via
`update_room_text` — the caller is expected to pass the hood-page names
through `room_names_expanded` alongside the lab-page names.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from .bricscad import (
    CadSession,
    _log_swallowed,
    insert_block,
)
from .migrate import HOOD_ACCESSORY_KEYS


def collect_hood_combos(
    rooms: list[dict],
) -> list[tuple[frozenset[str], list[str]]]:
    """Group FEVs across all rooms by their accessory combo.

    Returns a list of (accessory_keys_frozenset, [referencing_tags]) tuples
    in stable order: most accessories first, then alphabetical by the
    sorted accessory tuple. Each tag in the inner list points back to the
    FEV that produced this combo (used downstream as the "REFERENCED BY"
    annotation on the page).

    A frozenset() in the output means "no accessories selected" — per the
    feature spec, those still get a page (ACM-only).

    Pure function; safe to call without a CAD session.
    """
    combos: dict[frozenset[str], list[str]] = defaultdict(list)
    for room in rooms or []:
        for fev in room.get("FEV", []) or []:
            acc = fev.get("accessories") or {}
            enabled = frozenset(k for k, v in acc.items() if v)
            tag = (fev.get("tag", "") or "").strip() or "(untagged)"
            combos[enabled].append(tag)
    # Sort: most-accessories first (so full-page combos appear earliest
    # in the doc), then alphabetical by tuple for deterministic order.
    return sorted(
        combos.items(),
        key=lambda kv: (-len(kv[0]), tuple(sorted(kv[0]))),
    )


def combo_label(combo: frozenset[str], tags: list[str]) -> str:
    """Human-readable label for a hood detail page.

    Goes into the ROOM: text slot. Format:
        "HOOD WIRING — <acc list>: <tag list>"

    For combos with no accessories, the accessory list collapses to
    "ACM ONLY" so the page is still self-describing.
    """
    if combo:
        acc_part = ", ".join(
            _ACCESSORY_DISPLAY.get(k, k.upper()) for k in sorted(combo)
        )
    else:
        acc_part = "ACM ONLY"
    tag_part = ", ".join(sorted(set(tags)))
    return f"HOOD WIRING — {acc_part}: {tag_part}"


# Display labels for accessory keys when rendering the combo summary text.
# Kept in sync with ui/main_window.py:_HOOD_ACCESSORY_LABELS — duplicating
# the mapping is OK because the rendering context differs (this one is
# embedded in drawing text, the other one is for UI checkbox labels).
_ACCESSORY_DISPLAY = {
    "fhd500": "FHD500",
    "zps": "ZPS",
    "dhv": "DHV",
}


def generate_hood_detail_pages(
    session: CadSession,
    project: dict,
    page_bounds: tuple[float, float, float, float],
    page_height: float,
    hood_blocks_dir: Path,
    starting_page_idx: int,
    log_path: Path | None = None,
) -> int:
    """Insert one hood detail page per unique accessory combo across all
    FEVs in the project.

    `starting_page_idx` is the WORLD page index of the first hood page —
    i.e., the page just after the last lab page. Hood pages then stack
    downward at `page_height` intervals like every other page.

    Returns the number of hood pages emitted (0 when no FEVs exist or
    when required block files are missing).

    Required block files (under `hood_blocks_dir`):
      HOOD_ACM.dwg HOOD_FHD500.dwg HOOD_ZPS.dwg HOOD_DHV.dwg
    Missing any of these prints a stderr warning and returns 0 — the rest
    of the generation continues (lab pages still render).
    """
    rooms = project.get("rooms") or []
    combos = collect_hood_combos(rooms)
    if not combos:
        return 0

    acm_path = hood_blocks_dir / "HOOD_ACM.dwg"
    accessory_paths = {
        key: hood_blocks_dir / f"HOOD_{_ACCESSORY_DISPLAY[key]}.dwg"
        for key in HOOD_ACCESSORY_KEYS
    }

    missing = [
        p for p in [acm_path, *accessory_paths.values()] if not p.is_file()
    ]
    if missing:
        msg = (
            "Hood detail pages skipped: missing block files: "
            + ", ".join(str(p) for p in missing)
        )
        print(f"WARNING: {msg}", file=sys.stderr)
        if log_path is not None:
            try:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(f"\n{msg}\n")
            except Exception:  # noqa: BLE001
                # Log-write failure — already printed to stderr.
                pass
        return 0

    x_min, x_max, y_min, y_max = page_bounds
    notes: list[str] = []

    for combo_idx, (combo, tags) in enumerate(combos):
        world_page_idx = starting_page_idx + combo_idx
        page_y_offset = -world_page_idx * float(page_height)
        # Anchor for inserting the schematic blocks. All 4 source DWGs were
        # saved at the same world origin, so inserting each at the same
        # (ins_x, ins_y) reconstructs the original wiring layout.
        # Page x_min / y_min give us the lower-left corner of this page in
        # world coords; the source DWG's content is positioned around the
        # source's modelspace origin, which we map onto the page lower-left.
        ins_x = float(x_min)
        ins_y = float(y_min) + page_y_offset

        # Always insert the ACM. Failure here is fatal for this page — skip
        # to the next combo so the rest of the pages still render.
        try:
            insert_block(session, acm_path, ins_x, ins_y)
        except Exception as exc:  # noqa: BLE001
            _log_swallowed(
                f"hood_detail.acm[combo{combo_idx + 1}]", exc, notes=notes,
            )
            notes.append(
                f"  combo {combo_idx + 1} skipped (ACM insert failed)"
            )
            continue

        # Insert each enabled accessory at the same anchor.
        for key in HOOD_ACCESSORY_KEYS:
            if key not in combo:
                continue
            try:
                insert_block(session, accessory_paths[key], ins_x, ins_y)
            except Exception as exc:  # noqa: BLE001
                _log_swallowed(
                    f"hood_detail.{key}[combo{combo_idx + 1}]",
                    exc,
                    notes=notes,
                )

        notes.append(
            f"  combo {combo_idx + 1} (page {world_page_idx + 1}): "
            f"{combo_label(combo, tags)}"
        )

    if log_path is not None and notes:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"\n--- Hood detail pages "
                    f"({len(combos)} unique combo"
                    f"{'s' if len(combos) != 1 else ''}, "
                    f"starting at world page {starting_page_idx + 1}) ---\n"
                    + "\n".join(notes) + "\n"
                )
        except Exception:  # noqa: BLE001
            # Log-write failure — leave silent. _log_swallowed's IO fallback
            # would target the same file and could fail again recursively.
            pass

    return len(combos)


def hood_page_names(combos: list[tuple[frozenset[str], list[str]]]) -> list[str]:
    """Returns one room-text-slot name per hood page.

    Caller appends these to `room_names_expanded` in app.py so
    `update_room_text` populates the "ROOM:" text slot on each hood page
    with the combo label (e.g., "HOOD WIRING — FHD500, ZPS: HOOD 1, HOOD 5").

    The "ROOM:" prefix prepended by `update_room_text` is awkward on hood
    pages but functional for v1; a future refinement could give that
    function a per-name prefix override.
    """
    return [combo_label(combo, tags) for combo, tags in combos]
