#!/usr/bin/env python3
from pathlib import Path
import sys
if len(sys.argv)!=2: raise SystemExit('usage: fix_manifest.py <source-root>')
path=Path(sys.argv[1]).resolve()/'internal/installer/builtin.go'
text=path.read_text(encoding='utf-8')
old='VersionSpec{{Version: "ubuntu-24.04", Default: true, Repository: "ubuntu"}}'
new='VersionSpec{{Version: "ubuntu-24.04", Default: true}}'
if old not in text: raise SystemExit('Redis version repository marker not found')
path.write_text(text.replace(old,new,1),encoding='utf-8')
print('Fixed Redis distro manifest repository field')
