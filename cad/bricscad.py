"""BricsCAD COM driver.

Drives BricsCAD via its AutoCAD-compatible COM API. ProgID is
`BricscadApp.AcadApplication`. Falls back to `AutoCAD.Application` so the same
code works against AutoCAD if needed.

Each block insertion is done via `InsertBlock(insertionPoint, blockName, xs, ys, zs, rot)`.
We pass the absolute `.dwg` path as the block name — BricsCAD treats that as
"insert a reference to this external drawing as a block in the current drawing,"
which is exactly what we want for a library of standalone DWG block files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pythoncom  # type: ignore
import win32com.client  # type: ignore

from .layout import LayoutSpec, Placement


PROG_IDS = ("BricscadApp.AcadApplication", "AutoCAD.Application")

# Default sink for swallowed-exception notes when no caller-supplied notes
# list is in scope. Most generation entry-points truncate this file at the
# start of the run, so accumulated swallowed-exception messages from prior
# runs don't leak in.
_DEFAULT_LOG = Path(__file__).resolve().parent.parent / "jobs" / "last_generation.log"


def _log_swallowed(
    context: str,
    exc: BaseException,
    notes: "list[str] | None" = None,
) -> None:
    """Record a swallowed exception so it doesn't disappear silently.

    Many functions in this module use `try/except Exception: pass` for
    best-effort COM ops (attribute writes that may fail on a locked block,
    GetBoundingBox on a degenerate entity, etc). When a generation produces
    wrong output, knowing which of those quiet failures fired is invaluable.

    If a caller-local `notes` list is provided, append there (the function's
    existing per-section log dump will pick it up). Otherwise write a single
    line to last_generation.log directly. Failure of the logging itself is
    silent — there's nowhere safer to put it.
    """
    msg = f"  [swallowed] {context}: {type(exc).__name__}: {exc}"
    if notes is not None:
        notes.append(msg)
        return
    try:
        with _DEFAULT_LOG.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:  # noqa: BLE001
        pass


class CadError(RuntimeError):
    pass


def _variant_point(x: float, y: float, z: float = 0.0):
    """Wrap an XYZ point as a VARIANT array of doubles, as COM expects."""
    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8, (x, y, z)
    )


@dataclass
class CadSession:
    app: object
    doc: object
    model_space: object


def connect(visible: bool = True) -> CadSession:
    """Connect to BricsCAD (preferred) or AutoCAD.

    Tries each ProgID in order; falls through to the next ONLY if Dispatch
    itself fails (CAD app not installed / COM not registered). Once Dispatch
    succeeds we commit to that app — if accessing the active document fails
    we open a new empty one rather than silently switching to a different
    CAD app, which would change file format and behavior under the user.
    """
    last_err: Exception | None = None
    for prog_id in PROG_IDS:
        # Phase 1: try to bind to this CAD app via COM. If Dispatch fails,
        # the app isn't installed or registered — try the next ProgID.
        try:
            app = win32com.client.Dispatch(prog_id)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue

        # Phase 2: we have a live app handle. Stick with it. A missing
        # ActiveDocument just means the user has BricsCAD/AutoCAD running
        # with no drawing open — proactively create one instead of falling
        # through to the next CAD app (which would silently swap, e.g.,
        # BricsCAD for AutoCAD on a system with both installed).
        try:
            app.Visible = visible
            try:
                doc = app.ActiveDocument
            except Exception:  # noqa: BLE001
                doc = app.Documents.Add()
            return CadSession(app=app, doc=doc, model_space=doc.ModelSpace)
        except Exception as e:  # noqa: BLE001
            raise CadError(
                f"Connected to {prog_id} via COM but couldn't open an "
                f"active document: {e}"
            ) from e

    raise CadError(
        f"Could not connect to BricsCAD or AutoCAD via COM. "
        f"Is one of them installed? Last error: {last_err}"
    )


def new_drawing(session: CadSession, template_dwg: Path | None) -> CadSession:
    """Open a new drawing, optionally based on a template DWG."""
    if template_dwg and template_dwg.is_file():
        doc = session.app.Documents.Add(str(template_dwg))
    else:
        doc = session.app.Documents.Add()
    return CadSession(app=session.app, doc=doc, model_space=doc.ModelSpace)


def cleanup_after_failure(
    session: "CadSession | None",
    log_path: "Path | None" = None,
    error: "Exception | None" = None,
) -> None:
    """Best-effort restore of BricsCAD process state after a generation
    exception. Each step is independent: failures here are swallowed so
    the original error in generate() can still propagate cleanly.

    Specifically restores:
      - app.Visible = True (so the user can see what state the doc is in)
      - FILEDIA = 1 (so file dialogs work again)
      - exits any active model-space viewport back to paper space

    Does NOT save or close the partial drawing — the user may want to
    inspect what was placed before the failure. Appends a note to the
    generation log so post-mortem debugging knows where things went.
    """
    notes: list[str] = []
    if error is not None:
        notes.append(f"FAILURE: {type(error).__name__}: {error}")
    if session is None:
        notes.append("  no session to clean up")
    else:
        app = None
        doc = None
        try:
            app = session.app
        except Exception:  # noqa: BLE001
            pass
        try:
            doc = session.doc
        except Exception:  # noqa: BLE001
            pass

        # Restore app visibility — most important: a mid-burst crash that
        # bypassed replicate_paper_space_layouts' own finally would leave
        # BricsCAD invisible and the user thinks it died.
        try:
            if app is not None:
                app.Visible = True
                notes.append("  visibility restored")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"  visibility restore failed: {exc}")

        # Restore FILEDIA so file dialogs work again
        try:
            if doc is not None:
                doc.SetVariable("FILEDIA", 1)
                notes.append("  FILEDIA = 1")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"  FILEDIA restore failed: {exc}")

        # Exit MSpace if we ended inside a viewport
        try:
            if doc is not None:
                doc.MSpace = False
        except Exception:  # noqa: BLE001
            pass

    if log_path is not None and notes:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write("\n--- cleanup_after_failure ---\n" + "\n".join(notes) + "\n")
        except Exception:  # noqa: BLE001
            pass


def insert_block(
    session: CadSession,
    dwg_path: Path,
    x: float,
    y: float,
    scale: float = 1.0,
    rotation_rad: float = 0.0,
):
    if not dwg_path.is_file():
        raise CadError(f"Block DWG not found: {dwg_path}")
    pt = _variant_point(x, y)
    # Note: BricsCAD/AutoCAD COM accepts a full path here for "insert external DWG as block".
    return session.model_space.InsertBlock(
        pt, str(dwg_path), scale, scale, scale, rotation_rad
    )


def _bbox(ref) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return (min_xyz, max_xyz) of the block reference's bounding box.

    BricsCAD's COM API mirrors AutoCAD's: GetBoundingBox returns the two
    corners as 3-element double arrays.
    """
    result = ref.GetBoundingBox()
    if not (isinstance(result, tuple) and len(result) == 2):
        raise CadError(f"Unexpected GetBoundingBox return: {result!r}")
    minp, maxp = result
    return (tuple(minp), tuple(maxp))


def insert_block_at_grid_cell(
    session: CadSession,
    dwg_path: Path,
    target_x: float,
    target_y: float,
    scale: float = 1.0,
    rotation_rad: float = 0.0,
):
    """Insert a block, then shift it so its bounding-box bottom-left lands at
    (target_x, target_y). This works regardless of where the block's geometry
    sits relative to the source DWG's (0,0) — useful when the block DWGs
    weren't authored with `BASE` set to the geometry's bottom-left.
    """
    ref = insert_block(session, dwg_path, 0.0, 0.0, scale, rotation_rad)
    minp, _ = _bbox(ref)
    dx = target_x - minp[0]
    dy = target_y - minp[1]
    if dx != 0.0 or dy != 0.0:
        from_pt = _variant_point(0.0, 0.0)
        to_pt = _variant_point(dx, dy)
        ref.Move(from_pt, to_pt)
    return ref


def insert_with_dynamic_layout(
    session: CadSession,
    placements: list[Placement],
    layout: LayoutSpec,
    log_path: Path | None = None,
) -> tuple[list, int]:
    """Insert placements with serpentine flow across multi-page templates.

    Returns (refs, max_local_page) where `max_local_page` is the highest
    LOCAL page index used (0 if everything fit on one page; 1 if it spilled
    onto a second page; etc.). Callers shift subsequent rooms by this offset
    so multi-page rooms don't trample each other.

    Walks placements in `layout.row_order` (default SAV → GEX → FEV → AUX) as a
    single continuous chain. Within each page, rows alternate direction:
      page row 0: L→R from anchor_x
      page row 1: R→L from anchor_x + max_row_width
      page row 2: L→R again — and so on
    Once `rows_per_page` rows are filled, the chain jumps down by `page_height`
    to the next template page and direction resets to L→R.

    Each placement records its row direction in `is_reversed`; wire-drawing
    swaps OUT/IN endpoint roles for reversed blocks so the comm bus reads
    continuously.
    """
    by_cat: dict[str, list[Placement]] = {}
    for p in placements:
        by_cat.setdefault(p.category, []).append(p)

    ordered: list[Placement] = []
    for cat in layout.row_order:
        ordered.extend(by_cat.get(cat, []))

    refs: list = []
    log_lines: list[str] = []

    direction = +1                                  # +1 = L→R, -1 = R→L
    cursor_x = layout.anchor_x                      # leading edge of next block
    cursor_y = layout.anchor_y
    max_h_in_row = 0.0
    page_idx = 0
    row_in_page = 0
    row_right_limit = layout.anchor_x + layout.max_row_width

    for i, p in enumerate(ordered):
        ref = insert_block(session, Path(p.dwg_path), 0.0, 0.0)
        try:
            minp, maxp = _bbox(ref)
            w = maxp[0] - minp[0]
            h = maxp[1] - minp[1]
        except Exception as exc:  # noqa: BLE001
            log_lines.append(f"{p.category}  {p.variant_id}  bbox-read-failed: {exc}")
            refs.append(ref)
            continue

        # Compute target X for current direction
        if direction == +1:
            target_x = cursor_x
            overflow = (target_x + w > row_right_limit)
        else:
            target_x = cursor_x - w
            overflow = (target_x < layout.anchor_x)

        if i > 0 and overflow:
            row_in_page += 1
            if row_in_page >= layout.rows_per_page:
                # Jump to next page — reset direction to L→R, jump down a page
                page_idx += 1
                row_in_page = 0
                direction = +1
                cursor_y = layout.anchor_y - page_idx * layout.page_height
                target_x = layout.anchor_x
                if page_idx >= layout.page_count:
                    log_lines.append(
                        f"  WARN page-overflow: needed page {page_idx + 1} but "
                        f"page_count={layout.page_count}; placement continues "
                        f"on a virtual page below the template."
                    )
            else:
                # Wrap to next row on same page, reverse direction
                cursor_y -= max_h_in_row + layout.v_gap
                direction *= -1
                if direction == +1:
                    target_x = layout.anchor_x
                else:
                    target_x = row_right_limit - w
            max_h_in_row = 0.0

        # Per-variant Y nudge for visual alignment (load elements like FUME
        # HOOD / CAGE WASH may sit at different internal heights). Positive
        # offset shifts the block UP relative to the row baseline.
        align_offsets = getattr(layout, "_align_offsets", {}) or {}
        y_nudge = float(align_offsets.get(p.variant_id, 0.0))
        target_y = cursor_y + y_nudge

        # Move parked block so its bbox bottom-left lands at (target_x, target_y)
        dx = target_x - minp[0]
        dy = target_y - minp[1]
        if dx != 0.0 or dy != 0.0:
            ref.Move(_variant_point(0.0, 0.0), _variant_point(dx, dy))

        p.x, p.y = target_x, target_y
        p.width, p.height = w, h
        p.is_reversed = (direction == -1)
        p.page_idx = page_idx
        p.row_idx = row_in_page

        # Advance cursor for next block
        if direction == +1:
            cursor_x = target_x + w + layout.h_gap
        else:
            cursor_x = target_x - layout.h_gap
        if h > max_h_in_row:
            max_h_in_row = h

        log_lines.append(
            f"{p.category}  {p.variant_id:24s}  "
            f"placed at ({target_x:8.2f},{target_y:8.2f})  "
            f"size={w:7.2f}x{h:7.2f}  "
            f"{'<-' if direction == -1 else '->'}  "
            f"page={page_idx + 1}"
            + (f"  nudge={y_nudge:+.1f}" if y_nudge else "")
        )
        refs.append(ref)

    # Bounds check vs the page rectangle, if provided in mstp_cfg or page cfg.
    page_cfg = getattr(layout, "_page_bounds", None)
    if page_cfg is not None:
        x_min, x_max, y_min, y_max = page_cfg
        for p in placements:
            if p.width <= 0:
                continue
            right = p.x + p.width
            top = p.y + p.height
            issues = []
            if p.x < x_min: issues.append(f"left={p.x:.1f}<{x_min}")
            if right > x_max: issues.append(f"right={right:.1f}>{x_max}")
            if p.y < y_min: issues.append(f"bottom={p.y:.1f}<{y_min}")
            if top > y_max: issues.append(f"top={top:.1f}>{y_max}")
            if issues:
                log_lines.append(
                    f"  WARN out-of-page  {p.category}  {p.variant_id}: "
                    + ", ".join(issues)
                )

    max_local_page = max((p.page_idx for p in placements), default=0)

    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"\n--- room layout (anchor_y={layout.anchor_y:.1f}, "
                    f"local pages used: {max_local_page + 1}) ---\n"
                    + "\n".join(log_lines) + "\n"
                )
        except Exception:  # noqa: BLE001
            pass
    return refs, max_local_page


def save_as(session: CadSession, dwg_path: Path):
    dwg_path.parent.mkdir(parents=True, exist_ok=True)
    session.doc.SaveAs(str(dwg_path))


def add_polyline_with_width(
    session: CadSession,
    points: list[tuple[float, float]],
    width: float,
):
    """Add a 2D LWPOLYLINE through `points` with constant width.

    Consecutive duplicate (or near-duplicate) points are filtered out so the
    resulting polyline has no zero-length segments, which BricsCAD can render
    as visible gaps at vertex caps."""
    cleaned: list[tuple[float, float]] = []
    for p in points:
        if cleaned and abs(p[0] - cleaned[-1][0]) < 0.01 and abs(p[1] - cleaned[-1][1]) < 0.01:
            continue
        cleaned.append((float(p[0]), float(p[1])))
    if len(cleaned) < 2:
        return None  # not enough points to make a polyline
    coords: list[float] = []
    for x, y in cleaned:
        coords.append(x)
        coords.append(y)
    coord_var = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8, coords
    )
    pl = session.model_space.AddLightWeightPolyline(coord_var)
    if width and width > 0:
        try:
            pl.ConstantWidth = float(width)
        except Exception:  # noqa: BLE001
            pass
    return pl


def draw_mstp_wires(
    session: CadSession,
    placements: list[Placement],
    mstp_cfg: dict,
    layout: LayoutSpec | None = None,
    log_path: Path | None = None,
) -> int:
    """Connect adjacent same-row placements with an MSTP comm wire.

    Each block variant supplies its own port offsets via mstp_cfg["ports"]:
        ports[variant_id] = { "in_offset": [x, y], "out_offset": [x, y] }
    where x, y are offsets from the block's bbox bottom-left.

    For an A→B pair, draws a polyline from A's OUT port to B's IN port. If
    either port is missing from config, skips that pair and logs a TODO.
    Pairs across a row wrap (different y) are also skipped for now.

    Returns the number of wires drawn. Appends notes to log_path if provided.
    """
    if not mstp_cfg.get("enabled", True):
        return 0
    if len(placements) < 2:
        return 0

    ports: dict = mstp_cfg.get("ports", {})
    width = float(mstp_cfg.get("wire_width", 0.0))

    # Small overlap that pulls each wire endpoint a few inches INTO its block,
    # so the new wire visually merges with the existing rail polyline even if
    # the rail's vertex coords drift by a fraction of an inch (post-straighten
    # snap residue, etc). 2" is enough to mask typical sub-inch drift without
    # bleeding visibly into other interior block content.
    SAFETY_OVERLAP = 2.0

    def _outgoing_world(p: Placement, p_ports: dict) -> tuple[float, float] | None:
        """Outgoing-wire endpoint for placement `p`, shifted inward by SAFETY_OVERLAP.

        For non-reversed (L→R) rows the outgoing side is OUT (right); for
        reversed (R→L) rows we use IN as the outgoing side (left-side of block).
        Shift INWARD = toward the block interior on the appropriate side.
        """
        key = "in_offset" if p.is_reversed else "out_offset"
        off = p_ports.get(key)
        if not off:
            return None
        x = p.x + float(off[0])
        y = p.y + float(off[1])
        # Outgoing on LEFT side of block (reversed) → inward = +x
        # Outgoing on RIGHT side of block (non-reversed) → inward = -x
        x += SAFETY_OVERLAP if p.is_reversed else -SAFETY_OVERLAP
        return (x, y)

    def _incoming_world(p: Placement, p_ports: dict) -> tuple[float, float] | None:
        """Incoming-wire endpoint for placement `p`, shifted inward by SAFETY_OVERLAP."""
        key = "out_offset" if p.is_reversed else "in_offset"
        off = p_ports.get(key)
        if not off:
            return None
        x = p.x + float(off[0])
        y = p.y + float(off[1])
        # Incoming on LEFT side (non-reversed) → inward = +x
        # Incoming on RIGHT side (reversed) → inward = -x
        x += -SAFETY_OVERLAP if p.is_reversed else SAFETY_OVERLAP
        return (x, y)

    notes: list[str] = []
    drawn = 0
    for prev, cur in zip(placements, placements[1:]):
        prev_ports = ports.get(prev.variant_id, {})
        cur_ports = ports.get(cur.variant_id, {})
        out_world = _outgoing_world(prev, prev_ports)
        in_world = _incoming_world(cur, cur_ports)

        missing: list[str] = []
        if out_world is None:
            outgoing_key = "in_offset" if prev.is_reversed else "out_offset"
            missing.append(f"{prev.variant_id}.{outgoing_key}")
        if in_world is None:
            incoming_key = "out_offset" if cur.is_reversed else "in_offset"
            missing.append(f"{cur.variant_id}.{incoming_key}")
        if missing:
            notes.append(
                f"MSTP skip ({prev.variant_id} -> {cur.variant_id}): "
                f"missing port(s) — {', '.join(missing)}"
            )
            continue

        # Cross-page wire: route through the page's left margin so the wire
        # wraps around the title-block area instead of crossing through it.
        if prev.page_idx != cur.page_idx:
            margin_x = 80.0  # default fallback
            if layout is not None:
                page_bounds = getattr(layout, "_page_bounds", None)
                if page_bounds:
                    margin_x = float(page_bounds[0]) + 15.0  # 15" inside left page edge
                else:
                    margin_x = layout.anchor_x - 20.0
            pts = [
                out_world,
                (margin_x, out_world[1]),
                (margin_x, in_world[1]),
                in_world,
            ]
            add_polyline_with_width(session, pts, width)
            notes.append(
                f"MSTP cross-page wire: {prev.variant_id} (pg{prev.page_idx + 1}) "
                f"-> {cur.variant_id} (pg{cur.page_idx + 1}) via left margin "
                f"x={margin_x:.1f}"
            )
            drawn += 1
            continue

        # Compare row identity, not post-nudge Y. align_offsets nudges Y by
        # variant_id (potentially tens of inches), so two valves of different
        # categories on the same logical row would fail an abs(prev.y-cur.y)<0.5
        # check and route their wire through the wrong margin.
        same_row = (prev.page_idx == cur.page_idx) and (prev.row_idx == cur.row_idx)

        # The bbox edge at which the wire exits/enters each block (the side
        # the chain is flowing toward).
        prev_edge_x = prev.x if prev.is_reversed else (prev.x + prev.width)
        cur_edge_x = (cur.x + cur.width) if cur.is_reversed else cur.x

        # Compute bridge_x — a column of empty space outside both blocks
        # where the vertical wire segment lives.
        if same_row:
            # Inter-block gap — midpoint between adjacent block edges.
            # Holds for both L→R and R→L rows: prev_edge_x and cur_edge_x are
            # the *facing* edges in either direction, so the midpoint is the
            # column of empty space between them regardless of row direction.
            bridge_x = (prev_edge_x + cur_edge_x) / 2.0
        else:
            # Row wrap (within one page). Chain ends on the right (L→R end)
            # or left (R→L end). Bridge to the corresponding outer margin.
            if prev.is_reversed:
                bridge_x = min(prev.x, cur.x) - 30.0
            else:
                bridge_x = max(prev.x + prev.width, cur.x + cur.width) + 30.0

        # Build the polyline. For same Y on same row we can run straight;
        # otherwise route via block-edge → bridge → block-edge so the wire
        # only adds geometry OUTSIDE the bbox of either block (the in-block
        # legs at rail Y just overlap the existing rail polyline).
        if same_row and abs(out_world[1] - in_world[1]) < 0.5:
            pts = [out_world, in_world]
        else:
            pts = [
                out_world,
                (prev_edge_x, out_world[1]),
                (bridge_x, out_world[1]),
                (bridge_x, in_world[1]),
                (cur_edge_x, in_world[1]),
                in_world,
            ]
        add_polyline_with_width(session, pts, width)
        notes.append(
            f"MSTP drew {prev.variant_id}.out{tuple(round(v, 2) for v in out_world)} "
            f"-> {cur.variant_id}.in{tuple(round(v, 2) for v in in_world)} "
            f"({len(pts)} verts, {'row-wrap' if not same_row else 'same-row'}, "
            f"bridge_x={bridge_x:.1f})"
        )
        drawn += 1

    if log_path is not None and notes:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write("\n--- MSTP ---\n" + "\n".join(notes) + "\n")
        except Exception:  # noqa: BLE001
            pass
    return drawn


def update_room_text(
    session: CadSession,
    room_names: list[str],
    log_path: Path | None = None,
) -> int:
    """Replace 'ROOM: LAB XX' (or any text starting with 'ROOM:') in model space
    with 'ROOM: <room_name>'. Multiple matches are sorted by Y descending (top
    of drawing first) and assigned to room_names[0], room_names[1], etc.
    Returns the number of texts replaced."""
    candidates: list[tuple[float, object]] = []
    for ent in session.model_space:
        try:
            if ent.ObjectName != "AcDbText":
                continue
            text = str(ent.TextString)
        except Exception:  # noqa: BLE001
            continue
        # Match "ROOM:" only when followed by space/colon-space — avoids
        # false-positive matches on user-added text like "Room Info:" that
        # incidentally starts with the same 5 chars.
        if not re.match(r"^\s*ROOM:\s", text, re.IGNORECASE):
            continue
        try:
            ip = ent.InsertionPoint
            candidates.append((float(ip[1]), ent))
        except Exception:  # noqa: BLE001
            continue

    # Top of drawing first → page 1 first
    candidates.sort(key=lambda c: -c[0])
    replaced = 0
    notes: list[str] = []
    for i, (y, ent) in enumerate(candidates):
        if i >= len(room_names):
            break
        new_text = f"ROOM: {room_names[i]}"
        try:
            ent.TextString = new_text
            replaced += 1
            notes.append(f"  ROOM text @ y={y:.1f} -> {new_text!r}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"  ROOM text @ y={y:.1f} write failed: {exc}")

    if log_path is not None and notes:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write("\n--- ROOM names ---\n" + "\n".join(notes) + "\n")
        except Exception:  # noqa: BLE001
            pass
    return replaced


def update_title_block(
    session: CadSession,
    project: dict,
    log_path: Path | None = None,
) -> int:
    """Fill the title-block attributes in every paper-space block reference.

    Project-level attributes (same on every sheet):
        JOBNAMETOP    ← job_name
        JOBNAMEBOTTOM ← job_name_bottom
        TITLETOP      ← title_top
        TITLEBOTTOM   ← title_bottom
        OFFICE        ← office
        REVISED       ← revision
        DRAFTER       ← technician
        DATE          ← date
        JOBNUM        ← job_number
    Per-sheet attributes (TITLE, DRAWNAME, PAGE) are intentionally NOT
    written here — those vary per page and are filled manually by the user.

    Returns the number of attributes written across all paper-space layouts.
    """
    field_map = {
        "JOBNAMETOP":    str(project.get("job_name", "") or ""),
        "JOBNAMEBOTTOM": str(project.get("job_name_bottom", "") or ""),
        "TITLETOP":      str(project.get("title_top", "") or ""),
        "TITLEBOTTOM":   str(project.get("title_bottom", "") or ""),
        "OFFICE":        str(project.get("office", "") or ""),
        "REVISED":       str(project.get("revision", "") or ""),
        "DRAFTER":       str(project.get("technician", "") or ""),
        "DATE":          str(project.get("date", "") or ""),
        "JOBNUM":        str(project.get("job_number", "") or ""),
    }
    written = 0
    notes: list[str] = []
    try:
        doc = session.doc
        for layout in doc.Layouts:
            try:
                lname = str(layout.Name)
            except Exception:  # noqa: BLE001
                continue
            if lname.lower() == "model":
                continue
            try:
                block = layout.Block
            except Exception:  # noqa: BLE001
                continue
            for ent in block:
                try:
                    if ent.ObjectName != "AcDbBlockReference":
                        continue
                    attrs = ent.GetAttributes()
                except Exception:  # noqa: BLE001
                    continue
                if not attrs:
                    continue
                for a in attrs:
                    try:
                        tag = str(a.TagString).upper()
                    except Exception:  # noqa: BLE001
                        continue
                    if tag in field_map:
                        new_val = field_map[tag]
                        if not new_val:
                            continue
                        try:
                            a.TextString = new_val
                            written += 1
                            notes.append(f"  [{lname}] {tag} = {new_val!r}")
                        except Exception as exc:  # noqa: BLE001
                            notes.append(f"  [{lname}] {tag} write failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"  iter error: {exc}")

    if log_path is not None and notes:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write("\n--- title block ---\n" + "\n".join(notes) + "\n")
        except Exception:  # noqa: BLE001
            pass
    return written


def add_tag_labels(
    session: CadSession,
    placements: list[Placement],
    height: float = 8.0,
    gap_above: float = 8.0,
) -> int:
    """Add a TEXT entity above each placement showing its tag string.

    Position: centered horizontally on the block bbox, `gap_above` inches
    above the block's top edge. `height` is the text height in inches.
    Returns the number of labels drawn.
    """
    drawn = 0
    for p in placements:
        if not p.tag:
            continue
        cx = p.x + p.width / 2.0
        ty = p.y + p.height + gap_above
        # rough horizontal center — TextString width ≈ len * 0.6 * height
        text_x = cx - len(p.tag) * height * 0.3
        try:
            session.model_space.AddText(p.tag, _variant_point(text_x, ty), height)
            drawn += 1
        except Exception:  # noqa: BLE001
            pass
    return drawn


# PBC network page generation lives in cad/pbc.py — it composes over the
# block-insert / wire-draw / bbox helpers in this module. Imported lazily by
# app.py:generate to keep COM out of the GUI startup path.


def replicate_paper_space_layouts(
    session: CadSession,
    page_bounds: tuple[float, float, float, float],
    page_height: float,
    n_pages: int,
    log_path: Path | None = None,
) -> int:
    """Replicate the existing non-Model paper-space layout, one new layout
    per additional page (page 2 onward). Each new layout's viewport(s) get
    their ViewCenter shifted to the corresponding page's model-space
    rectangle, so each sheet shows the right page when printed/exported.

    `update_title_block` runs over all layouts at the end of generation, so
    the new layouts inherit the project's title-block field values
    automatically — this function only needs to clone + shift the viewport.

    Returns the number of layouts added (0 if n_pages <= 1 or source not found).
    """
    if n_pages <= 1:
        return 0

    doc = session.doc

    # Find the existing source layout (first non-"Model" entry)
    source_layout = None
    for layout in doc.Layouts:
        try:
            if str(layout.Name).lower() == "model":
                continue
        except Exception:  # noqa: BLE001
            continue
        source_layout = layout
        break

    if source_layout is None:
        if log_path is not None:
            try:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(
                        "\nreplicate_paper_space_layouts: no non-Model layout "
                        "found in template — skipping\n"
                    )
            except Exception:  # noqa: BLE001
                pass
        return 0

    source_name = str(source_layout.Name)
    x_min, x_max, y_min, y_max = page_bounds
    target_cx = (x_min + x_max) / 2.0

    # Generate new sheet names by incrementing the trailing integer if any
    # ("7.301" → "7.302", "7.303" …). Falls back to "<source>_pN" otherwise.
    m = re.match(r"^(.*?)(\d+)$", source_name)
    if m:
        name_prefix, num_str = m.groups()
        base_num = int(num_str)
        digits = len(num_str)

        def name_for_page(p_idx: int) -> str:
            return f"{name_prefix}{base_num + p_idx:0{digits}d}"
    else:
        def name_for_page(p_idx: int) -> str:
            return f"{source_name}_p{p_idx + 1}"

    notes = [
        f"replicate_paper_space_layouts: source='{source_name}', n_pages={n_pages}"
    ]

    # Snapshot existing layout names ONCE (avoid O(N²) iteration).
    existing_names: set[str] = set()
    try:
        for layout in doc.Layouts:
            try:
                existing_names.add(str(layout.Name))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass

    # Speed knobs — hide app + suppress dialogs during the SendCommand burst.
    # Captured here, then EVERYTHING below runs inside a try/finally so any
    # exception still restores the user-visible state (visible app, FILEDIA
    # on, viewports re-locked, model space exited, original layout active).
    # Without this, a mid-burst crash leaves BricsCAD invisible / dialogs
    # suppressed / viewports pannable, and the user thinks the app is broken.
    app = None
    orig_visible: object = None
    orig_filedia: object = None
    prev_active = None
    unlocked_viewports: list = []  # populated below; relocked in finally
    added = 0
    view_shift_count = 0
    new_names: list[str] = []

    try:
        try:
            app = doc.Application
            orig_visible = app.Visible
            app.Visible = False
        except Exception:  # noqa: BLE001
            pass
        try:
            orig_filedia = doc.GetVariable("FILEDIA")
            doc.SetVariable("FILEDIA", 0)
        except Exception:  # noqa: BLE001
            pass
        try:
            prev_active = doc.ActiveLayout
        except Exception:  # noqa: BLE001
            pass

        added, view_shift_count, new_names = _replicate_layouts_inner(
            doc, source_name, source_layout, page_bounds, page_height,
            n_pages, name_for_page, existing_names, notes, unlocked_viewports,
        )

    finally:
        # Relock every viewport we unlocked. Cloned viewports start
        # DisplayLocked=True; we toggle them off to ZOOM, then back on so
        # the user can't accidentally pan a viewport off its assigned page.
        for ent in unlocked_viewports:
            try:
                ent.DisplayLocked = True
            except Exception:  # noqa: BLE001
                pass
        # Exit model space if we ended inside a viewport
        try:
            doc.MSpace = False
        except Exception:  # noqa: BLE001
            pass
        # Restore the previously-active layout
        if prev_active is not None:
            try:
                doc.ActiveLayout = prev_active
            except Exception:  # noqa: BLE001
                pass
        # Restore FILEDIA so the user sees file dialogs again
        if orig_filedia is not None:
            try:
                doc.SetVariable("FILEDIA", orig_filedia)
            except Exception:  # noqa: BLE001
                pass
        # Restore app visibility — most important: without this, a crash
        # mid-burst leaves BricsCAD invisible and the user thinks it died.
        if app is not None and orig_visible is not None:
            try:
                app.Visible = bool(orig_visible)
            except Exception:  # noqa: BLE001
                pass

    notes.append(
        f"  view-shift completed for {view_shift_count}/{n_pages} layout(s)"
    )

    if log_path is not None:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    "\n--- replicate_paper_space_layouts ---\n"
                    + "\n".join(notes)
                    + f"\n  layouts added: {added}\n"
                )
        except Exception:  # noqa: BLE001
            pass
    return added


def _replicate_layouts_inner(
    doc,
    source_name: str,
    source_layout,
    page_bounds: tuple[float, float, float, float],
    page_height: float,
    n_pages: int,
    name_for_page,
    existing_names: set[str],
    notes: list[str],
    unlocked_viewports: list,
) -> tuple[int, int, list[str]]:
    """Inner body of replicate_paper_space_layouts — mutating section.

    Split out so the caller can wrap state mutations in try/finally without
    nesting the whole logic. Appends per-step messages to `notes` and tracks
    unlocked viewports in `unlocked_viewports` (caller relocks them all).

    Returns (layouts_added, view_shift_count, new_names_list).
    """
    # Use BricsCAD's built-in `LAYOUT _C source new` command via SendCommand.
    # This is the only path that produces a properly-initialised paper-space
    # clone (entities + working viewport) — direct COM `Layouts.Add +
    # CopyObjects + AddPViewport` is sabotaged by BricsCAD's layout-init not
    # firing for inactive layouts. Each new sheet ends up identical to source
    # (viewport shows page-1 of model space). The view-shift loop below
    # retargets each clone's viewport via ZOOM WINDOW with explicit corners
    # (post-D fix — ZOOM CENTER is ambiguous when called from a SendCommand
    # burst and zooms ~2x farther out than asked).
    cmd_parts: list[str] = []
    new_names: list[str] = []
    for p in range(1, n_pages):     # page 0 IS source; clone for pages 1..n_pages-1
        new_name = name_for_page(p)
        if new_name in existing_names:
            notes.append(f"  page {p + 1}: '{new_name}' already exists; skipping")
            continue
        cmd_parts.append(
            f'(command "_LAYOUT" "_C" "{source_name}" "{new_name}") '
        )
        new_names.append(new_name)

    notes.append(
        f"  sending {len(new_names)} LAYOUT _C command(s) "
        f"(~{sum(len(c) for c in cmd_parts)} chars)"
    )
    if cmd_parts:
        try:
            doc.SendCommand("".join(cmd_parts))
        except Exception as exc:  # noqa: BLE001
            notes.append(f"  SendCommand failed: {exc}")

    # Force the queued commands to flush. Reading a system variable forces a
    # synchronous COM round-trip which BricsCAD only services after pending
    # commands process. PumpWaitingMessages handles any leftover COM events.
    try:
        _ = doc.GetVariable("CDATE")
    except Exception:  # noqa: BLE001
        pass
    try:
        pythoncom.PumpWaitingMessages()
    except Exception:  # noqa: BLE001
        pass

    # Verify how many actually appeared
    after_names: set[str] = set()
    try:
        for layout in doc.Layouts:
            try:
                after_names.add(str(layout.Name))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    added = sum(1 for n in new_names if n in after_names)
    notes.append(f"  verified {added}/{len(new_names)} new layouts present")

    # Per-sheet viewport view-shift. Cloned viewports are DisplayLocked by
    # default — that's why every previous ZOOM CENTER attempt silently failed
    # (the lock makes the viewport reject view changes). Procedure per page:
    # 1) unlock the viewport, 2) activate the layout, 3) enter MSpace, 4)
    # ZOOM CENTER on the page's model-space center, 5) exit MSpace, 6) relock.
    x_min, x_max, y_min, y_max = page_bounds
    cx = (x_min + x_max) / 2.0
    # Build the full ordered list of layouts to view-shift. Use name_for_page
    # for ALL pages — that way pre-existing template layouts (e.g. 7.302..7.304
    # already in Background.dwg before any cloning) get view-shifted too. The
    # original `[source_name] + new_names` only covered the source plus newly-
    # cloned layouts, so any project where pages == template's existing layout
    # count would leave intermediate layouts retaining the page-1 view.
    page_layouts = [name_for_page(p) for p in range(n_pages)]

    view_shift_count = 0
    for p, layout_name in enumerate(page_layouts):
        cy = (y_min + y_max) / 2.0 - p * page_height
        try:
            layout = doc.Layouts.Item(layout_name)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"  view-shift {layout_name}: not found ({exc})")
            continue

        # Step 1: snapshot + unlock all viewports in this layout. Track
        # unlocked viewports in `unlocked_viewports` so the caller's finally
        # block relocks them even if a later step raises.
        for ent in layout.Block:
            try:
                if str(ent.ObjectName) != "AcDbViewport":
                    continue
            except Exception:  # noqa: BLE001
                continue
            try:
                ent.DisplayLocked = False
                unlocked_viewports.append(ent)
            except Exception:  # noqa: BLE001
                pass

        # Step 2: activate this layout
        try:
            doc.ActiveLayout = layout
        except Exception as exc:  # noqa: BLE001
            notes.append(f"  view-shift {layout_name}: ActiveLayout failed ({exc})")
            continue

        # Step 3: enter model space within the active viewport
        try:
            doc.MSpace = True
        except Exception:  # noqa: BLE001
            pass

        # Step 4: confirm we're inside a model viewport
        try:
            cvport = int(doc.GetVariable("CVPORT"))
        except Exception:  # noqa: BLE001
            cvport = 1

        # Step 5: ZOOM WINDOW (explicit corners) if we have a real model-
        # viewport context. ZOOM CENTER's height parameter has been observed
        # to mis-fit the viewport when a long SendCommand burst queues — the
        # viewport ends up showing ~2 pages instead of one. ZOOM WINDOW with
        # the page rectangle's lower-left and upper-right is unambiguous and
        # behaves consistently regardless of viewport aspect.
        if cvport != 1:
            try:
                page_x_min = cx - (x_max - x_min) / 2.0
                page_x_max = cx + (x_max - x_min) / 2.0
                page_y_min = cy - page_height / 2.0
                page_y_max = cy + page_height / 2.0
                doc.SendCommand(
                    f'(command "_ZOOM" "_W" '
                    f'(list {page_x_min:.4f} {page_y_min:.4f} 0.0) '
                    f'(list {page_x_max:.4f} {page_y_max:.4f} 0.0)) '
                )
                try:
                    _ = doc.GetVariable("CDATE")   # flush command queue
                except Exception:  # noqa: BLE001
                    pass
                try:
                    pythoncom.PumpWaitingMessages()
                except Exception:  # noqa: BLE001
                    pass
                view_shift_count += 1
            except Exception as exc:  # noqa: BLE001
                notes.append(f"  view-shift {layout_name}: ZOOM failed ({exc})")
        else:
            notes.append(
                f"  view-shift {layout_name}: still in paperspace "
                f"(CVPORT=1) after MSpace=True — skipping ZOOM"
            )

        # Step 6: back to paper space (per-iteration; caller's finally also
        # unsets MSpace if we exit the loop with it still True).
        try:
            doc.MSpace = False
        except Exception:  # noqa: BLE001
            pass

        # Note: viewports stay unlocked here. The caller's finally block
        # relocks all viewports in `unlocked_viewports` once we return,
        # so a mid-loop exception still results in locked viewports.

    return added, view_shift_count, new_names


def extend_template_pages(
    session: CadSession,
    page_bounds: tuple[float, float, float, float],
    page_height: float,
    from_page: int,
    to_page: int,
    log_path: Path | None = None,
) -> int:
    """Replicate page-1 model-space content to additional pages.

    For each page index p in [from_page, to_page), copies every entity that
    lies on page 1 (bbox center within page-1 y range) to a new entity at
    Y offset -p * page_height. Used when a project needs more pages than the
    template provides — adds borders + lab callouts for those extra pages.

    Uses `AcadDocument.CopyObjects(safearray)` which is the spec-recommended
    bulk-copy API — `AcadObject.Copy()` per-entity is unreliable in BricsCAD
    for some entity types (paper-space block refs, polylines with width).

    Returns the number of pages added.
    """
    if to_page <= from_page:
        return 0

    x_min, x_max, y_min, y_max = page_bounds

    # Notes list created early so the bbox-snapshot loop below can record
    # entities it had to skip (vs. earlier behavior of silent skip).
    notes: list[str] = [
        f"extend_template_pages: from_page={from_page} to_page={to_page} "
        f"page_height={page_height:.1f}",
    ]

    # Snapshot page-1 entities BEFORE we start mutating model space.
    page1_entities: list = []
    type_counts: dict[str, int] = {}
    for ent in session.model_space:
        try:
            obj_name = ent.ObjectName
            minp, maxp = ent.GetBoundingBox()
            mid_y = (float(minp[1]) + float(maxp[1])) / 2.0
        except Exception as exc:  # noqa: BLE001
            _log_swallowed(
                "extend_template_pages.snapshot-bbox-read", exc, notes=notes,
            )
            continue
        if y_min <= mid_y <= y_max:
            page1_entities.append(ent)
            type_counts[obj_name] = type_counts.get(obj_name, 0) + 1

    notes.append(f"  page-1 entities snapshotted: {len(page1_entities)}")
    for k, c in sorted(type_counts.items(), key=lambda kv: -kv[1]):
        notes.append(f"    {k}: {c}")

    if not page1_entities:
        notes.append("  no page-1 entities found — extension skipped")
        if log_path is not None:
            try:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(
                        "\n--- extend_template_pages ---\n"
                        + "\n".join(notes) + "\n"
                    )
            except Exception:  # noqa: BLE001
                pass
        return 0

    # Per-entity Copy + Move — bulk CopyObjects(safearray) errors out with
    # E_INVALIDARG in BricsCAD even with a properly-typed VARIANT array, so
    # we iterate. Each copy lands in the same owner (model space) per the
    # AutoCAD ActiveX spec; we then Move() it to the target page Y.
    added = 0
    for p in range(from_page, to_page):
        dy = -p * float(page_height)
        success = 0
        per_type_failures: dict[str, int] = {}
        for ent in page1_entities:
            try:
                obj_name = str(ent.ObjectName)
            except Exception:  # noqa: BLE001
                obj_name = "?"
            try:
                copy = ent.Copy()
            except Exception as exc:  # noqa: BLE001
                key = f"{obj_name}-copy({type(exc).__name__})"
                per_type_failures[key] = per_type_failures.get(key, 0) + 1
                continue
            # Some BricsCAD plugin layers return None from Copy() for unsupported
            # entity types instead of raising. Without this guard, copy.Move on
            # the next line would crash with AttributeError and be silently
            # swallowed by the per-type-failures bucket.
            if copy is None:
                key = f"{obj_name}-copy(None-returned)"
                per_type_failures[key] = per_type_failures.get(key, 0) + 1
                continue
            try:
                copy.Move(_variant_point(0.0, 0.0), _variant_point(0.0, dy))
                success += 1
            except Exception as exc:  # noqa: BLE001
                key = f"{obj_name}-move({type(exc).__name__})"
                per_type_failures[key] = per_type_failures.get(key, 0) + 1

        # Surface low-success pages prominently. < 50% means most page-1
        # entities didn't replicate to this page — extended pages will be
        # mostly blank and the user needs to know why.
        ratio = success / max(1, len(page1_entities))
        warn = " (LOW — replicated <50% of source page)" if ratio < 0.5 else ""
        notes.append(
            f"  page {p} (dy={dy:.1f}): success={success}/{len(page1_entities)}{warn}"
            + (f", failures={per_type_failures}" if per_type_failures else "")
        )
        if success > 0:
            added += 1

    # Force a regen so the newly-copied geometry shows in the active viewport.
    try:
        session.doc.Regen(1)   # acAllViewports
    except Exception as exc:  # noqa: BLE001
        notes.append(f"  Regen failed: {exc}")

    if log_path is not None:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    "\n--- extend_template_pages ---\n"
                    + "\n".join(notes)
                    + f"\n  pages added: {added}\n"
                )
        except Exception:  # noqa: BLE001
            pass
    return added


def insert_eol_marker(
    session: CadSession,
    placements: list[Placement],
    mstp_cfg: dict,
    eol_dwg_path: Path,
    log_path: Path | None = None,
) -> bool:
    """Insert the EOL resistor block at the OUT port of the last placement.

    The EOL block's bbox bottom-left snaps to the OUT world coord. Returns True
    if a block was inserted, False otherwise.
    """
    if not placements:
        return False
    if not eol_dwg_path.is_file():
        if log_path is not None:
            try:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(f"\nEOL skip: block file missing at {eol_dwg_path}\n")
            except Exception:  # noqa: BLE001
                pass
        return False

    last = placements[-1]
    ports = mstp_cfg.get("ports", {})
    last_ports = ports.get(last.variant_id, {})
    # Use OUT for non-reversed rows; for reversed (R→L) rows the outgoing
    # endpoint is IN. The EOL marker terminates the trunk at the chain end.
    outgoing_key = "in_offset" if last.is_reversed else "out_offset"
    outgoing = last_ports.get(outgoing_key)
    if not outgoing:
        if log_path is not None:
            try:
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(
                        f"\nEOL skip: no {outgoing_key} for last variant {last.variant_id}\n"
                    )
            except Exception:  # noqa: BLE001
                pass
        return False

    target_x = last.x + float(outgoing[0])
    target_y = last.y + float(outgoing[1])

    # Insert EOL at parking, then move so its bbox is CENTERED vertically on the
    # wire endpoint (so the wire passes through the EOL block's middle, not its
    # bottom). Horizontally, anchor the EOL's left edge to the wire endpoint
    # (or right edge if the chain is reversed — wire approaches from the right).
    ref = insert_block(session, eol_dwg_path, 0.0, 0.0)
    try:
        minp, maxp = _bbox(ref)
        eol_w = maxp[0] - minp[0]
        eol_h = maxp[1] - minp[1]
        if last.is_reversed:
            # Wire continues leftward; place EOL to the LEFT of the endpoint.
            new_min_x = target_x - eol_w
        else:
            new_min_x = target_x
        new_min_y = target_y - eol_h / 2.0
        dx = new_min_x - minp[0]
        dy = new_min_y - minp[1]
        if dx != 0.0 or dy != 0.0:
            ref.Move(_variant_point(0.0, 0.0), _variant_point(dx, dy))
    except Exception:  # noqa: BLE001
        pass

    if log_path is not None:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"\nEOL inserted at wire endpoint ({target_x:.2f}, {target_y:.2f}) "
                    f"(end of chain after {last.variant_id}, reversed={last.is_reversed})\n"
                )
        except Exception:  # noqa: BLE001
            pass
    return True
