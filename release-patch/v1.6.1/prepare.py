#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: prepare.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()
path = root / "internal/installer/manifest.go"
text = path.read_text(encoding="utf-8")
pattern = re.compile(r'var allowedCheckKinds = map\[string\]struct\{\}\{\n(?:\t[^\n]*\n)+?\}', re.MULTILINE)
match = pattern.search(text)
if not match:
    raise SystemExit("allowedCheckKinds block not found")
normalized = '''var allowedCheckKinds = map[string]struct{}{
\t"arch":            {},
\t"disk":            {},
\t"memory":          {},
\t"os":              {},
\t"package_absent":  {},
\t"path_writable":   {},
\t"port_free":       {},
\t"service_absent":  {},
}'''
path.write_text(text[:match.start()] + normalized + text[match.end():], encoding="utf-8")
print("Normalized Installer Engine check vocabulary for V1.6.1 patch")
