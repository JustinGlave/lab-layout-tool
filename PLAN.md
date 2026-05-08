# Lab Layout Tool — Phased Plan

Reference doc for the staged buildout. Each phase is a checkpoint: don't start the next phase until the previous one's acceptance criteria are met.

## Quick state (as of 2026-05-07)

- Phases 0–8: ✅ done
- **Audit Phase A (correctness fixes): ✅ shipped 2026-05-07** — see audit doc + git log A1–A9
- **Audit Phase B (project hygiene): ⚙️ IN PROGRESS** — docs reset, dead-code cleanup, fixture portability, repo hygiene
- Phase 9+ (other product lines, Excel export, …): backlog
- See `docs/AUDIT_PLAN_2026-05-07.docx` for the full audit-driven phase plan.

## ⭐ Stable checkpoint (2026-05-07 — Phase 8 COMPLETE)

End-to-end working on the thorough-test (10 labs + 10 PBCs across 2 PBC pages → 12 model-space pages, paper-space sheets `7.301`–`7.31N`, each viewing its OWN page):

- ✅ PBC network page generation (BMS NETWORK ellipse + NET branches + PBC bodies side-by-side, 7-per-page wrap; COM1/COM2 valve columns directly under each PBC ordered SAV → GEX → FEV → AUX top-to-bottom, terminated by LON4)
- ✅ Multi-page rooms (rooms with >2 rows of valves get extra pages, subsequent rooms shift down accordingly)
- ✅ Auto-extension of model-space borders for pages 5+ (page-1 entities replicated via `ent.Copy() + Move()` per page)
- ✅ Auto-replication of paper-space layouts via `_LAYOUT _C` LISP SendCommand (each page gets its own sheet — `7.301`, `7.302`, …, `7.31N`, named by incrementing the trailing integer in source name)
- ✅ **Per-sheet viewport view-shift** — each clone's viewport zooms to its corresponding model-space page
- ✅ Title-block attributes auto-filled across ALL paper-space layouts (`update_title_block` iterates `doc.Layouts`)
- ✅ ROOM: text replaced per-page in model space with proper room-name padding for multi-page rooms
- ✅ App-visibility-off + REGENMODE-off speed-knobs cut paper-space replication from minutes-per-page to seconds total

### The DisplayLocked breakthrough

For most of 2026-05-07 we couldn't shift each clone's viewport view. Tried direct COM `ViewCenter` / `Target` / `SetView` (rejected as read-only), LISP `setvar CTAB` + `_MSPACE` + ZOOM (MSPACE no-op'd, ZOOM hit paperspace), direct-COM `doc.ActiveLayout` + `doc.MSpace` + ZOOM (same paperspace-zoom-out problem). Even Justin manually double-clicking into a viewport and running ZOOM CENTER hit paperspace — BricsCAD made it look like the viewport accepted entry but silently ignored view changes.

**The cause:** cloned viewports inherit `DisplayLocked = True` from the source. The lock makes BricsCAD silently reject view changes via every COM/LISP/SendCommand path. Justin found it by clicking the unlock button in the Properties panel after entering modelspace.

**The fix in `replicate_paper_space_layouts`** — for each layout (source + clones):
1. Find every `AcDbViewport` in the layout's block, set `DisplayLocked = False` via direct COM
2. `doc.ActiveLayout = layout` to switch GUI tab
3. `doc.MSpace = True` to enter the now-unlocked viewport
4. Verify `CVPORT != 1` (we're really in model space)
5. `SendCommand "(command \"_ZOOM\" \"_C\" (list cx cy 0) view_height)"`
6. `doc.MSpace = False` back to paperspace
7. Set `DisplayLocked = True` again so the user can't accidentally pan

---

## Phase 0 — Foundation ✅

PySide6 GUI shell on the ATS Phoenix design system, BricsCAD COM driver wired, build pipeline in place. See `README.md` for the build/run commands. Stack: Python 3.14, PySide6 6.10.2, pywin32, BricsCAD via COM.

## Phase 1 — First Real Drawing ✅

End-to-end: form → BricsCAD → DWG with one valve block placed.

## Phase 2 — Full CSCP Block Library ✅

CSCP blocks all in place (10 valve variants — see `blocks/cscp/`). Other product lines (Celeris II / THERIS / TRACCELL) still empty — backlog.

**Decisions locked in here:**
- Block naming: `{TYPE}_{CONFIG}.dwg` for SAV/GEX/FEV (e.g. `SAV_SINGLE.dwg`); free-form for AUX (e.g. `CAGE_DOUBLE.dwg`).
- SAV has 6 variants (Single/Double × PBC ACM Start / ACM Start / ACM non-start). PBC+ACM is start-only, non-start is always ACM-only.
- Free-form **tag input per valve** (user types `PSV-1`, `PEV-2`, etc.). No auto-tag generation.

## Phase 3 — MSTP Wiring + EOL + Serpentine Layout ✅

- Same-row pairs: straight horizontal, or 6-point Z-shape with vertical bridge in inter-block gap when rail Y differs
- Wraps within a page: serpentine (row 1 L→R, row 2 R→L), wires routed through the page's right margin
- Cross-page wire: routed through the page's left margin (X ≈ `page.x_min + 15`) to avoid the title block area
- EOL block (`blocks/misc/eol.dwg`) inserted at the chain end per room
- Tag labels rendered as text above each block (`add_tag_labels`)

**Tools written in this phase:**
- `tools/anchored_refresh.py` — re-resolve port offsets against current DWGs using each variant's anchor coords as input (handles drift after polyline straightening)
- `tools/straighten_polylines.py` — snap near-axis polyline segments to exact horizontal/vertical (with `.dwg.bak` backups)

(Earlier iterations `measure_ports.py`, `compute_offsets.py`, `refresh_offsets.py` were superseded by `anchored_refresh.py` and removed during Phase B cleanup; recover from git history if a future product line needs onboarding-style measurement.)

## Phase 4 — UX Polish (partial)

Done:
- No-scroll combo + spin (`NoScrollComboBox`, `NoScrollSpinBox`) — wheel scrolls don't change values unless widget is focused.
- Sidebar tree (Project → Rooms → Tagged valves) for navigation; click a room/valve to jump tabs.
- Tools → Test → Quick Test / Full Test menu.

Still backlog:
- Background overlay logo (~12% opacity centered, like Checkout Tool's `_BgWidget`).
- Block thumbnail previews in dropdowns.
- Job browser dialog replacing the bare file picker.
- Drag-to-reorder valves within a category section.
- Welcome dialog with "don't show again".
- Settings dialog for layout/page tuning.
- Better COM-error surfacing.

## Phase 5 — Suite Integration ✅ (infrastructure)

- `installer.iss` (Inno Setup), `updater.py` (full-folder GitHub-Releases updater), `UpdateBanner` widget, `build.bat` with zip-content verification — all in place.

Backlog (ship-related — explicit go required, see feedback memory):
- Push to `JustinGlave/lab-layout-tool` repo with the suite-standard metadata files.
- `AGENTS.md` (build commands, gotchas) is in place — see project root.
- First GitHub Release — bump `version.py` → 0.1.0, run `build.bat`, attach the three artifacts.

## Phase 6 — Multi-room project model ✅

Refactored from "one job = one drawing" to "one project = many rooms". Job schema v2:

```
Project
  ├─ job_name, job_number, technician, date, product_line
  └─ rooms[]
       ├─ name (e.g. "LAB 101")
       ├─ SAV/GEX/FEV/AUX (each a list of {variant_id, label, dwg_path, tag})
       └─ pbcs[]    ← Phase 8 adds this
```

UI: top-level metadata fields + room count spinbox. Each room is a tab with the 4 valve panels and a Tag input next to each variant dropdown. Sidebar tree shows project → rooms → tagged valves.

Generation: each room placed on its own page (`anchor_y - room_idx * page_height`). Each room has its own MSTP chain with EOL. No cross-room wires.

## Phase 7 — Title-block auto-fill + ROOM text ✅

- Project metadata writes to title-block attributes in paper-space:
  - `JOBNAMETOP` ← Job name
  - `JOBNUM` ← Job number
  - `DRAFTER` ← Technician
  - `DATE` ← Date
- Per-room "ROOM: LAB XX" text in model space is found (text starting with `ROOM:`), sorted by Y descending, and replaced with `ROOM: <room name>` for each project room.
- Implemented in `cad/bricscad.py`: `update_title_block`, `update_room_text`.

## Phase 8 — PBC Network Builder ✅

Complete — see "Stable checkpoint" at the top of this file for the full breakdown of what shipped (BMS network ellipse + branches, side-by-side PBC bodies wrapping 7-per-page, COM1/COM2 valve columns SUPPLY → GEX → HOOD → AUX, LON4 terminators, multi-page rooms, auto-extension of model-space borders, auto-replication of paper-space layouts, per-sheet viewport view-shift, title-block + ROOM-text auto-fill across all sheets).

The ⭐ DisplayLocked breakthrough at the top of this file is the canonical reference for why per-sheet view-shifts had been failing previously.

**Audit-driven follow-ups (Phase A, shipped 2026-05-07) — see `docs/AUDIT_PLAN_2026-05-07.docx`:**
- A1: page accounting consistent across estimate / actual / ROOM-text slots when a room is empty
- A2: `connect()` doesn't silently swap to AutoCAD when BricsCAD has no doc open
- A3: `replicate_paper_space_layouts` wrapped in try/finally so a mid-burst exception still restores user-visible state
- A4: same-row wire detection compares `(page_idx, row_idx)` instead of post-nudge Y
- A5: view-shift covers pre-existing template layouts, not just freshly-cloned ones
- A6: `PBCSection.refresh_all` actually does the documented sync chain
- A7: confirm before spinbox-driven room removal that would discard data
- A8: lambda-captured RoomEditor reference replaced with `sender()`-based slot
- A9: `com_trunk` accepts int 1/2 or string "1"/"2"/"COM1"/"COM2"

**Constraints (from Justin):**
- 1 PBC per lab usual; future: 1 PBC across 4 labs (out of scope now)
- Column order top to bottom: **SUPPLY → GEX → HOOD → AUX** (per Justin 2026-05-06 evening review)
- COM1 vs COM2 is user-assigned per linked valve (not auto-split)
- Hardware limits (visual only, not enforced yet): 20 valves, 10 hoods, 30 total per PBC
- Multiple PBCs squeeze to fit, wrap to additional pages like the lab pages

## Phase 9 — Other Product Lines (Backlog)

CSCP is fully populated. Celeris II / THERIS / TRACCELL block library directories exist but are empty. Each line uses different tag prefixes (already in config — see `tag_prefixes` per product line). Once block files are dropped in (with consistent layer naming), they should generate without code changes.

## Phase 10 — Advanced Features (Backlog)

- BOM / valve schedule export to Excel (reuse styled-xlsx pattern from Checkout Tool).
- PTT (Project Tracking Tool) linkage — attach generated DWG path back to a PTT project.
- Symbol legend / notes block on each page.
- DXF-only mode via `ezdxf` (no BricsCAD required, useful for headless/CI).
- Per-line layer / color overrides.

---

## Decision log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-05-04 | PySide6 over PyQt6 | Match existing ATS suite (Phoenix Checkout Tool, Project Tracking Tool) |
| 2026-05-04 | Orange icon for this app | Other colors taken: green = Checkout, blue = PTT |
| 2026-05-04 | Block library is filesystem-driven, naming convention `{TYPE}_{CONFIG}.dwg` | No registry/DB needed; drop-in friendly |
| 2026-05-05 | Variants are by configuration (single / dual), not size | Phoenix uses configuration as the meaningful axis |
| 2026-05-05 | Free-form tag input per valve, no auto-suggestion | User wanted explicit control |
| 2026-05-05 | Wire safety overlap = 2.0" inward into block | Masks sub-inch float drift between cached offsets and live rail vertices |
| 2026-05-05 | Cross-page wire routes through left margin (`x_min + 15`) | Avoids crossing the next page's title block |
| 2026-05-06 | Multi-room project model (one drawing = many rooms, one room per page) | User requirement: "1 building 10 labs" |
| 2026-05-06 | Title-block fields: `JOBNAMETOP/JOBNUM/DRAFTER/DATE`, no PM attribute | User picked which attributes; PM was dropped |
| 2026-05-06 | Per-PBC editor lives in a modal Wizard dialog, not inline | Form was getting long; inline + count was cluttered |
| 2026-05-06 | PBC column order top-to-bottom: SUPPLY → GEX → HOOD → AUX | User updated original spec during first PBC review |
| 2026-05-06 | COM1/COM2 assignment is user-picked per linked valve, not auto | User-specified |
