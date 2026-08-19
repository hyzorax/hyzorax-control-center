#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: ui_refine.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()

def read(rel):
    return (root / rel).read_text(encoding="utf-8")

def write(rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def sub_once(rel, pattern, replacement, label):
    text = read(rel)
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    write(rel, updated)

# ---------------------------------------------------------------------------
# Applications: turn the showcase cards into a compact software manager.
# ---------------------------------------------------------------------------
html_path = "internal/web/static/index.html"
applications_view = r'''        <section id="applications-view" class="content applications-view" hidden>
          <div class="software-manager">
            <div class="software-manager-top">
              <div class="software-tabs" role="tablist" aria-label="Application sources">
                <button type="button" class="software-source active" aria-selected="true">Official apps</button>
                <button type="button" class="software-source" aria-selected="false" disabled>Third-party <span>Soon</span></button>
              </div>
              <div class="software-manager-meta"><span id="applications-visible-count">2 apps</span><span class="software-guard">Guarded installers</span></div>
            </div>

            <div class="software-controls">
              <label class="software-search" aria-label="Search applications">
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="5.8"></circle><path d="m15 15 4.5 4.5"></path></svg>
                <input id="applications-search" type="search" autocomplete="off" spellcheck="false" placeholder="Search applications">
              </label>
              <div class="software-filters" aria-label="Filter applications">
                <button type="button" class="software-filter active" data-app-filter="all">All</button>
                <button type="button" class="software-filter" data-app-filter="installed">Installed</button>
                <button type="button" class="software-filter" data-app-filter="available">Available</button>
                <button type="button" class="software-filter" data-app-filter="attention">Needs attention</button>
              </div>
            </div>

            <div class="software-list" role="table" aria-label="HYZoraX managed applications">
              <div class="software-list-head" role="row">
                <span role="columnheader">Application</span><span role="columnheader">Target</span><span role="columnheader">Installed</span><span role="columnheader">Status</span><span role="columnheader">Action</span>
              </div>

              <article id="node24-card" class="software-row" role="row" data-app-name="node.js 24 lts javascript runtime" data-app-status="checking">
                <div class="software-app" role="cell"><span class="software-app-icon">JS</span><div><strong>Node.js 24 LTS</strong><small id="node24-detail">Checking server status…</small></div></div>
                <div class="software-value" role="cell"><small>Target</small><strong>24.19.0</strong></div>
                <div class="software-value" role="cell"><small>Installed</small><strong id="node24-version">—</strong></div>
                <div role="cell"><span id="node24-status" class="application-status neutral">Checking…</span></div>
                <div class="software-action" role="cell"><button id="node24-install-button" type="button" class="software-install" disabled>Install</button></div>
              </article>

              <article id="composer-card" class="software-row" role="row" data-app-name="composer php dependency manager" data-app-status="checking">
                <div class="software-app" role="cell"><span class="software-app-icon composer">C</span><div><strong>Composer</strong><small id="composer-detail">Requires HYZoraX PHP 8.4.</small></div></div>
                <div class="software-value" role="cell"><small>Target</small><strong>2.10.2</strong></div>
                <div class="software-value" role="cell"><small>Installed</small><strong id="composer-version">—</strong></div>
                <div role="cell"><span id="composer-status" class="application-status neutral">Checking…</span></div>
                <div class="software-action" role="cell"><button id="composer-install-button" type="button" class="software-install" disabled>Install</button></div>
              </article>

              <div id="applications-empty" class="software-empty" hidden>No applications match this filter.</div>
            </div>
            <div id="applications-error" class="alert" role="alert" hidden></div>
          </div>
        </section>

'''
html = read(html_path)
pattern = r'        <section id="applications-view" class="content applications-view" hidden>.*?</section>\n\n(?=        <section id="files-view")'
updated, count = re.subn(pattern, lambda _m: applications_view, html, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f"Applications HTML replacement failed: {count}")
html = updated

# ---------------------------------------------------------------------------
# Editor: full workspace, compact command bar, directory-focused explorer,
# dark editing surface, and a real status bar. Existing guarded read/write API
# and multi-tab/find/replace behavior remain unchanged.
# ---------------------------------------------------------------------------
editor_dialog = r'''    <dialog id="editor-dialog" class="modal editor-modal">
      <form id="editor-form" class="modal-card editor-card">
        <div class="editor-window-bar">
          <div class="editor-window-title"><span class="editor-file-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M7 3.75h7l3 3V20.25H7z"></path><path d="M14 3.75v3h3"></path><path d="M9.5 11h5M9.5 14h5M9.5 17h3.5"></path></svg></span><div><strong id="editor-name">Online Text Editor</strong><code id="editor-path"></code></div></div>
          <div class="editor-window-actions"><button id="editor-maximize-button" type="button" class="editor-window-button" aria-label="Maximize editor" title="Maximize"><svg class="maximize-icon" viewBox="0 0 24 24"><path d="M8 4H4v4M16 4h4v4M8 20H4v-4M16 20h4v-4"></path></svg><svg class="restore-icon" viewBox="0 0 24 24"><path d="M8 7h9v9H8z"></path><path d="M6 17H4V5h12v2"></path></svg></button><button id="editor-close-button" type="button" class="editor-window-button close" aria-label="Close editor" title="Close">×</button></div>
        </div>

        <div class="editor-command-bar">
          <button id="editor-save-button" type="submit" class="editor-command primary-command">✓ <span>Save</span></button>
          <button id="editor-find-button" type="button" class="editor-command">⌕ <span>Find</span></button>
          <button id="editor-replace-button" type="button" class="editor-command">↔ <span>Replace</span></button>
          <span class="editor-command-spacer"></span>
          <span class="editor-command-note">Ctrl+S Save</span><span class="editor-command-note">Ctrl+F Find</span>
        </div>

        <div class="editor-tabs-bar"><div id="editor-tabs" class="editor-tabs" role="tablist" aria-label="Open files"></div></div>

        <div class="editor-layout">
          <aside class="editor-tree" aria-label="Current directory files">
            <div class="editor-tree-head"><div><span>Directory</span><code id="editor-tree-path">/</code></div></div>
            <div class="editor-tree-tools"><button id="editor-tree-up" type="button">↑ Up</button><button id="editor-tree-refresh" type="button">↻ Refresh</button></div>
            <div id="editor-tree-content" class="editor-tree-content"><div class="editor-tree-loading">Loading directory…</div></div>
          </aside>
          <section class="editor-main">
            <aside id="editor-find-panel" class="editor-find-panel" hidden>
              <div class="editor-find-row"><input id="editor-find-input" type="search" autocomplete="off" spellcheck="false" placeholder="Find" aria-label="Find in file"><button id="editor-find-expand" type="button" class="editor-find-expand" aria-expanded="false" aria-label="Show replace" title="Replace">⌄</button><span id="editor-find-count" class="editor-find-count">0 / 0</span><button id="editor-find-previous" type="button" class="editor-find-nav" aria-label="Previous match">↑</button><button id="editor-find-next" type="button" class="editor-find-nav" aria-label="Next match">↓</button><button id="editor-find-close" type="button" class="editor-find-close" aria-label="Close find">×</button></div>
              <div id="editor-replace-row" class="editor-replace-row" hidden><input id="editor-replace-input" type="text" autocomplete="off" spellcheck="false" placeholder="Replace" aria-label="Replace with"><button id="editor-replace-one" type="button">Replace</button><button id="editor-replace-all" type="button">Replace all</button></div>
            </aside>
            <div class="editor-workspace"><pre id="editor-line-numbers" class="editor-line-numbers" aria-hidden="true">1</pre><textarea id="editor-content" name="content" spellcheck="false" aria-label="File contents"></textarea></div>
          </section>
        </div>
        <div id="editor-error" class="alert editor-inline-error" role="alert" hidden></div>
        <div class="editor-footer"><span id="editor-status" class="editor-status">Ready · Ln 1, Col 1</span><div class="editor-footer-meta"><span>LF</span><span id="editor-language">Text</span><span>UTF-8</span><span>Tab: 2</span></div></div>
      </form>
    </dialog>
'''
pattern = r'    <dialog id="editor-dialog" class="modal editor-modal">.*?</dialog>\n(?=    <div id="toast-host")'
updated, count = re.subn(pattern, lambda _m: editor_dialog, html, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f"Editor HTML replacement failed: {count}")
html = updated.replace("Version 1.6.8", "Version 1.6.9")
write(html_path, html)

# ---------------------------------------------------------------------------
# JavaScript enhancements.
# ---------------------------------------------------------------------------
js_path = "internal/web/static/app.js"
js = read(js_path)
if "editorTreePath:" not in js:
    marker = "editorTreeLoaded: false,"
    if marker not in js:
        raise SystemExit("editorTreeLoaded state marker not found")
    js = js.replace(marker, marker + '\neditorTreePath: "/",', 1)

# Applications renderer + filtering.
pattern = r'function renderApplication\(prefix,data\)\{.*?\n\}\nasync function loadApplications\(\)\{'
replacement = r'''function renderApplication(prefix,data){
const badge=$(`#${prefix}-status`),version=$(`#${prefix}-version`),detail=$(`#${prefix}-detail`),button=$(`#${prefix}-install-button`),row=$(`#${prefix}-card`);
badge.textContent=applicationStatusLabel(data.status);badge.className=`application-status ${data.status||"neutral"}`;
version.textContent=data.version||"—";
detail.textContent=data.detail||"Status unavailable.";
if(prefix==="node24"&&data.npm_version)detail.textContent=`Installed and healthy · npm ${data.npm_version}`;
button.disabled=!data.installable||state.applicationsBusy;
button.textContent=data.installed?"Installed":"Install";
row.dataset.appStatus=data.status||"unknown";
row.dataset.appInstalled=data.installed?"true":"false";
applyApplicationFilters();
}
function activeApplicationFilter(){return document.querySelector("[data-app-filter].active")?.dataset.appFilter||"all";}
function applyApplicationFilters(){
const query=($("#applications-search")?.value||"").trim().toLocaleLowerCase(),filter=activeApplicationFilter();let visible=0;
document.querySelectorAll(".software-row").forEach((row)=>{const status=row.dataset.appStatus||"unknown",installed=row.dataset.appInstalled==="true";let match=!query||row.dataset.appName.includes(query)||row.textContent.toLocaleLowerCase().includes(query);if(filter==="installed")match=match&&installed;else if(filter==="available")match=match&&status==="not_installed";else if(filter==="attention")match=match&&["dependency","conflict","attention","unsupported","blocked"].includes(status);row.hidden=!match;if(match)visible++;});
$("#applications-visible-count").textContent=`${visible} app${visible===1?"":"s"}`;$("#applications-empty").hidden=visible!==0;
}
async function loadApplications(){'''
updated, count = re.subn(pattern, lambda _m: replacement, js, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f"Applications renderer replacement failed: {count}")
js = updated

# Editor directory-focused explorer and guarded close.
pattern = r'function activateEditorTab\(path\)\{.*?\nasync function openEditor\(path\)\{.*?\nasync function loadEditorTreeRoot\(\)\{.*?\nfunction renderEditorTreeEntries\(host,entries,depth\)\{.*?\n\nfunction openRename'
replacement = r'''function editorParentDirectory(path){const parts=String(path||"/").split("/").filter(Boolean);if(parts.length)parts.pop();return `/${parts.join("/")}`||"/";}
function editorLanguageLabel(path){const ext=(String(path).split(".").pop()||"").toLowerCase();return {js:"JavaScript",ts:"TypeScript",json:"JSON",php:"PHP",py:"Python",sh:"Shell",bash:"Shell",css:"CSS",html:"HTML",htm:"HTML",md:"Markdown",yaml:"YAML",yml:"YAML",toml:"TOML",sql:"SQL",go:"Go",xml:"XML"}[ext]||"Text";}
function renderEditorDirectoryEntries(host,entries){const sorted=[...(entries||[])].sort((a,b)=>{if(a.kind===b.kind)return String(a.name).localeCompare(String(b.name));if(a.kind==="directory")return -1;if(b.kind==="directory")return 1;return String(a.name).localeCompare(String(b.name));});if(!sorted.length){host.innerHTML='<div class="editor-tree-loading">This directory is empty.</div>';return}sorted.forEach((entry)=>{const button=document.createElement("button");button.type="button";button.className="editor-tree-row";button.title=entry.path;if(entry.kind==="directory"){button.classList.add("directory");button.innerHTML='<span class="editor-tree-kind">▣</span>';const label=document.createElement("span");label.textContent=entry.name;button.append(label);button.addEventListener("click",()=>loadEditorDirectory(entry.path));}else if(entry.editable){button.classList.add("editable");button.innerHTML='<span class="editor-tree-kind">▤</span>';const label=document.createElement("span");label.textContent=entry.name;button.append(label);button.addEventListener("click",()=>openEditor(entry.path));}else{button.classList.add("readonly");button.innerHTML='<span class="editor-tree-kind">·</span>';const label=document.createElement("span");label.textContent=entry.name;button.append(label);button.disabled=true;}host.append(button);});}
async function loadEditorDirectory(path){const target=path||"/",host=$("#editor-tree-content");host.innerHTML='<div class="editor-tree-loading">Loading directory…</div>';state.editorTreeLoaded=false;try{const data=await request(`api/v1/files?path=${encodeURIComponent(target)}`);state.editorTreePath=data.path||target;$("#editor-tree-path").textContent=state.editorTreePath;$("#editor-tree-up").disabled=state.editorTreePath==="/";host.replaceChildren();renderEditorDirectoryEntries(host,data.entries||[]);state.editorTreeLoaded=true;}catch(error){host.innerHTML='';const message=document.createElement("div");message.className="editor-tree-loading error";message.textContent=error.message;host.append(message);}}
function activateEditorTab(path){snapshotActiveEditor();const tab=state.editorTabs.find((item)=>item.path===path);if(!tab)return;state.activeEditorPath=tab.path;state.editorPath=tab.path;state.editorHash=tab.hash;$("#editor-path").textContent=tab.path;$("#editor-name").textContent=tab.name;$("#editor-language").textContent=editorLanguageLabel(tab.path);$("#editor-content").value=tab.content;resetEditorFind();renderEditorTabs();updateEditorLineNumbers();updateEditorCursorStatus();clearError("#editor-error");const directory=editorParentDirectory(tab.path);if(!state.editorTreeLoaded||state.editorTreePath!==directory)loadEditorDirectory(directory);$("#editor-content").focus({preventScroll:true});}
async function openEditor(path){clearError("#file-error");try{let tab=state.editorTabs.find((item)=>item.path===path);if(!tab){const data=await request(`api/v1/files/text?path=${encodeURIComponent(path)}`);tab={path:data.path,name:data.name||data.path.split("/").filter(Boolean).pop()||"Text file",hash:data.sha256,content:data.content,savedContent:data.content};state.editorTabs.push(tab)}if(!$("#editor-dialog").open)openDialog("#editor-dialog");activateEditorTab(tab.path)}catch(error){showError("#file-error",error.message)}}
async function closeEditorWindow(){snapshotActiveEditor();const modified=state.editorTabs.filter((tab)=>tab.content!==tab.savedContent);if(modified.length){const ok=await showPanelConfirmation({title:"Close editor?",message:`${modified.length} open file${modified.length===1?" has":"s have"} unsaved changes. Close without saving?`,confirmLabel:"Close",danger:true});if(!ok)return}closeDialog($("#editor-dialog"));}

function openRename'''
updated, count = re.subn(pattern, lambda _m: replacement, js, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f"Editor function replacement failed: {count}")
js = updated

# Applications search/filter event wiring.
marker = '$("#composer-install-button").addEventListener("click",()=>installApplication("composer","Composer"));'
if marker not in js:
    raise SystemExit("Composer install wiring marker not found")
extra = marker + r'''
$("#applications-search").addEventListener("input",applyApplicationFilters);
document.querySelectorAll("[data-app-filter]").forEach((button)=>button.addEventListener("click",()=>{document.querySelectorAll("[data-app-filter]").forEach((item)=>item.classList.toggle("active",item===button));applyApplicationFilters();}));'''
js = js.replace(marker, extra, 1)

# Editor top command and directory controls.
marker = '$("#editor-find-button").addEventListener("click",openEditorFind);$("#editor-maximize-button").addEventListener("click",toggleEditorMaximize);'
if marker not in js:
    raise SystemExit("Editor command wiring marker not found")
extra = r'''$("#editor-find-button").addEventListener("click",openEditorFind);$("#editor-replace-button").addEventListener("click",()=>{openEditorFind();if($("#editor-replace-row").hidden)toggleEditorReplace();});$("#editor-maximize-button").addEventListener("click",toggleEditorMaximize);$("#editor-close-button").addEventListener("click",closeEditorWindow);$("#editor-tree-refresh").addEventListener("click",()=>loadEditorDirectory(state.editorTreePath));$("#editor-tree-up").addEventListener("click",()=>{if(state.editorTreePath==="/")return;loadEditorDirectory(editorParentDirectory(state.editorTreePath+"/placeholder"));});$("#editor-dialog").addEventListener("cancel",(event)=>{event.preventDefault();closeEditorWindow();});'''
js = js.replace(marker, extra, 1)
write(js_path, js)

# ---------------------------------------------------------------------------
# CSS: compact software manager + full-workspace dark editor.
# ---------------------------------------------------------------------------
css_path = "internal/web/static/app.css"
css = read(css_path)
css += r'''

/* V1.6.9 practical Applications workspace */
.applications-view{padding-top:1.15rem!important}.software-manager{display:flex;flex-direction:column;gap:1rem}.software-manager-top{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.2rem 0 .65rem;border-bottom:1px solid var(--line)}.software-tabs{display:flex;align-items:center;gap:.35rem}.software-source{min-height:38px;padding:.55rem .9rem;border:1px solid transparent;border-radius:9px;color:#6b84a0;background:transparent;font-size:.68rem;font-weight:850}.software-source.active{color:var(--blue-deep);border-color:var(--line-strong);background:#fff;box-shadow:0 5px 15px rgba(40,102,177,.07)}.software-source:disabled{opacity:.52;cursor:not-allowed}.software-source span{margin-left:.35rem;font-size:.52rem;text-transform:uppercase;letter-spacing:.06em}.software-manager-meta{display:flex;align-items:center;gap:.55rem;color:#7990aa;font-size:.62rem;font-weight:800}.software-guard{padding:.38rem .58rem;border:1px solid #b9d8fb;border-radius:999px;color:#1c67c9;background:#eef7ff}.software-controls{display:flex;align-items:center;justify-content:space-between;gap:1rem}.software-search{width:min(520px,100%);height:42px;display:flex;align-items:center;gap:.55rem;padding:0 .75rem;border:1px solid var(--line-strong);border-radius:10px;background:#fff;box-shadow:0 5px 16px rgba(31,78,135,.05)}.software-search svg{width:17px;height:17px;flex:0 0 auto;fill:none;stroke:#6d87a4;stroke-width:1.8;stroke-linecap:round}.software-search input{width:100%;height:100%;padding:0;border:0;background:transparent;box-shadow:none!important;font-size:.72rem}.software-search input:focus{outline:0}.software-filters{display:flex;align-items:center;gap:.35rem;flex-wrap:wrap;justify-content:flex-end}.software-filter{min-height:36px;padding:.45rem .72rem;border:1px solid var(--line);border-radius:8px;color:#607d9d;background:#f7faff;font-size:.6rem;font-weight:820}.software-filter:hover{background:#fff;border-color:var(--line-strong)}.software-filter.active{color:#fff;border-color:#2478ee;background:#2478ee;box-shadow:0 7px 18px rgba(36,120,238,.18)}.software-list{overflow:hidden;border:1px solid var(--line);border-radius:13px;background:rgba(255,255,255,.96);box-shadow:0 12px 32px rgba(35,86,145,.06)}.software-list-head,.software-row{display:grid;grid-template-columns:minmax(300px,2.2fr) minmax(90px,.7fr) minmax(100px,.75fr) minmax(140px,.9fr) minmax(100px,.65fr);align-items:center;gap:.7rem}.software-list-head{min-height:42px;padding:.55rem .8rem;border-bottom:1px solid var(--line);color:#7d93ac;background:#f7faff;font-size:.55rem;font-weight:850;text-transform:uppercase;letter-spacing:.055em}.software-row{min-height:82px;padding:.72rem .8rem;border-bottom:1px solid #edf2f8;background:#fff}.software-row:last-of-type{border-bottom:0}.software-row:hover{background:#fbfdff}.software-row[hidden]{display:none!important}.software-app{min-width:0;display:flex;align-items:center;gap:.7rem}.software-app-icon{width:38px;height:38px;display:grid;place-items:center;flex:0 0 auto;border-radius:10px;color:#fff;background:linear-gradient(145deg,#64d6f6,#1769ea);box-shadow:0 7px 18px rgba(42,121,233,.18);font-size:.72rem;font-weight:900}.software-app-icon.composer{font-size:.84rem}.software-app>div{min-width:0}.software-app strong{display:block;margin-bottom:.18rem;color:var(--ink);font-size:.78rem}.software-app small{display:block;max-width:480px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#6f87a2;font-size:.6rem}.software-value small{display:none;color:#8a9db3;font-size:.52rem;text-transform:uppercase}.software-value strong{color:#385e84;font-size:.68rem}.software-action{display:flex;justify-content:flex-end}.software-install{min-width:86px;min-height:36px;padding:.45rem .8rem;border:1px solid #2478ee;border-radius:8px;color:#fff;background:#2478ee;font-size:.64rem;font-weight:850;box-shadow:0 7px 18px rgba(36,120,238,.17)}.software-install:hover:not(:disabled){background:#1767dc}.software-install:disabled{color:#9badc1;border-color:#d6e0eb;background:#eef3f8;box-shadow:none;cursor:not-allowed}.software-empty{padding:2rem;text-align:center;color:#7b91aa;font-size:.68rem}.software-empty[hidden]{display:none!important}.software-list .application-status{display:inline-flex;justify-content:center;min-width:108px}.applications-view>.alert{margin-top:0}@media(max-width:980px){.software-controls{align-items:stretch;flex-direction:column}.software-search{width:100%;max-width:none}.software-filters{justify-content:flex-start}.software-list-head{display:none}.software-row{grid-template-columns:minmax(0,1fr) auto;gap:.65rem .9rem}.software-app{grid-column:1}.software-action{grid-column:2;grid-row:1}.software-value{display:flex;align-items:center;gap:.45rem}.software-value small{display:inline}.software-row>div:nth-child(4){grid-column:1}.software-row>div:nth-child(3){grid-column:1}.software-row>div:nth-child(2){grid-column:1}}@media(max-width:620px){.software-manager-top{align-items:flex-start;flex-direction:column}.software-manager-meta{width:100%;justify-content:space-between}.software-filters{display:grid;grid-template-columns:1fr 1fr;width:100%}.software-filter{width:100%}.software-row{grid-template-columns:1fr}.software-action{grid-column:1;grid-row:auto;justify-content:flex-start}.software-app small{white-space:normal}.software-list .application-status{min-width:0}.software-install{width:100%}}

/* V1.6.9 full-workspace server editor */
.editor-modal{width:calc(100vw - 28px)!important;max-width:none!important;height:calc(100dvh - 28px)!important;max-height:none!important;margin:14px!important;padding:0!important;overflow:hidden!important;border-radius:14px!important}.editor-card{width:100%!important;height:100%!important;max-height:none!important;min-height:0!important;display:grid!important;grid-template-rows:auto auto auto minmax(0,1fr) auto auto!important;gap:0!important;padding:0!important;overflow:hidden!important;border-radius:14px!important;background:#111a25!important}.editor-window-bar{min-height:58px;display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.55rem .75rem .55rem .85rem;border-bottom:1px solid #dde6ef;background:#fff}.editor-window-title{min-width:0;display:flex;align-items:center;gap:.65rem}.editor-window-title>div{min-width:0}.editor-window-title strong{display:block;max-width:50vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#183453;font-size:.82rem}.editor-window-title code{display:block;max-width:70vw;margin-top:.14rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#7590ad;background:transparent;font-size:.58rem}.editor-window-actions{display:flex;align-items:center;gap:.35rem}.editor-window-button{width:34px;height:34px;display:grid;place-items:center;border:1px solid #d8e3ef;border-radius:8px;color:#587695;background:#f8fbff;font-size:1.15rem}.editor-window-button:hover{color:#1768df;background:#eef7ff}.editor-window-button.close:hover{color:#d02d3b;background:#fff1f3;border-color:#f2cbd0}.editor-window-button svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round}.editor-window-button .restore-icon{display:none}.editor-maximized .editor-window-button .maximize-icon{display:none}.editor-maximized .editor-window-button .restore-icon{display:block}.editor-command-bar{min-height:45px;display:flex;align-items:center;gap:.3rem;padding:.35rem .55rem;border-bottom:1px solid #d9e3ed;background:#f6f8fb}.editor-command{min-height:34px;display:flex;align-items:center;gap:.38rem;padding:.4rem .62rem;border:1px solid #d7e1ec;border-radius:7px;color:#4c6682;background:#fff;font-size:.62rem;font-weight:800}.editor-command:hover{color:#1768df;border-color:#b8d4f4;background:#f5faff}.editor-command.primary-command{color:#fff;border-color:#2478ee;background:#2478ee}.editor-command.primary-command:hover{background:#1767dd}.editor-command-spacer{flex:1 1 auto}.editor-command-note{color:#8699ae;font-size:.53rem;font-weight:750}.editor-tabs-bar{min-height:40px;display:flex;align-items:end;padding:.3rem .45rem 0;border-bottom:1px solid #263545;background:#172330}.editor-tabs{width:100%;min-width:0;display:flex;align-items:end;gap:.2rem;overflow-x:auto;scrollbar-width:thin}.editor-tab{min-height:32px!important;padding:.35rem .5rem!important;border:1px solid transparent!important;border-radius:7px 7px 0 0!important;color:#9eb0c3!important;background:transparent!important;box-shadow:none!important}.editor-tab:hover{color:#d5e0eb!important;background:#1d2b3a!important}.editor-tab.active{color:#fff!important;border-color:#314459!important;border-bottom-color:#0f1822!important;background:#0f1822!important}.editor-tab-close{color:#8296aa!important}.editor-layout{min-height:0!important;display:grid!important;grid-template-columns:255px minmax(0,1fr)!important;overflow:hidden!important;background:#0f1822!important}.editor-tree{min-width:0!important;min-height:0!important;display:grid!important;grid-template-rows:auto auto minmax(0,1fr)!important;overflow:hidden!important;border-right:1px solid #29394a!important;background:#172330!important}.editor-tree-head{min-height:52px!important;display:flex!important;align-items:center!important;padding:.48rem .65rem!important;border-bottom:1px solid #29394a!important;color:#90a7bd!important;background:#1b2937!important}.editor-tree-head>div{min-width:0}.editor-tree-head span{display:block;margin-bottom:.12rem;color:#8fa5ba;font-size:.54rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em}.editor-tree-head code{display:block;max-width:225px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#e1e9f2!important;background:transparent!important;font-size:.58rem}.editor-tree-tools{min-height:39px;display:flex;align-items:center;gap:.3rem;padding:.3rem .45rem;border-bottom:1px solid #29394a;background:#16212d}.editor-tree-tools button{min-height:30px;padding:.3rem .5rem;border:1px solid #314459;border-radius:6px;color:#a9bacb;background:#1c2b39;font-size:.56rem;font-weight:800}.editor-tree-tools button:hover:not(:disabled){color:#fff;border-color:#3f5b77;background:#26394b}.editor-tree-tools button:disabled{opacity:.4;cursor:not-allowed}.editor-tree-content{min-height:0!important;overflow:auto!important;padding:.25rem 0!important;scrollbar-gutter:stable!important;scrollbar-width:thin;background:#172330!important}.editor-tree-row{width:100%!important;min-width:max-content!important;display:flex!important;align-items:center!important;gap:.42rem!important;min-height:32px!important;padding:.3rem .55rem!important;border:0!important;border-radius:0!important;color:#adbdcd!important;background:transparent!important;text-align:left!important;font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important;font-size:.6rem!important}.editor-tree-row:hover:not(:disabled){color:#fff!important;background:#223448!important}.editor-tree-row.directory{color:#d4dfeb!important}.editor-tree-row.editable{color:#c7d6e5!important}.editor-tree-row.readonly{opacity:.42!important}.editor-tree-kind{width:16px;flex:0 0 16px;text-align:center;color:#68a9ee}.editor-tree-row.directory .editor-tree-kind{color:#e6b84b}.editor-tree-loading{padding:.7rem!important;color:#8197ac!important;font-size:.59rem!important}.editor-tree-loading.error{color:#f08a93!important}.editor-main{position:relative!important;min-width:0!important;min-height:0!important;overflow:hidden!important;background:#0f1822!important}.editor-workspace{height:100%!important;min-height:0!important;display:grid!important;grid-template-columns:auto minmax(0,1fr)!important;overflow:hidden!important;border:0!important;border-radius:0!important;background:#0f1822!important}.editor-line-numbers{min-width:52px!important;height:100%!important;margin:0!important;overflow:hidden!important;padding:12px 10px!important;border-right:1px solid #273646!important;color:#61778d!important;background:#151f2b!important;font-size:12px!important;line-height:1.6!important}#editor-content{width:100%!important;height:100%!important;min-height:0!important;resize:none!important;overflow:auto!important;padding:12px 15px!important;border:0!important;border-radius:0!important;color:#e8eef5!important;background:#0f1822!important;box-shadow:none!important;caret-color:#70b8ff!important;font-size:12px!important;line-height:1.6!important;tab-size:2!important}#editor-content:focus{outline:0!important;border:0!important;background:#0f1822!important;box-shadow:none!important}#editor-content::selection{background:rgba(77,153,244,.34)}.editor-find-panel{top:.55rem!important;right:.65rem!important;border-color:#3a4d61!important;background:#192635!important;box-shadow:0 16px 42px rgba(0,0,0,.35)!important}.editor-find-row input,.editor-replace-row input{color:#e7eef6!important;border-color:#3a4d61!important;background:#0f1822!important}.editor-find-expand,.editor-find-nav,.editor-find-close,.editor-replace-row button{color:#b2c3d4!important;border-color:#3a4d61!important;background:#223244!important}.editor-find-count{color:#9aafc2!important}.editor-replace-row{border-top-color:#34485c!important}.editor-inline-error{margin:0!important;border-radius:0!important}.editor-footer{min-height:34px!important;display:flex!important;align-items:center!important;justify-content:space-between!important;gap:.8rem!important;padding:.35rem .7rem!important;border-top:1px solid #29394a!important;color:#8fa5b9!important;background:#101923!important}.editor-status{color:#9fb2c4!important;font-size:.56rem!important}.editor-footer-meta{display:flex;align-items:center;gap:0}.editor-footer-meta span{padding:0 .58rem;border-left:1px solid #2b3c4e;color:#8da2b6;font-size:.54rem}.editor-maximized{width:100vw!important;height:100dvh!important;margin:0!important;border-radius:0!important}.editor-maximized .editor-card{border-radius:0!important}.editor-maximized .editor-layout{grid-template-columns:270px minmax(0,1fr)!important}@media(max-width:760px){.editor-modal{width:100vw!important;height:100dvh!important;margin:0!important;border-radius:0!important}.editor-card{border-radius:0!important}.editor-layout{grid-template-columns:145px minmax(0,1fr)!important}.editor-tree-head code{max-width:120px}.editor-command-note{display:none}.editor-command span{display:none}.editor-window-title strong{max-width:44vw}.editor-window-title code{max-width:56vw}.editor-footer-meta span:nth-child(1),.editor-footer-meta span:nth-child(4){display:none}}
'''
write(css_path, css)

# Version expectations in embedded UI tests.
for rel in ("internal/web/assets_test.go", "internal/httpapi/app_test.go"):
    text = read(rel)
    if "1.6.8" not in text:
        raise SystemExit(f"version marker missing in {rel}")
    write(rel, text.replace("1.6.8", "1.6.9"))

print("Applied HYZoraX V1.6.9 practical Applications and full-workspace editor refinement")
