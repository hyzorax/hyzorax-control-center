#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: fix.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()

# Normalize editor save-handler boundary after the V1.5.6 source transform.
path = root / "internal/web/static/app.js"
text = path.read_text(encoding="utf-8")
form_marker = '$("#editor-form").addEventListener("submit",async(event)=>'
end_marker = 'finally{setBusy(form,false)}});'
delete_marker = '$("#delete-form").addEventListener'
form_start = text.find(form_marker)
if form_start < 0:
    raise SystemExit("new editor form handler marker not found")
start = text.find(end_marker, form_start)
if start < 0:
    raise SystemExit("new editor save-handler end marker not found")
start += len(end_marker)
end = text.find(delete_marker, start)
if end < 0:
    raise SystemExit("delete-handler boundary not found")
text = text[:start] + "\n" + text[end:]
path.write_text(text, encoding="utf-8")

# Fresh initialization no longer exposes or consumes a generated password.
main_path = root / "cmd/hyzorax-control/main.go"
main = main_path.read_text(encoding="utf-8")
old = 'created, username, password, err := initializeOwner(*configPath)'
new = 'created, username, _, err := initializeOwner(*configPath)'
if old not in main:
    raise SystemExit("Owner initializer variable marker not found")
main_path.write_text(main.replace(old, new, 1), encoding="utf-8")

# Normalize every embedded interface version marker, including the sidebar
# footer carried forward by older File Manager release patches.
index_path = root / "internal/web/static/index.html"
index = index_path.read_text(encoding="utf-8")
index = re.sub(r'Version 1\.5\.[0-6]', 'Version 1.5.7', index)
index = re.sub(r'>1\.5\.[0-6]<', '>1.5.7<', index)
index_path.write_text(index, encoding="utf-8")

# Keep embedded-interface regression test aligned with the shipped release.
assets_path = root / "internal/web/assets_test.go"
assets = assets_path.read_text(encoding="utf-8")
assets = re.sub(r'1\.5\.[0-6]', '1.5.7', assets)
assets_path.write_text(assets, encoding="utf-8")

print("Normalized V1.5.7 editor boundary, CLI initializer and all interface version markers")
