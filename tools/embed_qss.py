"""embed_qss.py — sync ui/style.py:_EMBEDDED_QSS from phoenix_style.qss.

The runtime loads phoenix_style.qss from the resource path; if that file is
missing (rare auto-update edge case), it falls back to the embedded string
in ui/style.py. The embed is only a safety net — but if it drifts from the
source QSS, the fallback gives stale styling.

Run this whenever phoenix_style.qss changes:

    .venv/Scripts/python tools/embed_qss.py

...or wire it into build.bat as a pre-PyInstaller step. The script rewrites
ui/style.py in place, replacing the body of the existing _EMBEDDED_QSS
triple-quoted literal with the verbatim contents of phoenix_style.qss. No
QSS-aware parsing — just a string substitution between two well-known
markers (the `_EMBEDDED_QSS = ` opener and the matching closing quotes).

Exit codes:
  0  ui/style.py already in sync; no write needed.
  1  ui/style.py was rewritten.
  2  Markers missing from ui/style.py — manual fix needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QSS_PATH = PROJECT_ROOT / "phoenix_style.qss"
STYLE_PY = PROJECT_ROOT / "ui" / "style.py"

# Sentinel markers — must already exist around the embed in ui/style.py.
START_MARKER = '_EMBEDDED_QSS = """'
END_MARKER = '"""'


def main() -> int:
    if not QSS_PATH.is_file():
        print(f"ERROR: {QSS_PATH} does not exist.", file=sys.stderr)
        return 2
    if not STYLE_PY.is_file():
        print(f"ERROR: {STYLE_PY} does not exist.", file=sys.stderr)
        return 2

    qss = QSS_PATH.read_text(encoding="utf-8")
    style_src = STYLE_PY.read_text(encoding="utf-8")

    start = style_src.find(START_MARKER)
    if start < 0:
        print(
            f"ERROR: '{START_MARKER}' not found in {STYLE_PY}. "
            f"Has the embed marker been removed or renamed?",
            file=sys.stderr,
        )
        return 2
    body_start = start + len(START_MARKER)
    end = style_src.find(END_MARKER, body_start)
    if end < 0:
        print(
            f"ERROR: closing '\"\"\"' not found after embed start in {STYLE_PY}.",
            file=sys.stderr,
        )
        return 2

    # The embed body may have triple quotes inside it (rare, but a QSS
    # selector containing `"""` would break). Detect this so we don't
    # silently produce broken Python.
    if '"""' in qss:
        print(
            "ERROR: phoenix_style.qss contains a triple-quote sequence which "
            "can't be embedded as a Python triple-quoted string. Edit the "
            "QSS to avoid this, or change the embed mechanism.",
            file=sys.stderr,
        )
        return 2

    # Build the new style.py: prefix + start marker + newline + raw QSS +
    # end marker + suffix. Existing newlines around the markers are preserved
    # because we splice from inside-the-quotes to inside-the-quotes.
    new_body = "\n" + qss + ("" if qss.endswith("\n") else "\n")
    new_src = style_src[:body_start] + new_body + style_src[end:]

    if new_src == style_src:
        print(f"_EMBEDDED_QSS already in sync with phoenix_style.qss "
              f"({len(qss):,} chars).")
        return 0

    STYLE_PY.write_text(new_src, encoding="utf-8")
    print(f"Updated {STYLE_PY.relative_to(PROJECT_ROOT)} — embedded "
          f"{len(qss):,} chars from {QSS_PATH.relative_to(PROJECT_ROOT)}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
