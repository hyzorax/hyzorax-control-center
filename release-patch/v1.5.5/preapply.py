#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: preapply.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()
path = root / "internal/web/static/index.html"
text = path.read_text(encoding="utf-8")
marker = '<dialog id="confirmation-dialog"'
if marker not in text:
    raise SystemExit("V1.5.4 confirmation dialog not found")
# V1.5.5 apply.py uses a stable indentation marker. Normalize only the first
# occurrence; this does not change rendered HTML semantics.
idx = text.index(marker)
line_start = text.rfind("\n", 0, idx) + 1
indent = text[line_start:idx]
if indent != "    ":
    text = text[:line_start] + "    " + text[idx:]
path.write_text(text, encoding="utf-8")
print("Normalized V1.5.4 confirmation dialog marker")
