# Lab Layout Tool

[![CI](https://github.com/JustinGlave/lab-layout-tool/actions/workflows/ci.yml/badge.svg)](https://github.com/JustinGlave/lab-layout-tool/actions/workflows/ci.yml)

PySide6 desktop tool that drives BricsCAD via COM to generate 2D as-built lab valve drawings — multi-room projects with metadata, per-valve tags, MSTP wiring, EOL terminators, and an optional PBC network page.

Part of the **ATS Inc. tool suite** — same Phoenix Controls dark-navy design system as Project Tracking Tool and Phoenix Checkout Tool.

Current Version: v0.1.2

## Quick start

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Requires BricsCAD (or AutoCAD) installed locally. The tool talks to it via COM (`BricscadApp.AcadApplication`, falling back to `AutoCAD.Application`).

For a status snapshot of what's built and what's next, see [PLAN.md](PLAN.md).

## What it does

1. **New Project** — fill in job name, job number, technician, date, product line.
2. **Add rooms** — set the room count; each room becomes a tab. Per room, name it (e.g. `LAB 101`), then for each valve category (SAV / GEX / FEV / AUX) pick variants from a dropdown and type a tag (e.g. `PSV-1`, `PEV-2`).
3. **Add PBCs (per room)** — count spinner; per PBC, an Edit button opens a wizard with TAG / device name / device number / MAC / network number, plus a linked-valves table to pick which valves in the room belong to COM1 vs COM2 of that PBC.
4. **Generate** — opens BricsCAD, loads `templates/Background.dwg`, places valve blocks per room (one room per page), draws the MSTP comm chain with EOL terminator, fills the title-block attributes (job name / number / drafter / date), and writes per-room "ROOM: LAB XX" text. Saves to `jobs/drawings/<name>_<timestamp>.dwg`.

A **Tools → Test** menu has Quick Test (3 labs) and Full Test (10 labs covering all CSCP variants) for one-click smoke tests against `jobs/Quick_Test_Building.json` / `jobs/thorough-test.json`. Both fixtures ship without absolute paths — `dwg_path` is resolved from `variant_id` + product line + category at load time, so the fixtures are portable across machines.

## Block library

```
blocks/
  cscp/               ← fully populated (14 valve variants)
    SAV/   SAV_SINGLE_PBC_ACM_START.dwg    SAV_DOUBLE_PBC_ACM_START.dwg
           SAV_SINGLE_ACM_START.dwg        SAV_DOUBLE_ACM_START.dwg
           SAV_SINGLE_ACM.dwg              SAV_DOUBLE_ACM.dwg
    GEX/   GEX_SINGLE.dwg   GEX_DOUBLE.dwg
    FEV/   FEV_SINGLE.dwg   FEV_DOUBLE.dwg
    AUXILIARY/  CAGE_SINGLE.dwg  CAGE_DOUBLE.dwg
                SNORKEL_SINGLE.dwg  SNORKEL_DOUBLE.dwg
  celeris_ii/         ← directories exist, empty (backlog)
  theris/             ← empty (backlog)
  traccell/           ← empty (backlog)
  misc/               ← shared building blocks
    eol.dwg                MSTP end-of-line terminator
    pbc.dwg                PBC body (TAG/DEVICE_NUM/MAC attrs)
    pbc_valve_{gex,hood,aux,supply}.dwg   PBC valve sub-blocks
    pbc_network.dwg        BMS NETWORK reference geometry
    title_sheet.dwg        ...
  _reference/         ← out-of-band reference DWGs (not loaded at runtime)
```

**Naming convention:**
- SAV/GEX/FEV/AUX dropdowns auto-discover whatever DWGs are in their directory.
- SAV/GEX/FEV: `{TYPE}_{CONFIG}[_extra].dwg` — `CONFIG` is `SINGLE` / `DOUBLE` (case-insensitive). SAV has 6 variants because the user picks PBC ACM Start / ACM Start / ACM (non-start); PBC+ACM is start-only, the third variant is always ACM-only.
- AUX: free-form snake_case → Title Cased in dropdown (`gas_cabinet.dwg` → "Gas Cabinet").
- **AUX directory note:** the on-disk folder is `AUXILIARY/`, not `AUX/` — `AUX` is a Windows reserved device name (PowerShell can't access it; git needs `core.protectNTFS=false`). The category KEY is still `"AUX"` everywhere in code and JSON; `cad/blocks._CATEGORY_DIRNAME` maps it to `AUXILIARY` when constructing paths.

After dropping a new DWG in, hit `View → Refresh Block Library` (F5). To wire a new variant into the MSTP chain, register its port offsets in `config/product_lines.json` under `mstp.ports` (see "Port offsets" below).

## Page layout (multi-room)

`templates/Background.dwg` ships with 4 stacked title-block borders. Projects needing more pages (PBC + N rooms, multi-page rooms, etc.) auto-extend the template at generation time via `cad/bricscad.py:extend_template_pages` — page-1 entities are duplicated downward by `page_height`. The generator places **one room per page slot** (top page = first room). Bounds are world coords in `config/product_lines.json:page` (`x_min/x_max/y_min/y_max` and `page_height` between borders).

For each room:
- Anchor at `(101.6875, anchor_y - room_first_page * page_height)` where `room_first_page = room_idx + pbc_pages_drawn + cumulative_extra`. Empty rooms still reserve a page slot so room→page mapping stays consistent.
- Place blocks left-to-right with `h_gap = 30"`. If a row exceeds `max_row_width = 1400"`, wrap to the next row (`v_gap = 30"`). Within a row, use straight horizontal MSTP wires; row-to-row wires serpentine through the right margin (odd rows L→R, even rows R→L).
- Insert EOL block at the chain end (centered on the bus Y).
- Render a free-text tag label above each block.

After all rooms are placed, `replicate_paper_space_layouts` clones the source paper-space layout (typically `7.301`) for every additional page and view-shifts each cloned viewport to its corresponding model-space page. Cloned viewports inherit `DisplayLocked = True` and silently reject view changes via every API; the unlock → ZOOM → relock sequence is essential.

## Per-block port offsets

Each variant has two MSTP ports (entry/exit) that the bus polyline connects. They're **measured offsets from the block's lower-left corner** stored under `mstp.ports[<variant_id>]` in `config/product_lines.json`.

When you straighten/edit a block's polylines, the cached offsets drift. Recompute them with:

```cmd
.venv\Scripts\python tools\anchored_refresh.py
```

This uses the original user-measured world coordinates as anchors, finds the closest current vertex (within 5") and recomputes offsets against the current `EXTMIN`. Original measurements are preserved in `align_offsets._anchored_measurements` in the JSON config.

To straighten near-horizontal/vertical polyline segments before measuring, run:

```cmd
.venv\Scripts\python tools\straighten_polylines.py
```

(threshold is 1.0", `.dwg.bak` backups are written next to each modified DWG).

## Title block

`templates/Background.dwg` paper-space layout `7.301` contains block `ats-flat-3` with these attributes (filled by `cad/bricscad.py:update_title_block`):

| Attribute  | Source                |
|------------|-----------------------|
| JOBNAMETOP | Project → Job name    |
| JOBNUM     | Project → Job number  |
| DRAFTER    | Project → Technician  |
| DATE       | Project → Date        |

To inspect any DWG's blocks/attributes/layouts:

```cmd
.venv\Scripts\python tools\inspect_template.py
.venv\Scripts\python tools\inspect_template.py blocks/misc/pbc.dwg
```

Per-room labels: any model-space text starting with `ROOM:` is found, sorted by Y descending, and the top N matches are replaced with `ROOM: <room name>` — one per room, in order. (`update_room_text`.)

## PBC network builder (Phase 8 — complete)

Status:
- ✅ DWG block files generated by `tools\generate_pbc_blocks.py` (5 blocks).
- ✅ Data model: `Room.pbcs[]` with `tag / device_name / device_number / mac / network_number / links[]`.
- ✅ Form UI: `ui/pbc.py` — count spinner per room + Edit button → `PBCWizardDialog` with all fields + linked-valves table (Link checkbox + COM1/COM2 dropdown per linked valve).
- ✅ Drawing generation (`cad/bricscad.py:generate_pbc_page`) — first pages with BMS NETWORK ellipse, NET branches, side-by-side PBC blocks (7-per-page wrap), valve columns under each PBC sorted SUPPLY → GEX → HOOD → AUX top-to-bottom, MSTP wires, LON4 terminators. Skipped automatically when no room has any PBCs.
- ✅ Auto-extension of model-space borders for projects with >3 labs (`extend_template_pages`).

Constraints (from Justin):
- 1 PBC per lab is typical; future "1 PBC across 4 labs" is out of scope.
- Column order top-to-bottom: **SUPPLY → GEX → HOOD → AUX**.
- COM1 vs COM2 is user-assigned per linked valve, not auto-split.
- Hardware limits (visual only, not enforced): 20 valves, 10 hoods, 30 total per PBC.

To regenerate the PBC blocks (modify the source script first):

```cmd
.venv\Scripts\python tools\generate_pbc_blocks.py
```

## Design system

This tool follows the **ATS / Phoenix Controls Unified Design System** — dark navy theme with blue & red brand colors. Key files:

- `phoenix_style.qss` — canonical stylesheet (copied from Phoenix-Checkout-Tool; copy any future updates from there, don't diverge).
- `ui/style.py` — Fusion + dark QPalette + QSS loader, with embedded QSS fallback for auto-update scenarios.
- `ui/components.py` — `PrimaryButton`, `SecondaryButton`, `TertiaryButton`, `PageTitle`, `SectionTitle`, `Panel`, `PhoenixTable`, plus `NoScrollComboBox` / `NoScrollSpinBox` / `NoScrollDoubleSpinBox` (mouse wheel does **not** change values unless the widget is focused — Justin called this out, don't regress it).
- `LLT_Normal.ico` / `LLT_Transparent.png` — orange-themed app icon (each suite app uses a different color: green = Checkout, blue = PTT, orange = this).

Layout rules (8px grid):
- Window margins 16,16,16,16; spacing 16 between sections; spacing 8–12 within a section.
- Buttons / inputs minimum height 36 (32 in dense forms).
- Never `setStyleSheet` on individual widgets for colors/borders — use `setObjectName(...)` and the QSS handles it.

## Project layout

```
app.py                       entry point — generate(project) drives BricsCAD
version.py                   __version__ — bump before each release
build.bat                    PyInstaller --onedir build + zips + (optional) Inno Setup
phoenix_style.qss            shared design system stylesheet
PLAN.md                      phased buildout plan + tomorrow's pickup
config/product_lines.json    product lines, tag prefixes, page bounds, mstp.ports, align_offsets
ui/style.py                  apply_dark_theme + _EMBEDDED_QSS + _resource_path
ui/components.py             Phoenix component helpers + NoScroll widgets
ui/main_window.py            MainWindow (project metadata + room tabs + sidebar tree)
ui/pbc.py                    PBCSection + PBCWizardDialog
cad/blocks.py                block library discovery
cad/layout.py                Placement + LayoutSpec + flatten_job (pure math)
cad/bricscad.py              COM driver — insert, wire, EOL, tag labels, title-block, room text
tools/                       generate_pbc_blocks, anchored_refresh, straighten_polylines,
                             generate_psh500a, inspect_template
blocks/<line>/<CAT>/*.dwg    block library (cscp populated; others empty)
                             AUX maps to AUXILIARY/ on disk (Win32 reserved name)
blocks/misc/*.dwg            EOL, PBC, PBC-valve sub-blocks, ...
blocks/_reference/*.dwg      out-of-band reference DWGs (not loaded at runtime)
templates/Background.dwg     4-border template; auto-extended for >3-room projects
jobs/*.json                  saved project configs (Quick_Test_Building.json,
                             thorough-test.json — both portable, no absolute paths)
jobs/drawings/*.dwg          generated as-builts (gitignored)
jobs/last_generation.log     log from the most recent generate() run (gitignored)
docs/AUDIT_PLAN_*.docx       periodic audit + phased fix plans
```

## Build a release

> **Don't push to GitHub or publish a release without explicit go from Justin** — see `feedback_release_timing.md` in memory.

Bump `version.py`, then:

```cmd
build.bat
```

Outputs in `dist/`:
- `LabLayoutTool/LabLayoutTool.exe` — test this first
- `LabLayoutTool.zip` — auto-updater payload (contains `LabLayoutTool.exe` + `_internal/` at the zip root; `build.bat` verifies this before completing)
- `LabLayoutTool_FullInstall.zip` — full install zip
- `LabLayoutToolSetup.exe` — Inno Setup installer (requires Inno Setup 6 — `build.bat` skips this step gracefully if it's not installed)

Run `build.bat` from cmd.exe, **not** from a Bash shell — PyInstaller's spawn semantics under MSYS bash have caused issues for Justin before.

## Auto-updater

Each launch, the app polls
`https://api.github.com/repos/JustinGlave/lab-layout-tool/releases/latest`
in a background thread (see [updater.py](updater.py)). If a newer tag is
available, an Update Banner appears in the status bar with **Install & Restart**.
Clicking it downloads `LabLayoutTool.zip`, verifies the contents, then writes a
PowerShell + .bat that waits for this process to exit, replaces the entire app
folder, and relaunches. Auto-update only works in the compiled .exe (running
from source, the button shows an explanatory error).

You can also force a check anytime via **Help → Check for Updates**.

To configure for a different repo, edit `GITHUB_OWNER` / `GITHUB_REPO` at the
top of [updater.py](updater.py).

## Installer (Inno Setup)

The installer ([installer.iss](installer.iss)) installs to
`%LOCALAPPDATA%\ATS Inc\Lab Layout Tool`. No admin rights required — this also
means the auto-updater can replace files in the install folder without UAC.
Uninstall asks whether to keep saved jobs and generated drawings under
`%APPDATA%\ATS Inc\Lab Layout Tool\`.

To build just the installer (after PyInstaller has run):

```cmd
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" /DMyAppVersion=0.1.0 installer.iss
```
