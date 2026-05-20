r"""Filesystem path resolution for source vs. frozen builds.

Two distinct concepts:

- ``USER_DATA_DIR`` — writable, persists across auto-updates. In a PyInstaller
  frozen build, ``__file__`` lives at ``<install>\_internal\...`` and the
  auto-updater wipes ``_internal\`` on every update. Writing user data there
  silently destroys it. Frozen → ``%APPDATA%\<ORG>\<APP>``. Source → project
  root (so dev work stays in the repo, not in your roaming profile).

- ``PROJECT_ROOT`` — read-only resources bundled with the app (templates,
  blocks, config, fixtures). Frozen → ``_MEIPASS`` (PyInstaller's resource
  extraction dir). Source → project root.

The two coincide in source mode and diverge in frozen mode. Use the right
constant for the right purpose:

    JOBS_DIR / "my_project.json"        # writable — saved projects
    OUTPUT_DIR / "drawing.dwg"          # writable — generated DWGs
    LAST_GEN_LOG                        # writable — per-generation log
    FIXTURES_DIR / "thorough-test.json" # read-only — bundled test fixture
    PROJECT_ROOT / "templates" / ...    # read-only — bundled DWG template
    PROJECT_ROOT / "blocks" / ...       # read-only — bundled valve blocks
    PROJECT_ROOT / "config" / ...       # read-only — bundled config

Phase 3A retrofit: ``is_frozen`` now imports from
:mod:`phoenix_commons.paths`. The user-data resolution stays app-local
because Phoenix CAD's source-mode policy (writable data → repo root)
differs from commons's default (writable data → ``%APPDATA%`` always —
intended for tools where dev runs should share the installed-tool's
state). Per MIGRATION_RULES.md § Drift-vs-extension heuristic, this is
an app-local extension that uses commons primitives — not drift.

This module has zero non-stdlib dependencies beyond ``phoenix_commons.paths``
(itself stdlib-only), so it remains safe to import from anywhere (cad/,
ui/, tools/, app.py).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from phoenix_commons.paths import is_frozen

ORG_NAME = "ATS Inc"
APP_NAME = "Lab Layout Tool"

_SOURCE_ROOT = Path(__file__).resolve().parent


def _resolve_user_data() -> Path:
    if is_frozen():
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / ORG_NAME / APP_NAME
        # APPDATA unset is highly unusual on Windows; fall back to user profile
        # rather than crash on startup.
        return Path.home() / ORG_NAME / APP_NAME
    return _SOURCE_ROOT


def _resolve_project_root() -> Path:
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return _SOURCE_ROOT


USER_DATA_DIR = _resolve_user_data()
PROJECT_ROOT = _resolve_project_root()

# Writable user data (do NOT bundle into the build payload).
JOBS_DIR = USER_DATA_DIR / "jobs"
OUTPUT_DIR = USER_DATA_DIR / "jobs" / "drawings"
LAST_GEN_LOG = USER_DATA_DIR / "jobs" / "last_generation.log"

# Read-only bundled resources.
FIXTURES_DIR = PROJECT_ROOT / "jobs"  # test JSON fixtures bundled by build.bat
TEMPLATES_DIR = PROJECT_ROOT / "templates"
BLOCKS_DIR = PROJECT_ROOT / "blocks"
CONFIG_PATH = PROJECT_ROOT / "config" / "product_lines.json"


__all__ = [
    "ORG_NAME", "APP_NAME",
    "is_frozen",
    "USER_DATA_DIR", "PROJECT_ROOT",
    "JOBS_DIR", "OUTPUT_DIR", "LAST_GEN_LOG",
    "FIXTURES_DIR", "TEMPLATES_DIR", "BLOCKS_DIR", "CONFIG_PATH",
]
