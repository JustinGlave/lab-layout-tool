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
    _variant_point,
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


def _scrub_hood_page_top(
    session: CadSession,
    page_bounds: tuple[float, float, float, float],
    page_y_min: float,
    page_y_max: float,
    scrub_height_frac: float,
    notes: list[str],
) -> int:
    """Delete template bleed-through (VA-spec text, transformer block, etc.)
    from the upper strip of one hood page. Preserves the page border and
    title block — both extend below the strip's bottom so the "strict
    containment in [scrub_y_min, page_y_max]" check skips them.

    `page_y_min/page_y_max` are this page's world-coord Y bounds (already
    offset by the page index — caller's responsibility).

    `scrub_height_frac` = fraction of page height to scrub from the top.
    0.15 (top 15%) clears the VA-spec legend and transformer area on a
    typical CSCP template; tune via the `hood.scrub_height_frac` config
    knob if a future template has different positioning.
    """
    x_min, x_max, _, _ = page_bounds
    scrub_y_min = page_y_min + (page_y_max - page_y_min) * (1.0 - scrub_height_frac)

    swallow_notes: list[str] = []
    to_delete: list = []
    for ent in session.model_space:
        try:
            minp, maxp = ent.GetBoundingBox()
            bx_min, by_min = float(minp[0]), float(minp[1])
            bx_max, by_max = float(maxp[0]), float(maxp[1])
        except Exception as exc:  # noqa: BLE001
            _log_swallowed(
                "scrub_hood_page.bbox-read", exc, notes=swallow_notes,
            )
            continue
        # Strict containment — preserves anything that extends past the
        # page edges (border) or below the scrub strip (title block).
        if bx_min < x_min or bx_max > x_max:
            continue
        if by_min < scrub_y_min or by_max > page_y_max:
            continue
        to_delete.append(ent)

    deleted = 0
    for ent in to_delete:
        try:
            ent.Delete()
            deleted += 1
        except Exception as exc:  # noqa: BLE001
            _log_swallowed("scrub_hood_page.delete", exc, notes=swallow_notes)

    if deleted or swallow_notes:
        notes.append(
            f"    scrubbed {deleted} template entit"
            f"{'ies' if deleted != 1 else 'y'} from upper strip "
            f"(y in [{scrub_y_min:.0f}, {page_y_max:.0f}])"
        )
        notes.extend(f"    {n}" for n in swallow_notes)

    return deleted


def generate_hood_detail_pages(
    session: CadSession,
    project: dict,
    page_bounds: tuple[float, float, float, float],
    page_height: float,
    hood_blocks_dir: Path,
    starting_page_idx: int,
    log_path: Path | None = None,
    hood_cfg: dict | None = None,
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

    # Config knobs (defaults match the CSCP source layout as shipped).
    hood_cfg = hood_cfg or {}
    insertion_offset_x = float(hood_cfg.get("insertion_offset_x", 0.0))
    insertion_offset_y = float(hood_cfg.get("insertion_offset_y", 0.0))
    insertion_scale = float(hood_cfg.get("insertion_scale", 1.0))
    scrub_height_frac = float(hood_cfg.get("scrub_height_frac", 0.15))
    label_height = float(hood_cfg.get("label_height", 18.0))
    label_offset_x = float(hood_cfg.get("label_offset_x", 50.0))
    label_offset_y = float(hood_cfg.get("label_offset_y", -30.0))

    for combo_idx, (combo, tags) in enumerate(combos):
        world_page_idx = starting_page_idx + combo_idx
        page_y_offset = -world_page_idx * float(page_height)
        page_y_min = float(y_min) + page_y_offset
        page_y_max = float(y_max) + page_y_offset

        # 1. Scrub template bleed-through in the upper strip BEFORE inserting
        #    schematic blocks — the schematic doesn't exist yet, so the
        #    scrub can't damage it; only template content (VA-spec legend,
        #    transformer) ends up deleted.
        _scrub_hood_page_top(
            session, page_bounds,
            page_y_min=page_y_min, page_y_max=page_y_max,
            scrub_height_frac=scrub_height_frac, notes=notes,
        )

        # 2. Insert the schematic. Anchor for inserting the blocks — all 4
        #    source DWGs were saved at the same world origin, so inserting
        #    each at the same (ins_x, ins_y) reconstructs the original
        #    wiring layout. insertion_offset_x/y come from config so the
        #    schematic can be positioned without editing the source DWGs.
        ins_x = float(x_min) + insertion_offset_x
        ins_y = page_y_min + insertion_offset_y

        # Always insert the ACM. Failure here is fatal for this page — skip
        # to the next combo so the rest of the pages still render.
        try:
            insert_block(session, acm_path, ins_x, ins_y, scale=insertion_scale)
        except Exception as exc:  # noqa: BLE001
            _log_swallowed(
                f"hood_detail.acm[combo{combo_idx + 1}]", exc, notes=notes,
            )
            notes.append(
                f"  combo {combo_idx + 1} skipped (ACM insert failed)"
            )
            continue

        # Insert each enabled accessory at the same anchor with the same
        # scale so the schematic remains internally consistent.
        for key in HOOD_ACCESSORY_KEYS:
            if key not in combo:
                continue
            try:
                insert_block(
                    session, accessory_paths[key], ins_x, ins_y,
                    scale=insertion_scale,
                )
            except Exception as exc:  # noqa: BLE001
                _log_swallowed(
                    f"hood_detail.{key}[combo{combo_idx + 1}]",
                    exc,
                    notes=notes,
                )

        # 3. Add page label text at the top of the page. Placed AFTER the
        #    scrub so it doesn't get caught in the cleanup. Uses a plain
        #    "HOOD WIRING — ..." prefix (no ROOM: prefix) — the hood page
        #    skips update_room_text's ROOM:-prefix walk.
        label_x = float(x_min) + label_offset_x
        label_y = page_y_max + label_offset_y
        try:
            session.model_space.AddText(
                combo_label(combo, tags),
                _variant_point(label_x, label_y),
                label_height,
            )
        except Exception as exc:  # noqa: BLE001
            _log_swallowed(
                f"hood_detail.label[combo{combo_idx + 1}]", exc, notes=notes,
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


