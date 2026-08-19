#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: fix.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()
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
# V1.5.6 placed no required behavior between the text-editor submit handler
# and the delete submit handler. Restrict cleanup to the editor handler so
# unrelated form handlers and editor workspace functions remain untouched.
text = text[:start] + "\n" + text[end:]
path.write_text(text, encoding="utf-8")
print("Normalized V1.5.7 editor save-handler boundary")
