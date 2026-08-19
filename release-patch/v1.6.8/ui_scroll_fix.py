#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: ui_scroll_fix.py <hyzorax-control-source-root>")

root = Path(sys.argv[1]).resolve()
css_path = root / "internal/web/static/app.css"
if not css_path.is_file():
    raise SystemExit(f"missing source file: {css_path}")

css = css_path.read_text(encoding="utf-8")
old_tree = ".editor-tree{min-width:0;display:flex;flex-direction:column;border-right:1px solid var(--line);background:#f8fbff}"
new_tree = ".editor-tree{min-width:0;min-height:0;overflow:hidden;display:flex;flex-direction:column;border-right:1px solid var(--line);background:#f8fbff}"
if old_tree not in css:
    raise SystemExit("editor-tree CSS marker not found")
css = css.replace(old_tree, new_tree, 1)
old_content = ".editor-tree-content{flex:1 1 auto;min-height:0;overflow:auto;padding:.35rem 0}"
new_content = ".editor-tree-content{flex:1 1 0;min-height:0;overflow-x:auto;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;scrollbar-width:thin;padding:.35rem 0}"
if old_content not in css:
    raise SystemExit("editor-tree-content CSS marker not found")
css = css.replace(old_content, new_content, 1)
css += "\n/* V1.6.8 editor tree scrollbar visibility */\n.editor-tree-content::-webkit-scrollbar{width:10px;height:10px}.editor-tree-content::-webkit-scrollbar-thumb{background:rgba(92,119,151,.42);border:2px solid transparent;border-radius:999px;background-clip:padding-box}.editor-tree-content::-webkit-scrollbar-track{background:transparent}\n"
css_path.write_text(css, encoding="utf-8")
print("Applied editor tree vertical/horizontal scroll containment fix")
