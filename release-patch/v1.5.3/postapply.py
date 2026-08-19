#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: postapply.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()
path = root / "internal/helper/filesystem_linux.go"
text = path.read_text(encoding="utf-8")
var_line = 'var filesystemRecycleMetadataDir = "/var/lib/hyzorax-control/recycle-bin"'
# The main patch initially inserts the variable after maxDeleteEntries; move it
# outside the const block before gofmt/compile.
text = text.replace('\tmaxDeleteEntries      = 5000\n\n' + var_line + '\n\tmaxFilesystemPath', '\tmaxDeleteEntries      = 5000\n\tmaxFilesystemPath', 1)
if var_line not in text:
    marker = ')\n\ntype filesystemEntry struct {'
    if marker not in text:
        raise SystemExit("const block end marker not found")
    text = text.replace(marker, ')\n\n' + var_line + '\n\ntype filesystemEntry struct {', 1)
elif text.find(var_line) < text.find(')\n\ntype filesystemEntry struct {'):
    # Defensive fallback if formatting differs: remove and reinsert after const.
    text = text.replace(var_line + '\n', '', 1)
    marker = ')\n\ntype filesystemEntry struct {'
    text = text.replace(marker, ')\n\n' + var_line + '\n\ntype filesystemEntry struct {', 1)
path.write_text(text, encoding="utf-8")
print("Finalized V1.5.3 recycle metadata variable placement")
