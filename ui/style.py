"""Phoenix design-system loader — Phase 3A retrofit.

Pre-retrofit: this file was ~800 lines — `_resource_path` helper,
`apply_dark_theme` (loading `phoenix_style.qss` from the resource path
with a hand-maintained `_EMBEDDED_QSS` fallback), and the full
`_EMBEDDED_QSS` body that `tools/embed_qss.py` kept in sync with
`phoenix_style.qss`.

Post-retrofit: ~25 lines.

* ``apply_dark_theme`` re-exported from
  :mod:`phoenix_commons.theme`. Commons owns the QSS file + the
  generated embedded fallback + the brand-profile sentinel
  substitution (ADR-016). Phoenix CAD passes no ``brand=`` kwarg,
  so the default brand profile (canonical Phoenix red + deep blue +
  blue) is used — visually identical to pre-retrofit.
* ``_resource_path`` stays app-local. It resolves Phoenix-CAD-specific
  assets (``LLT_Normal.ico``, ``LLT_Transparent.png``) — commons has no
  business knowing about per-app brand assets. Two existing callers in
  ``ui/main_window.py`` continue to work unchanged.

The local ``phoenix_style.qss`` at the repo root is no longer consulted
at runtime (commons resolves its own QSS through importlib.resources).
A copy is retained at ``legacy/phoenix_style.qss.preretrofit`` per
``MIGRATION_RULES.md`` § Local backup QSS strategy for ~30 days after
the retrofit ships; the build pipeline stops bundling it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from phoenix_commons.theme import apply_dark_theme


def _resource_path(filename: str) -> str:
    """Resolve an app-local resource path (works in dev + PyInstaller).

    For Phoenix-CAD-specific assets like ``LLT_Normal.ico`` and
    ``LLT_Transparent.png``. Commons resources are loaded by
    :func:`phoenix_commons.theme.apply_dark_theme` internally — callers
    must not use this helper to resolve commons-owned files.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", ""))
    else:
        base = Path(__file__).resolve().parent.parent
    return str(base / filename)


__all__ = ["apply_dark_theme", "_resource_path"]
