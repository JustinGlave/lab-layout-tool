# legacy/ — pre-retrofit safety archive

Files in this directory are **NOT** loaded at runtime. They exist as
known-good fallbacks if a regression is discovered post-merge of a
commons retrofit.

Per `commons/docs/ui-platform-baseline-v1/MIGRATION_RULES.md` §
"Local backup QSS strategy", these files are removed in a follow-up
PR ~30 days after the retrofit ships (assuming no regressions surface).

## Contents

| File | Origin | Removal target |
|------|--------|----------------|
| `phoenix_style.qss.preretrofit` | The repo-root `phoenix_style.qss` shipped with Lab Layout Tool through v0.1.1, copied unchanged when the Phase 3A commons retrofit landed. Byte-identical (after CRLF/LF normalization) to `commons/src/phoenix_commons/theme/phoenix_style.qss` at the pinned commons SHA. | ~30 days after Phase 3A merges (per MIGRATION_RULES.md). |

## Do not edit

Files here are immutable snapshots. Edits would defeat the
"known-good fallback" purpose. If you need to modify the canonical
QSS, edit `commons/src/phoenix_commons/theme/phoenix_style.qss`
(through a commons PR) and re-pin the submodule.
