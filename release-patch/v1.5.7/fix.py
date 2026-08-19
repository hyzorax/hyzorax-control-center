#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: fix.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()
path = root / "internal/web/static/app.js"
text = path.read_text(encoding="utf-8")
end_marker = 'finally{setBusy(form,false)}});'
delete_marker = '$("#delete-form").addEventListener'
start = text.find(end_marker)
if start < 0:
    raise SystemExit("new editor save-handler end marker not found")
start += len(end_marker)
end = text.find(delete_marker, start)
if end < 0:
    raise SystemExit("delete-handler boundary not found")
# V1.5.6 placed no required behavior between the text-editor submit handler
# and the delete submit handler. Any bytes here are residue from a partial
# regex replacement and must not survive into the shipped JavaScript.
text = text[:start] + "\n" + text[end:]
path.write_text(text, encoding="utf-8")
print("Normalized V1.5.7 editor save-handler boundary")
