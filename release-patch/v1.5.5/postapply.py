#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: postapply.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()
path = root / "internal/helper/filesystem_linux_test.go"
text = path.read_text(encoding="utf-8")
if '"strconv"' not in text:
    marker = '"path/filepath"\n'
    if marker not in text:
        raise SystemExit("test import marker not found")
    text = text.replace(marker, marker + '\t"strconv"\n', 1)
path.write_text(text, encoding="utf-8")
print("Added V1.5.5 metadata test strconv import")
