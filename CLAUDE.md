# CLAUDE.md — Lab Layout Tool cold-start guide

Read this first when picking up the project in a new session. Sister docs: [README.md](README.md) for user-facing setup, [PLAN.md](PLAN.md) for phased buildout state and tomorrow's pickup.

## What this project is

A PySide6 desktop app that drives **BricsCAD via COM** to generate as-built lab valve drawings from form input. Multi-room project model: one project = many rooms = many DWG pages, with a shared title block and an optional first-page PBC network drawing.

Justin works at ATS Inc. on lab controls / Phoenix Controls valve as-builts. Email: `justing@atsinc.org`. He uses BricsCAD + VSCode. This is one of four ATS suite apps that share a dark-navy Phoenix Controls design system (Project Tracking Tool, Phoenix Checkout Tool, this, and one more).

## Where to start

```cmd
.venv\Scripts\activate
python app.py
```

Then **Tools → Test → Quick Test** generates a 3-lab CSCP drawing using `jobs/Quick_Test_Building.json`. **Full Test** generates a 10-lab thorough test using `jobs/thorough-test.json`. Both open BricsCAD and dump a generated DWG into `jobs/drawings/`.

If you need to inspect what the template / generated DWG actually contains:

```cmd
.venv\Scripts\python tools\inspect_template.py
.venv\Scripts\python tools\inspect_template.py jobs/drawings/<name>.dwg
```

Generation log: `jobs/last_generation.log` (truncated each run).

## Status snapshot

Phases 0–8 complete. End-to-end working on the thorough-test (10 labs + 10 PBCs across 2 PBC pages → 12 model-space pages, paper-space sheets `7.301`–`7.31N`, each viewing its OWN page). See `PLAN.md`'s "Stable checkpoint" for the full list of what shipped, including:

- PBC network page generation (BMS NETWORK ellipse + NET branches + PBC bodies side-by-side, 7-per-page wrap; COM1/COM2 valve columns directly under each PBC ordered SUPPLY → GEX → HOOD → AUX top-to-bottom, LON4 terminator at the bottom of each column). Implemented in `cad/bricscad.py:generate_pbc_page`, called from `app.py:generate` BEFORE the lab room loop.
- Auto-extension of model-space borders for pages 5+ via `cad/bricscad.py:extend_template_pages` — page-1 entities replicated through `ent.Copy() + Move()` per page. No more manual template work for >3-lab projects.
- Auto-replication of paper-space layouts via `_LAYOUT _C` LISP SendCommand: each page gets its own sheet (`7.301`, `7.302`, …, `7.31N`).
- Per-sheet viewport view-shift — each cloned viewport zooms to its corresponding model-space page. Cloned viewports inherit `DisplayLocked = True` and silently reject view changes via every direct API; the fix is unlock → ZOOM → relock.
- Multi-page rooms: rooms with >2 valve rows get extra pages, subsequent rooms shift down accordingly.

Phase A (audit-driven correctness fixes) shipped 2026-05-07: state-restore guards in paper-space replication, ROOM-name page accounting for empty rooms, gated AutoCAD fallback in `connect()`, row-identity-based same-row wire detection, view-shift for pre-existing template layouts, and several UI signal/lambda safety fixes. See git log for details.

Currently working through Phase B (project hygiene: docs reset, hygiene cleanup, dead code) and Phase C (UX polish — backgrounded generation, humanized COM errors, pre-flight validation). See `docs/AUDIT_PLAN_2026-05-07.docx` for the full plan.

## Architecture cheat sheet

```
app.py:generate(project)
  ├─ load config + layout spec
  ├─ open BricsCAD, load templates/Background.dwg
  ├─ extend_template_pages(...) if project needs more pages than template
  ├─ generate_pbc_page(...)                        # PBC network page(s) FIRST
  ├─ for room_idx, room in enumerate(rooms):
  │     # Each room reserves a page slot — empty rooms still get one.
  │     # cumulative_extra tracks multi-page room overflow.
  │     room_first_page = room_idx + pbc_pages_drawn + cumulative_extra
  │     room_layout.anchor_y = layout.anchor_y - room_first_page * page_height
  │     bricscad.insert_with_dynamic_layout(...)   # places valve blocks
  │     bricscad.draw_mstp_wires(...)              # uses (page_idx, row_idx)
  │     bricscad.insert_eol_marker(...)            # bbox-centered EOL
  │     bricscad.add_tag_labels(...)               # text above each block
  ├─ replicate_paper_space_layouts(...)            # one sheet per page
  ├─ bricscad.update_title_block(...)              # paper-space attrs (all sheets)
  └─ bricscad.update_room_text(...)                # find-and-replace ROOM:
```

Key data flow:
- `ui/main_window.py:_collect_project()` returns the project dict (schema v2).
- `_load_project_from_path` calls `_resolve_block_paths` to fill in any missing/stale `dwg_path` from variant_id + product_line + category — so test fixtures and hand-edited projects can ship without absolute Windows paths.
- `cad/layout.py:flatten_job(room)` converts `{SAV: [...], GEX: [...], ...}` to a flat list of `Placement(category, variant_id, dwg_path, tag, x, y, width, height, is_reversed, page_idx, row_idx)`.
- `cad/bricscad.py:insert_with_dynamic_layout` does bbox-snap insertion: insert at parking origin → read `GetBoundingBox()` → `Move` to target. Without bbox-snap, blocks land on top of each other if their geometry isn't centered at origin. Sets `page_idx` AND `row_idx` per placement so wire routing can compare row identity without being fooled by per-variant `align_offsets` Y nudges.

PBC data:
- `Room.pbcs[]` items have `tag, device_name, device_number, mac, network_number, links[]` where each link = `{valve_tag, com_trunk}`. `com_trunk` is canonically int `1` or `2`, but the loader and renderer both tolerate `"1"`/`"2"`/`"COM1"`/`"COM2"` (case-insensitive).
- `ui/pbc.py:PBCSection` shows count + Edit buttons. `PBCWizardDialog` wraps `PBCEditor`. `refresh_all` forwards into the live wizard's editor when one is open (modal today, future-proof for non-modal). Signal chain: `CategorySection.changed → RoomEditor._on_valve_changed → PBCSection.refresh_all → PBCEditor.refresh_valve_list`.

**Block library directory naming:** `AUX` is a Windows reserved device name, so the on-disk directory is `blocks/cscp/AUXILIARY/`. The category KEY stays `"AUX"` everywhere in code and JSON; `cad/blocks._CATEGORY_DIRNAME` maps `"AUX"` → `"AUXILIARY"` when resolving file paths. Don't reintroduce the AUX directory.

## Hot spots / gotchas

**BricsCAD COM:**
- Dispatch `BricscadApp.AcadApplication`, fall back to `AutoCAD.Application`. The fallback only fires when Dispatch ITSELF fails (CAD not installed/registered) — once Dispatch succeeds we commit to that app and create a doc if needed, rather than silently swapping CAD apps on a transient issue.
- `replicate_paper_space_layouts` mutates app/doc state (`Visible`, `FILEDIA`, `DisplayLocked`, `MSpace`, `ActiveLayout`). The whole body is wrapped in try/finally so a mid-burst exception still restores user-visible state — without that guard, a crash leaves BricsCAD invisible / dialogs suppressed / viewports pannable.
- Points are VARIANT-typed: `win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (x, y, z))`. The `_pt(x, y)` helper in tools/ is the canonical wrapper.
- `InsertBlock(point, name, x_scale, y_scale, z_scale, rotation)` inserts an external DWG as a block reference. After insert, read bbox via `GetBoundingBox()` and `Move(...)` if you need the geometry positioned by its bbox corner instead of its insertion point.
- Attribute definitions inside a block become `AcDbAttribute` instances on the inserted reference — get them with `GetAttributes()` and set via `attr.TextString = "..."`. Hidden mode = `mode=1`.
- `LWPOLYLINE` with `ConstantWidth = 1.875` (1 7/8") for MSTP buses. Bus polylines straightened via `tools/straighten_polylines.py` (1.0" snap threshold).

**Wire drawing:**
- Same-row identity is `(prev.page_idx, prev.row_idx) == (cur.page_idx, cur.row_idx)`, NOT a Y-coord comparison. `align_offsets` can nudge per-variant Y by tens of inches, which would fool an `abs(prev.y - cur.y) < epsilon` check and route the wire through the wrong margin.
- Same-row pairs: straight horizontal, or 6-point Z-shape with vertical bridge in inter-block gap when actual port Ys differ within the same row.
- Wraps within a page: serpentine (row 1 L→R, row 2 R→L). Inter-row wires routed through the page's right margin.
- Cross-page wire: routed through the page's left margin (`X ≈ page.x_min + 15`) to avoid the title block.
- `SAFETY_OVERLAP = 2.0` shifts wire endpoints inward into the block by 2" so the polyline visually overlaps the bus rail (covers up to ~0.5" of vertex drift).

**Port offsets drift after polyline edits.** If wires look slightly off after re-straightening, run `tools/anchored_refresh.py` — uses original user measurements as anchors, finds closest current vertex (within 5"), recomputes offsets.

**Page bounds:** `config/product_lines.json:page` is **world coords**, not sheet inches. `x_min/x_max/y_min/y_max` is the orange title-block border on page 1; pages stack vertically at `page_height` intervals (no gap).

## UI conventions (don't regress)

- Mouse wheel must NOT change combo/spin values unless the widget is focused. Use `NoScrollComboBox` / `NoScrollSpinBox` / `NoScrollDoubleSpinBox` from `ui/components.py`. Justin called this out specifically.
- Dark navy theme is mandatory — never `setStyleSheet(...)` for colors/borders. Use `setObjectName(...)` and let `phoenix_style.qss` handle it. Copy QSS updates from Phoenix-Checkout-Tool, never diverge.
- PBC editor is a modal Wizard (QDialog), not inline. Form was getting too long with inline + count layouts.
- PBC column order top-to-bottom: SUPPLY → GEX → HOOD → AUX (Justin updated original spec on 2026-05-06).
- COM1/COM2 is user-picked per linked valve, not auto-split.
- Valve tags are free-form user input (`PSV-1`, `PEV-2`). Do NOT auto-generate.

## Build / release

`build.bat` runs PyInstaller `--onedir` and zips outputs into `dist/`. **Run from cmd.exe, not Bash** — PyInstaller's MSYS handling has bitten Justin before.

**Don't push to GitHub or cut a release without explicit go.** Repo URL `https://github.com/JustinGlave/lab-layout-tool` exists and `updater.py` polls it. The working tree IS a local git repo (initialised 2026-05-07) but nothing has been pushed and no GitHub releases exist. Look for explicit verbs: *release*, *ship*, *push it*, *publish*, *tag v0.1.0*. See `feedback_release_timing.md` in memory. Tag `pre-audit-baseline` is the rollback target before the audit's correctness fixes.

## Files you'll touch most

- `cad/bricscad.py` — all CAD drawing logic. PBC generation will live here.
- `app.py` — `generate(project)` orchestration.
- `config/product_lines.json` — page bounds, MSTP port offsets, align offsets, tag prefixes.
- `ui/main_window.py` — project metadata + room tabs + sidebar tree.
- `ui/pbc.py` — PBC editor / wizard.
- `tools/generate_pbc_blocks.py` — re-run if you change PBC block geometry.
- `tools/anchored_refresh.py` — re-run after editing/straightening any CSCP DWG.

## Decision log highlights (full list in PLAN.md)

- Multi-room project model (one drawing = many rooms, one room per page) — user req: "1 building 10 labs"
- Title-block fields: `JOBNAMETOP/JOBNUM/DRAFTER/DATE`, no PM attribute (user picked which)
- Per-PBC editor lives in a modal Wizard dialog, not inline (form was getting long)
- PBC column order top-to-bottom: SUPPLY → GEX → HOOD → AUX (Justin's updated spec on 2026-05-06)
- COM1/COM2 assignment is user-picked, not auto (user-specified)
- Wire safety overlap = 2.0" inward into block (masks sub-inch float drift)
- Cross-page wire routes through left margin (`x_min + 15`) to avoid the next page's title block
- Free-form tag input per valve, no auto-suggestion (user wanted explicit control)
