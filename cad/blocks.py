"""Block library lookup.

Convention: blocks live under blocks/<product_line>/<CATEGORY>/<NAME>.dwg
Filename without extension is the variant id shown in the configuration dropdown.
For SAV/GEX/FEV the convention is `{TYPE}_{CONFIG}.dwg` — CONFIG is the valve
configuration (single, dual, triple, etc.), e.g. SAV_single.dwg = single supply valve.
For AUX it's a free-form name (e.g. drawdown_bench.dwg, gas_cabinet.dwg, snorkel.dwg).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "product_lines.json"

# Canonical valve categories, in iteration order (matches the DWG library
# layout, the form's row_order default, and the JSON schema's per-room keys).
# Imported across the codebase so adding/removing a category is a one-place
# edit. Order also matters for flatten_job(), which determines the wire-chain
# sequence within a room.
CATEGORIES: tuple[str, ...] = ("SAV", "GEX", "FEV", "AUX")

# Map category key -> on-disk directory name. Only categories whose key would
# clash with a Windows reserved device name (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
# need an entry here. Keep the in-memory key short ("AUX") for backwards-compat
# with existing JSON fixtures and code, but store the DWGs under a safe name.
_CATEGORY_DIRNAME = {
    "AUX": "AUXILIARY",
}


def _category_dirname(category: str) -> str:
    return _CATEGORY_DIRNAME.get(category, category)


@dataclass(frozen=True)
class BlockVariant:
    variant_id: str          # filename stem, e.g. "SAV_8"
    label: str               # human label for dropdown, e.g. "8\""
    dwg_path: Path           # absolute path to the .dwg

    def exists(self) -> bool:
        return self.dwg_path.is_file()


@dataclass(frozen=True)
class ProductLine:
    id: str
    display_name: str
    blocks_dir: Path


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def product_lines() -> list[ProductLine]:
    cfg = load_config()
    return [
        ProductLine(
            id=p["id"],
            display_name=p["display_name"],
            blocks_dir=PROJECT_ROOT / p["blocks_dir"],
        )
        for p in cfg["product_lines"]
    ]


def resolve_block_path(
    product_line: ProductLine, category: str, variant_id: str
) -> Path:
    """Construct the absolute DWG path for a (product_line, category,
    variant_id) triple. Lets project files ship without embedding absolute
    paths — the loader can fill them in at load time."""
    return (
        product_line.blocks_dir
        / _category_dirname(category)
        / f"{variant_id}.dwg"
    ).resolve()


def list_variants(product_line: ProductLine, category: str) -> list[BlockVariant]:
    """Return DWG variants in <product_line>/<category>/ sorted by size if parseable."""
    cat_dir = product_line.blocks_dir / _category_dirname(category)
    if not cat_dir.is_dir():
        return []

    variants: list[BlockVariant] = []
    for dwg in sorted(cat_dir.glob("*.dwg")):
        variants.append(
            BlockVariant(
                variant_id=dwg.stem,
                label=_label_for(dwg.stem, category),
                dwg_path=dwg.resolve(),
            )
        )
    variants.sort(key=lambda v: _sort_key(v.variant_id, category))
    return variants


_CONFIG_ORDER = {
    # Lower number → earlier in the dropdown. Anything not listed sorts after.
    "single": 1,
    "dual":   2,
    "double": 2,   # alias — CSCP files use DOUBLE
}

# Sub-rank inside the same Single/Double config. Lower = earlier.
# Used to order SAV variants like:
#   SAV_SINGLE_PBC_ACM_START  → Single, PBC ACM Start
#   SAV_SINGLE_ACM_START      → Single, ACM Start
#   SAV_SINGLE_ACM            → Single, ACM
#   SAV_DOUBLE_PBC_ACM_START  → Double, PBC ACM Start
#   …
_SAV_SUB_ORDER = [
    "PBC_ACM_START",
    "ACM_START",
    "ACM",
]


def _label_for(stem: str, category: str) -> str:
    """Human label for the dropdown — Title Case with spaces."""
    if category == "AUX":
        # drawdown_bench → "Drawdown Bench"
        return stem.replace("_", " ").title()

    # {TYPE}_{CONFIG}[_extra] → config + extras as title case
    m = re.match(r"^[A-Za-z]+_(.+)$", stem)
    if not m:
        return stem
    rest = m.group(1)
    # Special-case PBC and ACM — keep them upper-case for readability
    pretty = rest.replace("_", " ").title()
    pretty = pretty.replace("Pbc", "PBC").replace("Acm", "ACM")
    return pretty


def _sort_key(stem: str, category: str):
    if category == "AUX":
        # AUX names look like {FAMILY}_{CONFIG} (e.g. CAGE_SINGLE).
        parts = stem.rsplit("_", 1)
        if len(parts) == 2 and parts[1].lower() in _CONFIG_ORDER:
            family = parts[0].lower()
            cfg = parts[1].lower()
            return (0, family, _CONFIG_ORDER[cfg], cfg)
        return (1, stem.lower())

    # Other categories: {TYPE}_{CONFIG}[_extra]
    m = re.match(r"^[A-Za-z]+_([A-Za-z]+)(?:_(.+))?$", stem)
    if not m:
        return (99, stem.lower())
    config_word = m.group(1).lower()
    extras = (m.group(2) or "").upper()
    config_rank = _CONFIG_ORDER.get(config_word, 99)
    # Within the same config (e.g. all SINGLE rows), order by SAV sub-rank.
    sub_rank = next(
        (i for i, key in enumerate(_SAV_SUB_ORDER) if key == extras),
        len(_SAV_SUB_ORDER),
    )
    return (config_rank, sub_rank, extras)
