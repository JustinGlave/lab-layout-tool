# CLAUDE.md — Lab Layout Tool cold-start guide

Read this first when picking up the project in a new session. Sister docs: [README.md](README.md) for user-facing setup, [PLAN.md](PLAN.md) for phased buildout state and tomorrow's pickup.

## What this project is

A PySide6 desktop app that drives **BricsCAD via COM** to generate as-built lab valve drawings from form input. Multi-room project model: one project = many rooms = many DWG pages, with a shared title block and (in progress) a first-page PBC network drawing.

Justin works at ATS Inc. on lab controls / Phoenix Controls valve as-builts. Email: `justing@atsinc.org`. He uses BricsCAD + VSCode. This is one of four ATS suite apps that share a dark-navy Phoenix Controls design system (Project Tracking Tool, Phoenix Checkout Tool, this, and one more).

## Where to start

```cmd
.venv\Scripts\activate
python app.py
```

Then **Tools → Test → Quick Test** generates a 3-lab CSCP drawing using `jobs/quick-test.json`. **Full Test** generates a 10-lab thorough test using `jobs/thorough-test.json`. Both open BricsCAD and dump a generated DWG into `jobs/drawings/`.

If you need to inspect what the template / generated DWG actually contains:

```cmd
.venv\Scripts\python tools\inspect_template.py
.venv\Scripts\python tools\inspect_template.py jobs/drawings/<name>.dwg
```

Generation log: `jobs/last_generation.log` (truncated each run).

## Status snapshot

Phases 0–7 complete, Phase 8 in progress. **Tomorrow's task is Phase 8 step 4: PBC drawing generation.** See `PLAN.md` for the exact list — quoting the key bits:

- New first page on the generated drawing — PBC network. Existing lab pages shift to page 2+.
- Layout: BMS NETWORK cloud at top → NET1/NET2/... branches → PBCs side-by-side → COM1/COM2 valve columns ordered SUPPLY → GEX → HOOD → AUX top-to-bottom → LON4 terminator at column bottom.
- Insert PBC blocks with attributes (TAG, DEVICE_NUM, MAC); render the NET label above each block programmatically.
- Insert valve sub-blocks (correct variant per type) with attributes (ROOM, TAG).
- Draw the wires (BMS → PBC, PBC → COM column tops).
- Skip if no PBCs in any room.
- Implement in `cad/bricscad.py:generate_pbc_page` (new). Call from `app.py:generate` BEFORE the room loop so it lands on page 1.

After that, extend `templates/Background.dwg` (or write `tools/extend_template.py`) so projects with > 3 labs have N+1 pages (PBC + N rooms).

## Architecture cheat sheet

```
app.py:generate(project)
  ├─ load config + layout spec
  ├─ open BricsCAD, load templates/Background.dwg
  ├─ for room_idx, room in enumerate(rooms):
  │     room_layout.anchor_y = layout.anchor_y - room_idx * page_height
  │     bricscad.insert_with_dynamic_layout(...)   # places valve blocks
  │     bricscad.draw_mstp_wires(...)              # 6-pt polyline w/ bridge_x
  │     bricscad.insert_eol_marker(...)            # bbox-centered EOL
  │     bricscad.add_tag_labels(...)               # text above each block
  ├─ bricscad.update_title_block(...)              # paper-space attrs
  └─ bricscad.update_room_text(...)                # find-and-replace ROOM:
```

Key data flow:
- `ui/main_window.py:_collect_project()` returns the project dict (schema v2).
- `cad/layout.py:flatten_job(room)` converts `{SAV: [...], GEX: [...], ...}` to a flat list of `Placement(category, variant_id, dwg_path, tag, x, y, width, height, is_reversed, page_idx)`.
- `cad/bricscad.py:insert_with_dynamic_layout` does bbox-snap insertion: insert at parking origin → read `GetBoundingBox()` → `Move` to target. Without bbox-snap, blocks land on top of each other if their geometry isn't centered at origin.

PBC data:
- `Room.pbcs[]` items have `tag, device_name, device_number, mac, network_number, links[]` where each link = `{room_index, category, variant_index, com}` (`com` is `"COM1"` or `"COM2"`).
- `ui/pbc.py:PBCSection` shows count + Edit buttons. `PBCWizardDialog` wraps `PBCEditor`. The linked-valves table refreshes when valves change in any room (signal chain: `CategorySection.changed → RoomEditor._on_valve_changed → PBCSection.refresh_all → PBCEditor.refresh_valve_list`).

## Hot spots / gotchas

**BricsCAD COM:**
- Dispatch `BricscadApp.AcadApplication`, fall back to `AutoCAD.Application`. Never assume only one is installed.
- Points are VARIANT-typed: `win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, (x, y, z))`. The `_pt(x, y)` helper in tools/ is the canonical wrapper.
- `InsertBlock(point, name, x_scale, y_scale, z_scale, rotation)` inserts an external DWG as a block reference. After insert, read bbox via `GetBoundingBox()` and `Move(...)` if you need the geometry positioned by its bbox corner instead of its insertion point.
- Attribute definitions inside a block become `AcDbAttribute` instances on the inserted reference — get them with `GetAttributes()` and set via `attr.TextString = "..."`. Hidden mode = `mode=1`.
- `LWPOLYLINE` with `ConstantWidth = 1.875` (1 7/8") for MSTP buses. Bus polylines straightened via `tools/straighten_polylines.py` (1.0" snap threshold).

**Wire drawing:**
- Same-row pairs: straight horizontal, or 6-point Z-shape with vertical bridge in inter-block gap when rail Y differs.
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

**Don't push to GitHub or cut a release without explicit go.** Repo URL `https://github.com/JustinGlave/lab-layout-tool` exists and `updater.py` polls it, but the working tree isn't a git repo yet and nothing has shipped. Look for explicit verbs: *release*, *ship*, *push it*, *publish*, *tag v0.1.0*. See `feedback_release_timing.md` in memory.

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
