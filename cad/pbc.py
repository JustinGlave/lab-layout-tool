"""PBC network drawing — first-page-of-the-DWG generator.

Each room can declare 0+ Phoenix Building Controllers (PBCs). When any
project room has at least one, this module draws a network page (or
several, wrapping at `_PBC_PER_PAGE` PBCs each):

  - BMS NETWORK ellipse + horizontal trunk wire across the page top
  - Per PBC: NET label, vertical branch wire down to the PBC body block,
    inserted with TAG / DEVICE_NUM / MAC / NETWORK_NUM / DEVICE_NAME attrs
  - Under each PBC: COM1 column (left, slot_cx − 25) and COM2 column
    (right, slot_cx + 25). Each column is the linked valves for that
    com_trunk, sorted SUPPLY → GEX → HOOD → AUX top-to-bottom, with a
    LON4 terminator at the bottom (currently the EOL block is reused as
    a stand-in for LON4).

Lower-level CAD helpers (block insertion, polyline drawing, bbox math,
swallowed-exception logging) live in `cad/bricscad.py` and are imported
here. This module is purely PBC-aware composition over those primitives.

Public entry point: `generate_pbc_page(session, project, page_bounds, …)`
which returns the number of PBC pages drawn (0 if no room has any PBCs).
"""

from __future__ import annotations

import sys
from pathlib import Path

from .blocks import CATEGORIES, load_config
from .bricscad import (
    CadSession,
    _bbox,
    _log_swallowed,
    _variant_point,
    add_polyline_with_width,
    insert_block,
    insert_block_at_grid_cell,
)


# Per-column ordering, top-to-bottom: Supply → GEX → Fume Hood → AUX
_PBC_COL_ORDER = ["SAV", "GEX", "FEV", "AUX"]

# Category → PBC sub-block filename (relative to blocks/misc/)
_PBC_SUB_BLOCK = {
    "SAV": "pbc_valve_supply.dwg",
    "GEX": "pbc_valve_gex.dwg",
    "FEV": "pbc_valve_hood.dwg",
    "AUX": "pbc_valve_aux.dwg",
}


# Geometry constants — sourced from config/product_lines.json:pbc so the
# runtime drawing code and tools/generate_pbc_blocks.py share a single
# truth source. Fallbacks match the historical hardcoded values, so a
# missing/malformed config still produces a runnable build.
def _load_pbc_geometry() -> dict:
    try:
        return load_config().get("pbc", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


_PBC_GEOM = _load_pbc_geometry()

# Maximum PBCs that lay out cleanly side-by-side on one page (per Justin).
# Beyond this, the rest wrap onto additional PBC pages.
_PBC_PER_PAGE = int(_PBC_GEOM.get("per_page", 7))

# PBC body block geometry. AddEllipse(_pt(25, 12), _pt(15, 0), 0.45) →
# oval centered at y=12 with half-minor-axis = 15 * 0.45 = 6.75, so bottom
# edge sits at y = 5.25 (= _PBC_COM_OVAL_BOTTOM_DY).
_PBC_BODY_W = float(_PBC_GEOM.get("body_w", 100.0))
_PBC_BODY_H = float(_PBC_GEOM.get("body_h", 140.0))
_PBC_COM1_OVAL_DX = float(_PBC_GEOM.get("com1_oval_dx", 25.0))
_PBC_COM2_OVAL_DX = float(_PBC_GEOM.get("com2_oval_dx", 75.0))
_PBC_COM_OVAL_BOTTOM_DY = float(_PBC_GEOM.get("com_oval_bottom_dy", 5.25))

# Valve sub-block bbox (HOOD has an FHD spur extending the bbox right; bbox-snap
# uses the bbox bottom-left, so the type-label region is the leftmost 50w).
_PBC_SUB_W = float(_PBC_GEOM.get("sub_w", 50.0))
_PBC_SUB_H = float(_PBC_GEOM.get("sub_h", 32.0))
_PBC_SUB_VGAP = float(_PBC_GEOM.get("sub_vgap", 10.0))


def _set_attrs(ref, values: dict[str, str]) -> None:
    """Set ATTRIB values on an inserted block reference, matching by tag (case-insensitive)."""
    try:
        attrs = ref.GetAttributes()
    except Exception as exc:  # noqa: BLE001
        _log_swallowed("_set_attrs.GetAttributes", exc)
        return
    if not attrs:
        return
    upper = {k.upper(): str(v) for k, v in values.items() if v is not None}
    for a in attrs:
        try:
            tag = str(a.TagString).upper()
        except Exception as exc:  # noqa: BLE001
            _log_swallowed("_set_attrs.TagString-read", exc)
            continue
        if tag in upper:
            try:
                a.TextString = upper[tag]
            except Exception as exc:  # noqa: BLE001
                _log_swallowed(f"_set_attrs.TextString-write {tag!r}", exc)


def _draw_bms_cloud(session: CadSession, cx: float, cy: float) -> None:
    """Draw a labelled BMS NETWORK ellipse (stand-in for a true cloud shape)."""
    # 200w × 60h ellipse centered at (cx, cy)
    session.model_space.AddEllipse(
        _variant_point(cx, cy), _variant_point(100.0, 0.0), 0.30
    )
    label = "BMS NETWORK"
    session.model_space.AddText(
        label,
        _variant_point(cx - len(label) * 2.5, cy - 4.0),
        8.0,
    )


def _find_valve_in_room(room: dict, valve_tag: str) -> dict | None:
    """Return {category, label, variant_id, dwg_path, tag} for a valve in the
    room with the given tag, or None if not found."""
    valve_tag = (valve_tag or "").strip()
    if not valve_tag:
        return None
    for cat in CATEGORIES:
        for entry in room.get(cat, []) or []:
            if (entry.get("tag", "") or "").strip() == valve_tag:
                return {"category": cat, **entry}
    return None


def _place_pbc_valve_column(
    session: CadSession,
    valves: list[dict],
    room_name: str,
    col_x_center: float,
    col_top_y: float,
    pbc_blocks_dir: Path,
    eol_dwg_path: Path | None,
    notes: list[str],
) -> tuple[float | None, float | None]:
    """Insert valve sub-blocks down a single COM column, plus a LON4 terminator
    at the bottom (using the eol block as a stand-in). Sub-block bbox-bottom-left
    is snapped so the leftmost 50w of the bbox is centered on `col_x_center`.

    The comm wire is drawn ONLY in the gaps between adjacent blocks (and from
    the last block down to the LON4 terminator). The first block's top is
    returned so the caller can connect from the PBC's COM oval to it; the wire
    must never pass through a sub-block.

    Returns (column_top_world_y, column_bottom_world_y) — the wire entry point
    at the top and the LON4 top wire end — or (None, None) if the column is empty.
    """
    if not valves:
        return (None, None)

    # Place sub-blocks top-to-bottom and remember each block's top/bottom Y
    sub_x_left = col_x_center - _PBC_SUB_W / 2.0
    cur_top = col_top_y
    block_tops: list[float] = []
    block_bottoms: list[float] = []
    for v in valves:
        target_y = cur_top - _PBC_SUB_H
        sub_filename = _PBC_SUB_BLOCK.get(v["category"])
        sub_path = pbc_blocks_dir / sub_filename if sub_filename else None
        # If the sub-block can't be inserted (unknown category, missing
        # filename, or missing DWG file on disk), drop a visible placeholder
        # rectangle in its slot so the user sees there's a problem at THIS
        # position — silent skipping just shifts every later valve up and
        # makes debugging mysterious. The wire chain still connects through
        # the placeholder so the column reads as a single chain visually.
        missing_reason = None
        if not sub_filename:
            missing_reason = f"unknown category {v.get('category')!r}"
        elif sub_path is None or not sub_path.is_file():
            missing_reason = f"file not found ({sub_path.name if sub_path else '?'})"

        if missing_reason is None:
            ref = insert_block_at_grid_cell(session, sub_path, sub_x_left, target_y)
            _set_attrs(ref, {
                "ROOM": room_name,
                "TAG":  v.get("tag", ""),
            })
        else:
            # Outline rectangle the same size as a real sub-block, plus a
            # MISSING label so it's obvious in print preview / on-screen.
            x0, y0 = sub_x_left, target_y
            x1, y1 = sub_x_left + _PBC_SUB_W, target_y + _PBC_SUB_H
            add_polyline_with_width(
                session,
                [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)],
                0.5,
            )
            session.model_space.AddText(
                f"MISSING {v.get('category', '?')}",
                _variant_point(x0 + 4.0, y0 + _PBC_SUB_H / 2.0 - 3.0),
                6.0,
            )
            session.model_space.AddText(
                v.get("tag", "") or "?",
                _variant_point(x0 + 4.0, y0 + 4.0),
                4.0,
            )
            notes.append(
                f"  PBC column: placeholder for {v.get('tag', '?')!r} "
                f"(category {v.get('category', '?')!r}: {missing_reason})"
            )
        block_tops.append(cur_top)
        block_bottoms.append(target_y)
        cur_top = target_y - _PBC_SUB_VGAP

    if not block_bottoms:
        return (None, None)

    # Inter-block wire segments (in the gaps only — never through a block).
    for i in range(len(block_bottoms) - 1):
        gap_top = block_bottoms[i]
        gap_bottom = block_tops[i + 1]
        add_polyline_with_width(session, [
            (col_x_center, gap_top),
            (col_x_center, gap_bottom),
        ], 0.5)

    # Terminator below the last block. Currently uses the existing eol.dwg as
    # a stand-in until a dedicated LON4 block is authored. Whatever the block
    # itself shows (e.g. "EOL") is what reads on the page — no extra label
    # added here, since stacking a "LON4" caption under an "EOL" block is
    # confusing.
    last_block_bottom = block_bottoms[-1]
    term_top = last_block_bottom - _PBC_SUB_VGAP
    if eol_dwg_path is not None and eol_dwg_path.is_file():
        ref = insert_block(session, eol_dwg_path, 0.0, 0.0)
        try:
            minp, maxp = _bbox(ref)
            ew = maxp[0] - minp[0]
            eh = maxp[1] - minp[1]
            new_min_x = col_x_center - ew / 2.0
            new_min_y = term_top - eh
            dx = new_min_x - minp[0]
            dy = new_min_y - minp[1]
            if dx != 0.0 or dy != 0.0:
                ref.Move(_variant_point(0.0, 0.0), _variant_point(dx, dy))
        except Exception as exc:  # noqa: BLE001
            _log_swallowed(
                "_place_pbc_valve_column.LON4-bbox-snap", exc, notes=notes,
            )

    # Wire from last block bottom down to the terminator top edge.
    add_polyline_with_width(session, [
        (col_x_center, last_block_bottom),
        (col_x_center, term_top),
    ], 0.5)

    return (col_top_y, last_block_bottom)


def _scrub_pbc_page_top(
    session: CadSession,
    page_bounds: tuple[float, float, float, float],
    log_path: Path | None = None,
) -> int:
    """Delete lab-template content from the upper strip of THIS page (VA
    rating callouts, transformer diagram, ROOM: label, etc.) so the PBC
    network drawing has a clean canvas. Only entities whose ENTIRE bbox sits
    inside the scrub zone are removed — this preserves the orange page-border
    polyline (whose bbox spans the whole page) while removing the smaller
    lab callouts that live in the top strip.

    `page_bounds` is (x_min, x_max, y_min, y_max) for the page we're scrubbing
    (so the function works for page 1, page 2, etc.).

    Returns the number of entities deleted.
    """
    x_min, x_max, y_min, y_max = page_bounds
    # Top ~14% of the page (corresponds to y > 850 on page 1 with 33..984 bounds).
    scrub_y_min = y_min + 0.86 * (y_max - y_min)

    swallow_notes: list[str] = []
    to_delete: list = []
    for ent in session.model_space:
        try:
            minp, maxp = ent.GetBoundingBox()
            bx_min, by_min = float(minp[0]), float(minp[1])
            bx_max, by_max = float(maxp[0]), float(maxp[1])
        except Exception as exc:  # noqa: BLE001
            _log_swallowed(
                "scrub_pbc_page.bbox-read", exc, notes=swallow_notes,
            )
            continue
        # Strict containment — preserves the page border (whose bbox is the
        # whole page rectangle) while catching anything that lives inside the
        # upper strip of this page.
        if bx_min < x_min or bx_max > x_max:
            continue
        if by_min < scrub_y_min or by_max > y_max:
            continue
        to_delete.append(ent)

    deleted = 0
    for ent in to_delete:
        try:
            ent.Delete()
            deleted += 1
        except Exception as exc:  # noqa: BLE001
            _log_swallowed("scrub_pbc_page.delete", exc, notes=swallow_notes)

    if log_path is not None:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"\n--- PBC page scrub ---\n  removed {deleted} entities "
                    f"(strip y in [{scrub_y_min:.0f}, {y_max:.0f}])\n"
                )
                if swallow_notes:
                    f.write("\n".join(swallow_notes) + "\n")
        except Exception:  # noqa: BLE001
            # Log-write failure — leave silent. _log_swallowed's IO fallback
            # would target the same file and could fail again recursively.
            pass
    return deleted


def _render_pbc_page(
    session: CadSession,
    page_pbcs: list[tuple[dict, dict]],
    page_bounds: tuple[float, float, float, float],
    starting_net_index: int,
    pbc_body_path: Path,
    pbc_blocks_dir: Path,
    eol_dwg_path: Path | None,
    notes: list[str],
) -> None:
    """Render one PBC page given its bounds and the slice of (room, pbc) pairs
    that belong on it. `starting_net_index` is the index of the first PBC on
    this page within the project-wide PBC list (used for fallback NET<n>
    labelling when a PBC has no network_number set).
    """
    x_min, x_max, y_min, y_max = page_bounds

    # Scrub this page's upper strip (VA boxes / transformer / ROOM: text).
    _scrub_pbc_page_top(session, page_bounds)

    usable_left = x_min + 45.0
    usable_right = x_max - 10.0
    usable_width = max(usable_right - usable_left, 100.0)

    # Vertical zones, expressed relative to this page's y_min/y_max.
    bms_cy        = y_min + (y_max - y_min) * 0.95
    bms_bottom_y  = bms_cy - 30.0
    trunk_y       = bms_cy - 70.0
    pbc_top_y     = trunk_y - 20.0
    pbc_bottom_y  = pbc_top_y - _PBC_BODY_H
    col_top_y     = pbc_bottom_y - 30.0

    page_cx = (usable_left + usable_right) / 2.0
    _draw_bms_cloud(session, page_cx, bms_cy)

    n = len(page_pbcs)
    # Slots fill from the left edge — even when the last PBC page has fewer
    # than _PBC_PER_PAGE PBCs, slot positions stay aligned with full pages.
    slot_denom = max(n, 1) if n >= _PBC_PER_PAGE else _PBC_PER_PAGE
    slot_width = usable_width / slot_denom

    trunk_pts: list[tuple[float, float]] = []

    for j, (room, pbc) in enumerate(page_pbcs):
        slot_cx = usable_left + slot_width * (j + 0.5)
        pbc_x = slot_cx - _PBC_BODY_W / 2.0
        pbc_y = pbc_bottom_y

        global_idx = starting_net_index + j
        net_num = (pbc.get("network_number") or "").strip() or str(global_idx + 1)

        ref = insert_block_at_grid_cell(session, pbc_body_path, pbc_x, pbc_y)
        _set_attrs(ref, {
            "TAG":         pbc.get("tag", "") or "",
            "DEVICE_NUM":  pbc.get("device_number", "") or "",
            "MAC":         pbc.get("mac", "") or "",
            "NETWORK_NUM": str(net_num),
            "DEVICE_NAME": pbc.get("device_name", "") or "",
        })

        # NET label — top-left of the branch, just above the BMS trunk
        label = f"NET{net_num}"
        net_h = 7.0
        net_text_w = len(label) * net_h * 0.6
        net_x = slot_cx - net_text_w - 4.0
        net_y = trunk_y + 4.0
        session.model_space.AddText(
            label, _variant_point(net_x, net_y), net_h,
        )

        # Branch wire: trunk → top of PBC
        add_polyline_with_width(
            session, [(slot_cx, trunk_y), (slot_cx, pbc_top_y)], 0.5,
        )

        # Resolve linked valves into COM1 / COM2 lists
        com1: list[dict] = []
        com2: list[dict] = []
        for link in pbc.get("links", []) or []:
            tag = (link.get("valve_tag") or "").strip()
            # Accept int (1/2), str "1"/"2", or "COM1"/"COM2" (case-insensitive).
            # Default is COM1. Tolerant parsing so the data model can evolve
            # without crashing on cached projects.
            raw_trunk = link.get("com_trunk", 1)
            _trunk_str = str(raw_trunk if raw_trunk is not None else "").strip().upper()
            trunk_n = 2 if _trunk_str in ("2", "COM2") else 1
            valve = _find_valve_in_room(room, tag)
            if valve is None:
                notes.append(
                    f"  PBC {pbc.get('tag', '?')!r} (room {room.get('name', '?')!r}): "
                    f"linked valve tag {tag!r} not found in room"
                )
                continue
            (com1 if trunk_n == 1 else com2).append(valve)

        com1.sort(key=lambda v: _PBC_COL_ORDER.index(v["category"])
                  if v["category"] in _PBC_COL_ORDER else 99)
        com2.sort(key=lambda v: _PBC_COL_ORDER.index(v["category"])
                  if v["category"] in _PBC_COL_ORDER else 99)

        # Columns sit DIRECTLY UNDER the PBC body, aligned with the COM ovals
        # (oval X = pbc_x + 25 / pbc_x + 75 = slot_cx ± 25). This keeps each
        # PBC's full footprint inside its slot width so adjacent PBCs' COM2
        # and COM1 columns can never overlap.
        col1_cx = slot_cx - 25.0
        col2_cx = slot_cx + 25.0
        room_name = room.get("name", "") or ""

        col1_top, _col1_bottom = _place_pbc_valve_column(
            session, com1, room_name, col1_cx, col_top_y,
            pbc_blocks_dir, eol_dwg_path, notes,
        )
        col2_top, _col2_bottom = _place_pbc_valve_column(
            session, com2, room_name, col2_cx, col_top_y,
            pbc_blocks_dir, eol_dwg_path, notes,
        )

        # Wire from each COM oval bottom edge down to its valve column top.
        com1_oval = (pbc_x + _PBC_COM1_OVAL_DX, pbc_y + _PBC_COM_OVAL_BOTTOM_DY)
        com2_oval = (pbc_x + _PBC_COM2_OVAL_DX, pbc_y + _PBC_COM_OVAL_BOTTOM_DY)
        link_y = pbc_y - 15.0
        if col1_top is not None:
            add_polyline_with_width(session, [
                com1_oval,
                (com1_oval[0], link_y),
                (col1_cx, link_y),
                (col1_cx, col1_top),
            ], 0.5)
        if col2_top is not None:
            add_polyline_with_width(session, [
                com2_oval,
                (com2_oval[0], link_y),
                (col2_cx, link_y),
                (col2_cx, col2_top),
            ], 0.5)

        trunk_pts.append((slot_cx, trunk_y))

    # BMS cloud → trunk (vertical drop) and trunk horizontal bus across this page
    add_polyline_with_width(
        session, [(page_cx, bms_bottom_y), (page_cx, trunk_y)], 0.5,
    )
    if trunk_pts:
        first_x = min(p[0] for p in trunk_pts)
        last_x = max(p[0] for p in trunk_pts)
        first_x = min(first_x, page_cx)
        last_x = max(last_x, page_cx)
        # Single-PBC pages can collapse to first_x == last_x (zero-length
        # polyline → filtered out by add_polyline_with_width's epsilon).
        # Add a small hang on each side so the trunk reads as a trunk
        # rather than vanishing into the BMS-cloud drop.
        if last_x - first_x < 1.0:
            first_x -= 20.0
            last_x += 20.0
        add_polyline_with_width(
            session, [(first_x, trunk_y), (last_x, trunk_y)], 0.5,
        )


def generate_pbc_page(
    session: CadSession,
    project: dict,
    page_bounds: tuple[float, float, float, float],
    pbc_blocks_dir: Path,
    eol_dwg_path: Path | None = None,
    page_height: float | None = None,
    log_path: Path | None = None,
) -> int:
    """Render the PBC network drawing across one or more pages and return the
    number of pages used (0 if no PBCs exist anywhere in the project).

    PBCs lay out side-by-side, up to `_PBC_PER_PAGE` (7) per page. When more
    PBCs exist, they wrap onto additional PBC pages stacked downward at
    `page_height` intervals (matching the lab-page stacking).

    Layout per page:
      - BMS NETWORK ellipse near the top, with a horizontal trunk wire below.
      - Each PBC gets a horizontal slot; a NET label sits above it.
      - Under each PBC, two columns of valve sub-blocks (COM1 left, COM2 right),
        sorted SAV → GEX → FEV → AUX top-to-bottom, terminated by LON4.

    Wires are 0.5"-wide LWPOLYLINEs (much thinner than the lab-page MSTP rails).

    The caller should shift lab rooms down by the returned page count so PBC
    pages don't collide with lab pages.
    """
    pbc_body_path = pbc_blocks_dir / "pbc.dwg"
    if not pbc_body_path.is_file():
        # Print to stderr unconditionally — a missing PBC body block is a
        # real configuration problem and should not be invisible just
        # because the caller didn't pass a log_path.
        msg = f"PBC page skipped: missing {pbc_body_path}"
        print(f"WARNING: {msg}", file=sys.stderr)
        if log_path is not None:
            try:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(f"\n{msg}\n")
            except Exception:  # noqa: BLE001
                # Log-write failure — already printed to stderr.
                pass
        return 0

    rooms = project.get("rooms") or []
    paired: list[tuple[dict, dict]] = []
    for room in rooms:
        for pbc in room.get("pbcs", []) or []:
            paired.append((room, pbc))
    if not paired:
        return 0

    notes: list[str] = []
    x_min, x_max, y_min, y_max = page_bounds
    if page_height is None:
        page_height = y_max - y_min

    n_pages = (len(paired) + _PBC_PER_PAGE - 1) // _PBC_PER_PAGE

    for p in range(n_pages):
        y_offset = -p * float(page_height)
        page_y_min = y_min + y_offset
        page_y_max = y_max + y_offset
        slice_lo = p * _PBC_PER_PAGE
        slice_hi = min(slice_lo + _PBC_PER_PAGE, len(paired))
        _render_pbc_page(
            session,
            page_pbcs=paired[slice_lo:slice_hi],
            page_bounds=(x_min, x_max, page_y_min, page_y_max),
            starting_net_index=slice_lo,
            pbc_body_path=pbc_body_path,
            pbc_blocks_dir=pbc_blocks_dir,
            eol_dwg_path=eol_dwg_path,
            notes=notes,
        )

    if log_path is not None:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"\n--- PBC pages ({len(paired)} PBC"
                    f"{'s' if len(paired) != 1 else ''} across {n_pages} page"
                    f"{'s' if n_pages != 1 else ''}) ---\n"
                    + ("\n".join(notes) + "\n" if notes else "")
                )
        except Exception:  # noqa: BLE001
            pass
    return n_pages
