"""updater.py — Lab Layout Tool auto-updater (Phase 3A retrofit).

Thin facade over :mod:`phoenix_commons.updater`. The local module-level
constants (``GITHUB_OWNER`` / ``GITHUB_REPO`` / ``EXE_NAME`` /
``ZIP_ASSET_NAME``) stay because they're tool-specific configuration;
the heavy lifting (URL construction, validation, PowerShell + batch
script generation, file replacement, relaunch) now lives in commons.

Public surface preserved for ``ui/main_window.py``:

    UpdateInfo
    UpdatePackageError
    GITHUB_OWNER, GITHUB_REPO, EXE_NAME, ZIP_ASSET_NAME
    check_for_update() -> UpdateInfo | None
    download_and_apply(info, progress_callback=None) -> None

Call-site behaviour is identical to the pre-retrofit module — the
``commons`` facade passes the exact ``expected_internal=True`` /
full-folder layout flags Phoenix CAD has shipped since v0.1.0.
See ADR-003 for the cross-tool updater-payload-contract asymmetry
this preserves.

Was 358 lines duplicating commons (the heavy/5-constant pattern
documented in production-inventory.md). Now 60-ish — pure
configuration + a 4-line facade for each public function.
"""

from __future__ import annotations

from typing import Optional

from phoenix_commons.updater import (
    UpdateInfo,
    check_for_update as _commons_check_for_update,
    download_and_apply as _commons_download_and_apply,
)
from phoenix_commons.updater.installer import UpdatePackageError

from version import __version__

# ── Tool-specific configuration ─────────────────────────────────────────────
# These stay app-local: they encode Lab Layout Tool's GitHub identity
# + release-asset naming. Used by ``ui/main_window.py`` via
# ``updater.GITHUB_OWNER`` / ``updater.GITHUB_REPO`` attribute access
# (for the "Release Notes" link in the update-banner dialog).
GITHUB_OWNER   = "JustinGlave"
GITHUB_REPO    = "lab-layout-tool"
EXE_NAME       = "LabLayoutTool.exe"
ZIP_ASSET_NAME = "LabLayoutTool.zip"


def check_for_update() -> Optional[UpdateInfo]:
    """Query the GitHub Releases API for a newer ``lab-layout-tool`` release.

    Returns an :class:`UpdateInfo` if a newer tagged release exists with
    ``LabLayoutTool.zip`` attached, otherwise ``None``. Safe to call from
    a background thread — never raises (network failures are logged at
    DEBUG inside the commons implementation).
    """
    return _commons_check_for_update(
        owner=GITHUB_OWNER,
        repo=GITHUB_REPO,
        current_version=__version__,
        zip_asset_name=ZIP_ASSET_NAME,
    )


def download_and_apply(info: UpdateInfo, progress_callback=None) -> None:
    """Download the update zip, validate it, apply it, and restart.

    Phoenix CAD ships **full-folder** updater zips (exe + ``_internal/``),
    so we pass ``expected_internal=True`` (the commons default). See
    ADR-003 for the cross-tool asymmetry this preserves.

    ``progress_callback(bytes_done, total_bytes)`` is invoked during the
    download so the GUI can drive a progress bar. Pass ``None`` to skip.

    Raises :class:`RuntimeError` (or :class:`UpdatePackageError`, a
    subclass) on any failure so the caller can show an error dialog.
    On success the function calls ``sys.exit(0)`` — Windows takes it
    from there via a small batch/PowerShell wrapper that waits for this
    process to terminate, replaces the install files, and relaunches.
    """
    _commons_download_and_apply(
        info,
        EXE_NAME,
        expected_internal=True,
        progress_callback=progress_callback,
    )


__all__ = [
    # Tool-specific configuration (referenced by ui/main_window.py via
    # updater.GITHUB_OWNER / .GITHUB_REPO for the release-notes link).
    "GITHUB_OWNER", "GITHUB_REPO", "EXE_NAME", "ZIP_ASSET_NAME",
    # Public dataclass + exception (re-exported from commons so
    # `from updater import UpdateInfo, UpdatePackageError` keeps working).
    "UpdateInfo", "UpdatePackageError",
    # Public entry points.
    "check_for_update", "download_and_apply",
]
