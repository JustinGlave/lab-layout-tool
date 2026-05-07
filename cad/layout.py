"""Layout data classes + config loader.

Actual placement is dynamic — the bricscad driver inserts each block, reads its
bounding box via COM, then advances the cursor by that block's width before
inserting the next one. So this module owns the data shape (Placement,
LayoutSpec) and the config parsing; it does not pre-compute (x, y).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Placement:
    category: str            # SAV, GEX, FEV, AUX
    variant_id: str          # filename stem of the DWG block
    dwg_path: str            # absolute path
    tag: str = ""            # reserved for future user-input labels
    # Populated during insertion — bbox-bottom-left + bbox dimensions:
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    # True when this placement is in a R→L (reversed) row. Wire endpoints are
    # swapped — the IN port serves as the outgoing-wire endpoint and the OUT
    # port as the incoming-wire endpoint. Block geometry itself is not mirrored.
    is_reversed: bool = False
    # Index (0-based) of the template page this placement lives on.
    page_idx: int = 0


@dataclass
class LayoutSpec:
    anchor_x: float          # X of the bbox bottom-left of the very first valve
    anchor_y: float          # Y of the bbox bottom-left of the very first valve (page 1, row 1)
    h_gap: float             # gap between adjacent blocks horizontally (inches)
    v_gap: float             # gap between wrapped rows vertically (inches)
    max_row_width: float     # wrap when next block would exceed anchor_x + this
    row_order: list[str]     # category order: SAV → GEX → FEV → AUX
    page_height: float = 951.0   # Y delta between page anchors (page 2 anchor = anchor_y - page_height)
    page_count: int = 4          # max pages template provides
    rows_per_page: int = 2       # rows per page before jumping to next page


@dataclass
class PageSpec:
    width: float
    height: float


def flatten_job(job: dict) -> list[Placement]:
    """Convert a single-room dict (with SAV/GEX/FEV/AUX keys) into Placements."""
    out: list[Placement] = []
    for cat in ("SAV", "GEX", "FEV", "AUX"):
        for entry in job.get(cat, []):
            out.append(
                Placement(
                    category=cat,
                    variant_id=entry["variant_id"],
                    dwg_path=entry["dwg_path"],
                    tag=entry.get("tag", ""),
                )
            )
    return out


def page_from_config(cfg: dict) -> PageSpec:
    p = cfg["page"]
    return PageSpec(width=p["width"], height=p["height"])


def layout_from_config(cfg: dict) -> LayoutSpec:
    L = cfg["layout"]
    P = cfg.get("page", {})
    return LayoutSpec(
        anchor_x=float(L["anchor_x"]),
        anchor_y=float(L["anchor_y"]),
        h_gap=float(L["h_gap"]),
        v_gap=float(L["v_gap"]),
        max_row_width=float(L.get("max_row_width", 1500.0)),
        row_order=list(L.get("row_order", ["SAV", "GEX", "FEV", "AUX"])),
        page_height=float(P.get("page_height", 951.0)),
        page_count=int(P.get("page_count", 4)),
        rows_per_page=int(P.get("rows_per_page", 2)),
    )


def assign_tags(
    placements: list[Placement],
    prefixes: dict[str, str] | None = None,
) -> None:
    """Reserved for future user-input labeling. Currently unused."""
    prefixes = prefixes or {}
    counters: dict[str, int] = {}
    for p in placements:
        prefix = prefixes.get(p.category, p.category)
        n = counters.get(prefix, 0) + 1
        counters[prefix] = n
        p.tag = f"{prefix}-{n}"
