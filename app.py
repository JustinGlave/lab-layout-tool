"""Lab Layout Tool — entry point.

Run from the project root:
    python app.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QApplication

from cad import blocks
from cad.layout import (
    flatten_job,
    layout_from_config,
)
from ui.style import apply_dark_theme
from ui.main_window import MainWindow, APP_NAME, ORG_NAME
from version import __version__

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "jobs" / "drawings"


def generate(project: dict) -> Path:
    """Build the drawing in BricsCAD and save it. Multi-room project schema:
    each room becomes its own page in the multi-page template.
    Returns the output path.
    """
    # Lazy-import so the GUI can launch even on machines without pywin32 yet.
    import copy
    from cad import bricscad

    cfg = blocks.load_config()
    layout = layout_from_config(cfg)
    page = cfg.get("page", {})
    if all(k in page for k in ("x_min", "x_max", "y_min", "y_max")):
        layout._page_bounds = (
            float(page["x_min"]), float(page["x_max"]),
            float(page["y_min"]), float(page["y_max"]),
        )
    layout._align_offsets = {
        k: float(v) for k, v in cfg.get("align_offsets", {}).items()
        if not k.startswith("_")
    }

    rooms = project.get("rooms") or []
    if not rooms:
        raise RuntimeError("Project has no rooms.")

    rooms_placements: list[list] = []
    for room in rooms:
        room_placements = flatten_job(room)
        rooms_placements.append(room_placements)
    if all(not rp for rp in rooms_placements):
        raise RuntimeError("Project has no valves in any room.")

    template = PROJECT_ROOT / cfg.get("template_dwg", "")
    template_path = template if template.is_file() else None

    session = bricscad.connect(visible=True)
    session = bricscad.new_drawing(session, template_path)
    log_path = PROJECT_ROOT / "jobs" / "last_generation.log"
    log_path.write_text("", encoding="utf-8")  # truncate from previous run

    # Place each room on its own page. Each room runs the existing layout
    # logic but with anchor_y offset down by (room_idx * page_height) and
    # page_count clamped to 1 (so rooms can't spill into the next page).
    mstp_cfg = cfg.get("mstp", {})
    eol_rel = mstp_cfg.get("eol_block")
    eol_path = (PROJECT_ROOT / eol_rel) if eol_rel else None

    # PBC network pages: generated FIRST so they land on page 1+. PBCs wrap
    # 7-per-page. The returned page count is how far to shift lab rooms down.
    # Returns 0 (no shift) when no room has any PBCs.
    page_bounds = getattr(layout, "_page_bounds", None) or (
        66.0, 1545.0, 33.0, 984.0
    )
    pbc_blocks_dir = PROJECT_ROOT / "blocks" / "misc"

    # Auto-extend the template if the project needs more pages than the
    # template provides. Runs BEFORE PBC generation (whose scrub mutates
    # page-1 content) so the page-1 snapshot copied to extra pages is intact.
    # Estimate per-room page count generously (~5 valves per page) so dense
    # rooms that span multiple pages still land on borders.
    def _estimate_room_pages(room: dict) -> int:
        valves = sum(
            len(room.get(cat, []) or [])
            for cat in ("SAV", "GEX", "FEV", "AUX")
        )
        # Empty rooms still reserve a page slot so the per-room → per-page
        # mapping in placement (room_idx → world page) stays consistent.
        if valves == 0:
            return 1
        return max(1, (valves + 4) // 5)

    n_pbcs_total = sum(len(r.get("pbcs", []) or []) for r in rooms)
    n_pbc_pages_needed = (n_pbcs_total + 6) // 7 if n_pbcs_total else 0
    estimated_room_pages = sum(_estimate_room_pages(r) for r in rooms)
    # +2 buffer so a room overshooting its estimate still lands on a border
    total_pages_needed = n_pbc_pages_needed + estimated_room_pages + 2
    template_pages = int(layout.page_count)
    if total_pages_needed > template_pages:
        bricscad.extend_template_pages(
            session, page_bounds, layout.page_height,
            from_page=template_pages,
            to_page=total_pages_needed,
            log_path=log_path,
        )

    pbc_pages_drawn = bricscad.generate_pbc_page(
        session, project, page_bounds,
        pbc_blocks_dir=pbc_blocks_dir,
        eol_dwg_path=eol_path,
        page_height=layout.page_height,
        log_path=log_path,
    )

    # Lab rendering — each room may span multiple pages. cumulative_extra
    # tracks how many EXTRA pages prior rooms used (beyond their first page),
    # so subsequent rooms shift down accordingly and don't overlap.
    cumulative_extra = 0
    room_page_counts: list[int] = []   # 1+ for non-empty rooms, 0 for empty
    for room_idx, room_placements in enumerate(rooms_placements):
        if not room_placements:
            room_page_counts.append(0)
            continue
        # World page index of this room's FIRST page
        room_first_page = room_idx + pbc_pages_drawn + cumulative_extra
        room_layout = copy.copy(layout)
        room_layout.anchor_y = layout.anchor_y - room_first_page * layout.page_height
        room_layout.page_count = 10   # generous — let the room span as needed

        _, max_local_page = bricscad.insert_with_dynamic_layout(
            session, room_placements, room_layout, log_path=log_path,
        )
        room_pages = max_local_page + 1
        room_page_counts.append(room_pages)

        # Convert each placement's local page_idx (0..max_local_page) to its
        # WORLD page index so wire routing/cross-page logic uses the right
        # page bounds.
        for p in room_placements:
            p.page_idx = room_first_page + p.page_idx

        # Wire the room's chain
        if len(room_placements) >= 2:
            bricscad.draw_mstp_wires(
                session, room_placements, mstp_cfg,
                layout=layout, log_path=log_path,
            )
        # EOL at the end of this room's chain
        if eol_path is not None:
            bricscad.insert_eol_marker(
                session, room_placements, mstp_cfg, eol_path, log_path=log_path,
            )
        # Tag labels above each block
        bricscad.add_tag_labels(session, room_placements)

        # Subsequent rooms shift down by the EXTRA pages this room used.
        cumulative_extra += max_local_page

    # Replicate the paper-space layout for each additional page so every
    # sheet (PBC pages + lab pages) is printable. update_title_block runs
    # over ALL layouts so attributes fill on each new sheet automatically.
    # Each room reserves at least one page slot (placement uses room_idx
    # for world page); empty rooms count toward the total even though no
    # valves are drawn on their page.
    total_pages_actual = pbc_pages_drawn + sum(
        max(np, 1) for np in room_page_counts
    )
    if total_pages_actual > 1:
        bricscad.replicate_paper_space_layouts(
            session, page_bounds, layout.page_height,
            n_pages=total_pages_actual,
            log_path=log_path,
        )

    # Project-level title block attributes (paper space) and per-page ROOM text.
    # Multi-page rooms occupy multiple ROOM: text slots; expand room_names so
    # each occupied page gets the same room name (LAB 101 spans 2 pages →
    # both pages read "ROOM: LAB 101").
    bricscad.update_title_block(session, project, log_path=log_path)
    room_names_expanded: list[str] = []
    for room_idx, n_pages in enumerate(room_page_counts):
        name = rooms[room_idx].get("name", "") or ""
        # Each room reserves at least one slot to keep room_idx → world-page
        # mapping consistent with the placement loop above. Empty rooms still
        # get their name written to the (otherwise blank) page's ROOM: text.
        slots = max(n_pages, 1)
        room_names_expanded.extend([name] * slots)
    bricscad.update_room_text(session, room_names_expanded, log_path=log_path)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = (project.get("job_name") or "untitled").replace(" ", "_")
    out_path = OUTPUT_DIR / f"{name}_{stamp}.dwg"
    bricscad.save_as(session, out_path)
    return out_path


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)

    apply_dark_theme(app)

    win = MainWindow(on_generate=generate, version=__version__)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
