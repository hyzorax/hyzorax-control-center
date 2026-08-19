#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: preapply.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()
path = root / "internal/helper/filesystem_linux.go"
text = path.read_text(encoding="utf-8")
needle = 'strings.HasPrefix(directoryEntry.Name(), ".hyzorax-trash-")'
if needle not in text:
    old = '''\tfor _, directoryEntry := range directoryEntries {\n\t\tif err := ctx.Err(); err != nil {\n\t\t\treturn nil, &Error{Code: "operation_timeout", Message: "filesystem request timed out"}\n\t\t}\n\t\tinfo, infoError := directoryEntry.Info()'''
    new = '''\tfor _, directoryEntry := range directoryEntries {\n\t\tif err := ctx.Err(); err != nil {\n\t\t\treturn nil, &Error{Code: "operation_timeout", Message: "filesystem request timed out"}\n\t\t}\n\t\tif strings.HasPrefix(directoryEntry.Name(), ".hyzorax-trash-") {\n\t\t\tcontinue\n\t\t}\n\t\tinfo, infoError := directoryEntry.Info()'''
    if old not in text:
        raise SystemExit("filesystem list marker not found")
    text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
print("Prepared V1.5.3 recycle staging filter")
