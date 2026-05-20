# Changelog

All notable changes to **Lab Layout Tool** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

Tool is in pre-1.0 territory; minor bumps may include user-visible
behaviour changes until v1.0.0.

## [Unreleased]

### Changed
- **Phase 3A retrofit (2026-05-19)**: migrated to commons-backed
  pattern per ADR-015 (`phoenix-commons` git submodule + editable
  install). Theme + widgets + paths + updater now flow through
  `phoenix_commons` rather than local duplicates. Visible behaviour
  preserved (≈ 0% UI change). Local backup of pre-retrofit
  `phoenix_style.qss` kept under `legacy/` per MIGRATION_RULES.md
  § "Local backup QSS strategy". Merged via `--no-ff` to
  `master` as commit `79c7003`.

### Added
- CHANGELOG.md (this file) — Operational Hardening Sprint
  2026-05-19.

## [0.1.1] — 2026-05-12

Initial public version. Phoenix CAD desktop application that drives
BricsCAD via COM to generate 2D as-built lab valve drawings.

### Features
- Multi-room project model with shared title block.
- Per-valve tag generation with MSTP wiring + EOL terminators.
- Optional first-page PBC network drawing.
- PySide6 dark-navy UI (System A theme).
- Auto-updater via GitHub Releases (full-folder payload contract).
- Inno Setup installer to `{localappdata}\ATS Inc\Lab Layout Tool`.
- PyInstaller `--onedir --windowed` build pipeline.
