#!/usr/bin/env python3
from pathlib import Path
import sys
if len(sys.argv)!=2: raise SystemExit('usage: fix_manifest.py <source-root>')
path=Path(sys.argv[1]).resolve()/'internal/installer/builtin.go'
text=path.read_text(encoding='utf-8')
old='VersionSpec{{Version: "ubuntu-24.04", Default: true, Repository: "ubuntu"}}'
new='VersionSpec{{Version: "ubuntu-24.04", Default: true}}'
if old not in text: raise SystemExit('Redis version repository marker not found')
text=text.replace(old,new,1)
old_action='{ID: "secure-redis", Action: "config.write", Params: map[string]string{"managed": "redis-secure-defaults"}}'
new_action='{ID: "secure-redis", Action: "file.template", Params: map[string]string{"managed": "redis-secure-defaults"}}'
if old_action not in text: raise SystemExit('Redis secure-default action marker not found')
text=text.replace(old_action,new_action,1)
path.write_text(text,encoding='utf-8')
print('Normalized Redis manifest for distro package and existing operation vocabulary')
