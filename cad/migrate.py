"""Project JSON schema migration.

Loaded projects can pre-date the current schema. Centralised here so the
loader doesn't need to know the version history; it just calls
`migrate_project(data)` and gets back a dict in the latest shape.

Schema versions:
  v1 (implicit, pre-2026-05-06): single-room — top-level `name`, `SAV`,
      `GEX`, `FEV`, `AUX`, `product_line`. No `rooms` key.
  v2 (2026-05-06): multi-room — top-level `job_name`, `job_number`,
      `technician`, `date`, `product_line`, `rooms[]`. Each room has
      `name`, the four valve categories, and `pbcs[]`.

`schema_version` was added with v2 (writes set it to `2`). Older v1 files
don't have it; we detect them by absence of `rooms`.

If a future schema bumps to v3, append a branch in `migrate_project`
that reads v2-shaped data and produces v3 — keep migrations chained so
arbitrarily-old projects can still load.
"""

from __future__ import annotations

from .blocks import CATEGORIES

CURRENT_SCHEMA_VERSION = 2


def migrate_project(data: dict) -> dict:
    """Return `data` upgraded to the current schema, leaving an already-current
    dict untouched. Pure-function-ish: returns a possibly-new dict but doesn't
    mutate the input shape past what's required.
    """
    if "rooms" not in data:
        data = _v1_to_v2(data)
    # Future: if data.get("schema_version", 1) < N: data = _vN_minus_1_to_vN(data)
    data.setdefault("schema_version", CURRENT_SCHEMA_VERSION)
    return data


def _v1_to_v2(v1: dict) -> dict:
    """Wrap a v1 single-room project into the v2 multi-room shape.

    v1 had `name`, `SAV/GEX/FEV/AUX`, `product_line` at the top level.
    v2 promotes those into a single-element `rooms[]` list and adds
    project-level metadata fields (job_name, job_number, technician,
    date) — all empty since v1 didn't carry them.
    """
    room: dict = {"name": v1.get("name", "LAB 001")}
    for cat in CATEGORIES:
        room[cat] = v1.get(cat, [])
    return {
        "job_name": v1.get("name", ""),
        "job_number": "",
        "technician": "",
        "date": "",
        "product_line": v1.get("product_line"),
        "rooms": [room],
    }
