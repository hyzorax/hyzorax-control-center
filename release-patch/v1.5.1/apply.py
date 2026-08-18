#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply.py <hyzorax-control-source-root>")

root = Path(sys.argv[1]).resolve()
app_js = root / "internal/web/static/app.js"
app_css = root / "internal/web/static/app.css"
index_html = root / "internal/web/static/index.html"

for path in (app_js, app_css, index_html):
    if not path.is_file():
        raise SystemExit(f"missing source file: {path}")


def sub_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"unable to apply {label}: expected 1 match, got {count}")
    return updated


# ---------- app.js ----------
js = app_js.read_text(encoding="utf-8")

old_action_pattern = re.escape('const actionCell = document.createElement("td");') + r'.*?' + re.escape('actionCell.append(actionGroup);')
new_action_block = '''const actionCell = document.createElement("td");
actionCell.className = "file-action-cell";
actionCell.append(buildFileActionMenu(entry));'''
js = sub_once(js, old_action_pattern, new_action_block, "single file action menu")

menu_helpers = r'''function closeFileActionMenus() {
document.querySelectorAll(".file-action-menu").forEach((menu) => {
menu.hidden = true;
menu.style.removeProperty("left");
menu.style.removeProperty("top");
menu.style.removeProperty("right");
menu.style.removeProperty("bottom");
menu.style.removeProperty("visibility");
const trigger = menu.parentElement?.querySelector(".action-menu-trigger");
if (trigger) trigger.setAttribute("aria-expanded", "false");
});
document.body.classList.remove("file-action-menu-open");
}
function positionFileActionMenu(trigger, menu) {
menu.style.removeProperty("left");
menu.style.removeProperty("top");
menu.style.removeProperty("right");
menu.style.removeProperty("bottom");
menu.style.removeProperty("visibility");
if (window.matchMedia("(max-width: 680px)").matches) {
document.body.classList.add("file-action-menu-open");
return;
}
const padding = 8;
menu.style.visibility = "hidden";
const triggerRect = trigger.getBoundingClientRect();
const menuRect = menu.getBoundingClientRect();
let left = triggerRect.right - menuRect.width;
left = Math.max(padding, Math.min(left, window.innerWidth - menuRect.width - padding));
let top = triggerRect.bottom + 6;
if (top + menuRect.height > window.innerHeight - padding) {
top = Math.max(padding, triggerRect.top - menuRect.height - 6);
}
menu.style.left = `${left}px`;
menu.style.top = `${top}px`;
menu.style.visibility = "";
}
function appendFileAction(menu, label, handler, className = "") {
const button = document.createElement("button");
button.type = "button";
button.setAttribute("role", "menuitem");
button.textContent = label;
if (className) button.className = className;
button.addEventListener("click", handler);
menu.append(button);
}
function buildFileActionMenu(entry) {
const group = document.createElement("div");
group.className = "file-actions";
const menu = document.createElement("div");
menu.className = "file-action-menu";
menu.setAttribute("role", "menu");
menu.setAttribute("aria-label", `Actions for ${entry.name}`);
menu.hidden = true;
if (entry.kind === "directory") appendFileAction(menu, "Open", () => loadFiles(entry.path));
if (entry.downloadable) {
const download = document.createElement("a");
download.href = `api/v1/files/download?path=${encodeURIComponent(entry.path)}`;
download.setAttribute("role", "menuitem");
download.textContent = "Download";
menu.append(download);
}
if (entry.editable) appendFileAction(menu, "Edit", () => openEditor(entry.path));
if (entry.renamable) appendFileAction(menu, "Rename", () => openRename(entry));
if (entry.copyable) appendFileAction(menu, "Copy", () => openCopy(entry));
if (entry.movable) appendFileAction(menu, "Move", () => openMove(entry));
if (menu.childElementCount === 0) {
const unavailable = document.createElement("span");
unavailable.className = "file-unavailable";
unavailable.textContent = entry.kind === "file" ? "Over limit" : entry.kind === "symlink" ? "Symlink" : "Unavailable";
group.append(unavailable);
return group;
}
const trigger = document.createElement("button");
trigger.className = "action-menu-trigger";
trigger.type = "button";
trigger.textContent = "⋯";
trigger.title = `Actions for ${entry.name}`;
trigger.setAttribute("aria-label", `Actions for ${entry.name}`);
trigger.setAttribute("aria-haspopup", "menu");
trigger.setAttribute("aria-expanded", "false");
trigger.addEventListener("click", (event) => {
event.stopPropagation();
const shouldOpen = menu.hidden;
closeFileActionMenus();
if (!shouldOpen) return;
menu.hidden = false;
trigger.setAttribute("aria-expanded", "true");
positionFileActionMenu(trigger, menu);
});
menu.addEventListener("click", (event) => {
event.stopPropagation();
if (event.target.closest("button, a")) closeFileActionMenus();
});
group.append(trigger, menu);
return group;
}
document.addEventListener("click", closeFileActionMenus);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeFileActionMenus(); });
window.addEventListener("resize", closeFileActionMenus);
window.addEventListener("scroll", closeFileActionMenus, true);
'''

marker = 'function fileKindIcon(kind) {'
if marker not in js:
    raise SystemExit("unable to find fileKindIcon insertion point")
js = js.replace(marker, menu_helpers + marker, 1)
app_js.write_text(js, encoding="utf-8")

# ---------- index.html ----------
html = index_html.read_text(encoding="utf-8")
if "Version 1.5.0" not in html:
    raise SystemExit("expected Version 1.5.0 marker not found")
html = html.replace("Version 1.5.0", "Version 1.5.1", 1)
html = html.replace("<th>Action</th>", "<th>Actions</th>", 1)

rename_dialog = '''<dialog id="rename-dialog" class="modal operation-modal">
      <form id="rename-form" class="modal-card operation-card">
        <div class="operation-heading"><div><p class="eyebrow">Rename</p><h3>Rename item</h3></div><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        <p class="operation-source"><span>Current</span><code id="rename-source-path"></code></p>
        <label>New name<input id="rename-name-input" name="name" maxlength="255" autocomplete="off" required></label>
        <p class="operation-hint">Same directory · existing paths are never overwritten.</p>
        <div id="rename-error" class="alert" role="alert" hidden></div>
        <div class="modal-actions"><button type="button" class="ghost compact" data-close-dialog>Cancel</button><button type="submit" class="primary compact-primary">Rename</button></div>
      </form>
    </dialog>'''
copy_dialog = '''<dialog id="copy-dialog" class="modal operation-modal">
      <form id="copy-form" class="modal-card operation-card">
        <div class="operation-heading"><div><p class="eyebrow">Copy</p><h3>Copy item</h3></div><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        <p class="operation-source"><span>Item</span><code id="copy-source-path"></code></p>
        <label>Destination directory<input id="copy-destination-input" name="destination" maxlength="4096" autocomplete="off" required></label>
        <label>Copy name<input id="copy-name-input" name="name" maxlength="255" autocomplete="off" required></label>
        <p class="operation-hint">No overwrite · maximum 256 MB / 5,000 entries.</p>
        <div id="copy-error" class="alert" role="alert" hidden></div>
        <div class="modal-actions"><button type="button" class="ghost compact" data-close-dialog>Cancel</button><button type="submit" class="primary compact-primary">Copy</button></div>
      </form>
    </dialog>'''
move_dialog = '''<dialog id="move-dialog" class="modal operation-modal">
      <form id="move-form" class="modal-card operation-card">
        <div class="operation-heading"><div><p class="eyebrow">Move</p><h3>Move item</h3></div><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        <p class="operation-source"><span>Item</span><code id="move-source-path"></code></p>
        <label>Destination directory<input id="move-destination-input" maxlength="4096" autocomplete="off" required></label>
        <label>Name<input id="move-name-input" maxlength="255" autocomplete="off" required></label>
        <p class="operation-hint">Atomic same-filesystem move · existing paths are never overwritten.</p>
        <div id="move-error" class="alert" role="alert" hidden></div>
        <div class="modal-actions"><button type="button" class="ghost compact" data-close-dialog>Cancel</button><button type="submit" class="primary compact-primary">Move</button></div>
      </form>
    </dialog>'''

html = sub_once(html, r'<dialog id="rename-dialog" class="modal">.*?</dialog>', rename_dialog, "compact rename dialog")
html = sub_once(html, r'<dialog id="copy-dialog" class="modal">.*?</dialog>', copy_dialog, "compact copy dialog")
html = sub_once(html, r'<dialog id="move-dialog" class="modal">.*?</dialog>', move_dialog, "compact move dialog")
index_html.write_text(html, encoding="utf-8")

# ---------- app.css ----------
css = app_css.read_text(encoding="utf-8")
marker = "/* V1.5.1 compact File Manager actions + operation dialogs */"
if marker in css:
    raise SystemExit("V1.5.1 CSS already applied")
css += r'''

/* V1.5.1 compact File Manager actions + operation dialogs */
.file-table { min-width: 820px; }
.file-table th:last-child, .file-table td:last-child { width: 70px; padding-left: .55rem; padding-right: .55rem; }
.file-action-cell { position: relative; white-space: nowrap; }
.file-actions { position: relative; display: flex; align-items: center; justify-content: flex-start; flex-wrap: nowrap; gap: 0; }
.action-menu-trigger { width: 34px; height: 34px; display: grid; place-items: center; border: 1px solid var(--line-strong); border-radius: 9px; color: var(--blue-deep); background: rgba(255,255,255,.88); font-size: 1.08rem; font-weight: 900; line-height: 1; letter-spacing: .05em; }
.action-menu-trigger:hover, .action-menu-trigger[aria-expanded="true"] { border-color: rgba(48,129,234,.48); background: rgba(99,204,248,.16); box-shadow: 0 8px 20px rgba(48,129,234,.10); }
.file-action-menu { position: fixed; z-index: 60; min-width: 184px; display: grid; gap: .12rem; padding: .4rem; border: 1px solid var(--line-strong); border-radius: 12px; background: rgba(255,255,255,.99); box-shadow: 0 20px 55px rgba(16,42,77,.22); }
.file-action-menu[hidden] { display: none !important; }
.file-action-menu button, .file-action-menu a { width: 100%; display: flex; align-items: center; min-height: 36px; padding: .55rem .7rem; border: 0; border-radius: 8px; color: #31577f; background: transparent; text-decoration: none; text-align: left; font-size: .67rem; font-weight: 800; }
.file-action-menu button:hover, .file-action-menu a:hover { color: var(--blue-deep); background: rgba(99,204,248,.13); }
.operation-modal { width: min(92vw, 460px); }
.operation-card { gap: .78rem; padding: 1.15rem; }
.operation-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: .75rem; }
.operation-heading h3 { margin: 0; font-size: 1.08rem; }
.operation-heading .eyebrow { margin-bottom: .22rem; }
.operation-close { width: 32px; height: 32px; flex: 0 0 auto; border: 1px solid var(--line); border-radius: 9px; color: #6681a3; background: rgba(247,250,255,.92); font-size: 1.1rem; }
.operation-close:hover { color: var(--blue-deep); border-color: var(--line-strong); background: rgba(99,204,248,.12); }
.operation-source { display: grid; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: .55rem; margin: 0 !important; padding: .58rem .68rem; border: 1px solid var(--line); border-radius: 9px; background: #f7faff; }
.operation-source span { color: #8297b1; font-size: .58rem; font-weight: 850; text-transform: uppercase; letter-spacing: .08em; }
.operation-source code { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .66rem; }
.operation-card label { gap: .35rem; }
.operation-card input { padding: .72rem .8rem; }
.operation-hint { margin: -.05rem 0 0 !important; color: var(--muted); font-size: .62rem; line-height: 1.45; }
.operation-card .alert { margin-top: 0; }
.operation-card .modal-actions { margin-top: .1rem; }
.operation-card .modal-actions .primary { min-width: 92px; padding: .72rem .9rem; }

@media (max-width: 680px) {
  body.file-action-menu-open::after { content: ""; position: fixed; inset: 0; z-index: 55; background: rgba(16,42,77,.28); backdrop-filter: blur(2px); }
  .file-action-menu { left: 10px !important; right: 10px !important; top: auto !important; bottom: 10px !important; z-index: 60; width: auto; min-width: 0; grid-template-columns: repeat(2, minmax(0,1fr)); gap: .35rem; padding: .7rem; border-radius: 18px; }
  .file-action-menu button, .file-action-menu a { justify-content: center; min-height: 44px; padding: .72rem .55rem; text-align: center; border: 1px solid rgba(48,129,234,.09); background: #f8fbff; }
  .operation-modal { width: 100%; max-width: none; max-height: 88vh; margin: auto 0 0; border-radius: 20px 20px 0 0; }
  .operation-modal::backdrop { background: rgba(16,42,77,.34); }
  .operation-card { padding: 1rem; border-radius: 20px 20px 0 0; }
}
'''
app_css.write_text(css, encoding="utf-8")

print("Applied HYZoraX Control Panel V1.5.1 compact File Manager UI refinement")
