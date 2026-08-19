#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: postapply.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()

# Finalize recycle metadata variable placement.
path = root / "internal/helper/filesystem_linux.go"
text = path.read_text(encoding="utf-8")
var_line = 'var filesystemRecycleMetadataDir = "/var/lib/hyzorax-control/recycle-bin"'
text = text.replace('\tmaxDeleteEntries      = 5000\n\n' + var_line + '\n\tmaxFilesystemPath', '\tmaxDeleteEntries      = 5000\n\tmaxFilesystemPath', 1)
if var_line not in text:
    marker = ')\n\ntype filesystemEntry struct {'
    if marker not in text:
        raise SystemExit("const block end marker not found")
    text = text.replace(marker, ')\n\n' + var_line + '\n\ntype filesystemEntry struct {', 1)
elif text.find(var_line) < text.find(')\n\ntype filesystemEntry struct {'):
    text = text.replace(var_line + '\n', '', 1)
    marker = ')\n\ntype filesystemEntry struct {'
    if marker not in text:
        raise SystemExit("const block end marker not found")
    text = text.replace(marker, ')\n\n' + var_line + '\n\ntype filesystemEntry struct {', 1)
path.write_text(text, encoding="utf-8")

# V1.5.2 HTTP API regression fake recognized permanent filesystem.delete.
# V1.5.3 intentionally keeps the browser endpoint but routes it to
# filesystem.trash, so accept both helper actions in the existing fake.
test_path = root / "internal/httpapi/files_test.go"
test_text = test_path.read_text(encoding="utf-8")
if 'case "filesystem.delete", "filesystem.trash":' not in test_text:
    old = 'case "filesystem.delete":'
    if old not in test_text:
        raise SystemExit("filesystem delete fake marker not found")
    test_text = test_text.replace(old, 'case "filesystem.delete", "filesystem.trash":', 1)
test_path.write_text(test_text, encoding="utf-8")

print("Finalized V1.5.3 recycle metadata placement and trash API test compatibility")
