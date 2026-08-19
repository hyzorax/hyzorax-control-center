#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: post_refine.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()
path = root / "internal/web/static/app.js"
text = path.read_text(encoding="utf-8")
old = 'loadEditorDirectory(editorParentDirectory(state.editorTreePath+"/placeholder"))'
new = 'loadEditorDirectory(editorParentDirectory(state.editorTreePath))'
if old not in text:
    raise SystemExit("editor parent navigation marker not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Fixed V1.6.9 editor parent-directory navigation")
