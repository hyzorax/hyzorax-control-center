#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: testfix.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()

for rel in ("internal/web/assets_test.go", "internal/httpapi/app_test.go"):
    path = root / rel
    text = path.read_text(encoding="utf-8")
    text = text.replace("Version 1.5.5", "Version 1.5.6")
    path.write_text(text, encoding="utf-8")

assets = root / "internal/web/assets_test.go"
text = assets.read_text(encoding="utf-8")
text, count = re.subn(r'\nfunc TestV156EditorWorkflowAssets\(t \*testing\.T\) \{.*?\n\}\n?', '\n', text, flags=re.S)
if count != 1:
    raise SystemExit(f"expected to remove one temporary V1.5.6 asset test, removed {count}")
assets.write_text(text, encoding="utf-8")
print("Normalized V1.5.6 regression test expectations")
