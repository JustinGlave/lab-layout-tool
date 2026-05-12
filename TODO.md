# Lab Layout Tool — TODO

Tracking outstanding work outside the audit phases already landed.

Closed phases: F1–F4 and G1–G4 (commits `5cc5b33`..`bde3ea1`),
v0.1.1 published 2026-05-12.

---

## Immediate

- [ ] **Back up local v0.1.0 install data.** If you have v0.1.0 installed
  anywhere (work machine, laptop, etc.) with real saved projects in
  `<install>\_internal\jobs\`, copy those JSONs to
  `%APPDATA%\ATS Inc\Lab Layout Tool\jobs\` **before** the auto-updater
  pulls v0.1.1. The G1 fix moves user data to the right place going
  forward, but the auto-update wipes `_internal/` so any data still
  there at update time is lost.

## Substantial (own session each)

- [ ] **F4: function decomposition in `cad/bricscad.py`** (~2 hr) —
  extract `_view_shift_one_layout` from `_replicate_layouts_inner`,
  extract `_advance_to_next_row` from `insert_with_dynamic_layout`,
  document `update_title_block`'s blank-field policy.
- [ ] **`tests/` directory + first unit tests** (~2 hr) — CI workflow
  has a placeholder waiting at `.github/workflows/ci.yml:68-69`. When
  `tests/` exists, replace the placeholder `echo` with
  `python -m unittest discover -s tests`. Design fixtures that don't
  need BricsCAD COM (parse-only, geometry math, config validation).
- [ ] **Extract shared `cad/com.py:connect_app()`** (~1 hr) — 5 tool
  scripts (`tools/generate_pbc_blocks.py`, `tools/anchored_refresh.py`,
  `tools/inspect_template.py`, `tools/generate_thumbnails.py`,
  `tools/generate_psh500a.py`) each have a copy of the ProgID-fallback
  connect logic. The runtime path implements A2's "don't silently fall
  through to AutoCAD" rule; tool copies still do the wrong thing on a
  multi-CAD machine.
- [ ] **Per-layout success logging in `_replicate_layouts_inner`**
  (~30 min) — cad-com-debugger flagged: currently only failures are
  logged. Adding CVPORT + ViewCenter + ViewHeight readback after each
  ZOOM would let future synthetic-ZOOM-misalignment diagnoses pinpoint
  the layout that drifted.

---

Notes:
- `.claude/agents/*` subagents (cad-com-debugger, phoenix-ui-reviewer,
  audit-reviewer, release-engineer) are local-only dev tooling per
  user decision — kept out of git via `.gitignore`.
- v0.1.0 → v0.1.1 upgrade caveat is documented in the v0.1.1 release
  notes and in this file's "Immediate" section.
