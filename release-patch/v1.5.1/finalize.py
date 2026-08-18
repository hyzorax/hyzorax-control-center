#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: finalize.py <hyzorax-control-source-root>")

root = Path(sys.argv[1]).resolve()
index_html = root / "internal/web/static/index.html"
app_js = root / "internal/web/static/app.js"
app_test = root / "internal/httpapi/app_test.go"
assets_test = root / "internal/web/assets_test.go"

html = index_html.read_text(encoding="utf-8")
for old, new in (
    ('<p class="eyebrow">Rename</p><h3>Rename item</h3>', '<p class="eyebrow">Guarded rename</p><h3>Rename item</h3>'),
    ('<p class="eyebrow">Copy</p><h3>Copy item</h3>', '<p class="eyebrow">Guarded copy</p><h3>Copy item</h3>'),
    ('<p class="eyebrow">Move</p><h3>Move item</h3>', '<p class="eyebrow">Guarded move</p><h3>Move item</h3>'),
    ('Same directory · existing paths are never overwritten.', 'Same directory · Existing paths are never overwritten.'),
    ('Atomic same-filesystem move · existing paths are never overwritten.', 'Atomic same-filesystem move · no overwrite · Cross-filesystem moves are blocked.'),
):
    if old not in html:
        raise SystemExit(f"missing UI marker: {old}")
    html = html.replace(old, new, 1)
index_html.write_text(html, encoding="utf-8")

js = app_js.read_text(encoding="utf-8")
replacements = (
    ('download.setAttribute("role", "menuitem");\ndownload.textContent = "Download";', 'download.className = "download-link";\ndownload.setAttribute("role", "menuitem");\ndownload.textContent = "Download";'),
    ('if (entry.editable) appendFileAction(menu, "Edit", () => openEditor(entry.path));', 'if (entry.editable) appendFileAction(menu, "Edit", () => openEditor(entry.path), "edit-link");'),
    ('if (entry.renamable) appendFileAction(menu, "Rename", () => openRename(entry));', 'if (entry.renamable) appendFileAction(menu, "Rename", () => openRename(entry), "rename-link");'),
    ('if (entry.copyable) appendFileAction(menu, "Copy", () => openCopy(entry));', 'if (entry.copyable) appendFileAction(menu, "Copy", () => openCopy(entry), "copy-link");'),
    ('if (entry.movable) appendFileAction(menu, "Move", () => openMove(entry));', 'if (entry.movable) appendFileAction(menu, "Move", () => openMove(entry), "move-link");'),
)
for old, new in replacements:
    if old not in js:
        raise SystemExit(f"missing JS compatibility marker: {old}")
    js = js.replace(old, new, 1)
app_js.write_text(js, encoding="utf-8")

for test_path in (app_test, assets_test):
    text = test_path.read_text(encoding="utf-8")
    if "Version 1.5.0" not in text:
        raise SystemExit(f"missing V1.5.0 test marker in {test_path}")
    text = text.replace("Version 1.5.0", "Version 1.5.1")
    test_path.write_text(text, encoding="utf-8")

print("Finalized V1.5.1 UI labels, security hints, legacy action semantics, and version regression tests")
