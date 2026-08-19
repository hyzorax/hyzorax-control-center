#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply.py <hyzorax-control-source-root>")

root = Path(sys.argv[1]).resolve()

def read(rel): return (root / rel).read_text(encoding="utf-8")
def write(rel, text): (root / rel).write_text(text, encoding="utf-8")
def replace_once(text, old, new, label):
    if old not in text: raise SystemExit(f"{label}: marker not found")
    return text.replace(old, new, 1)
def sub_once(text, pattern, repl, label):
    out, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1: raise SystemExit(f"{label}: expected 1 match, got {count}")
    return out

index_path="internal/web/static/index.html"; js_path="internal/web/static/app.js"; css_path="internal/web/static/app.css"
assets_test_path="internal/web/assets_test.go"; app_test_path="internal/httpapi/app_test.go"
html=read(index_path); js=read(js_path); css=read(css_path)
html=replace_once(html,"Version 1.5.3","Version 1.5.4","version")

editor_dialog=r'''<dialog id="editor-dialog" class="modal editor-modal">
      <form id="editor-form" class="modal-card editor-card">
        <div class="editor-header">
          <div class="editor-title-group"><span class="editor-file-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M7 3.75h7l3 3V20.25H7z"></path><path d="M14 3.75v3h3"></path><path d="M9.5 11h5M9.5 14h5M9.5 17h3.5"></path></svg></span><div><h3 id="editor-name">Edit text file</h3><p class="editor-path"><code id="editor-path"></code></p></div></div>
          <div class="editor-header-tools"><span class="editor-encoding">UTF-8</span><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        </div>
        <div class="editor-workspace"><pre id="editor-line-numbers" class="editor-line-numbers" aria-hidden="true">1</pre><textarea id="editor-content" name="content" spellcheck="false" aria-label="File contents"></textarea></div>
        <div id="editor-error" class="alert" role="alert" hidden></div>
        <div class="editor-footer"><span id="editor-status" class="editor-status">Ready</span><div class="modal-actions"><button type="button" class="ghost compact" data-close-dialog>Cancel</button><button type="submit" class="primary compact-primary">Save</button></div></div>
      </form>
    </dialog>'''
html=sub_once(html,r'<dialog id="editor-dialog"[^>]*>.*?</dialog>',editor_dialog,"editor dialog redesign")

preview_dialog=r'''<dialog id="image-preview-dialog" class="modal image-preview-modal">
      <div class="modal-card image-preview-card">
        <div class="image-preview-header"><div><h3 id="image-preview-name">Image preview</h3><p id="image-preview-path" class="image-preview-path"></p></div><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        <div class="image-preview-stage"><img id="image-preview-image" alt=""></div>
        <div id="image-preview-error" class="alert" role="alert" hidden></div>
        <div class="image-preview-footer"><a id="image-preview-download" class="ghost compact" href="#">Download</a><button type="button" class="primary compact-primary" data-close-dialog>Close</button></div>
      </div>
    </dialog>'''
html=sub_once(html,r'<dialog id="image-preview-dialog"[^>]*>.*?</dialog>',preview_dialog,"image preview dialog")

delete_dialog=r'''<dialog id="delete-dialog" class="modal operation-modal delete-modal">
      <form id="delete-form" class="modal-card operation-card confirm-action-card">
        <div class="operation-heading"><h3>Move to Recycle Bin?</h3><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        <p class="confirm-action-message">Are you sure you want to move <strong id="delete-source-path"></strong> to the Recycle Bin?</p>
        <div id="delete-error" class="alert" role="alert" hidden></div>
        <div class="modal-actions"><button type="button" class="ghost compact" data-close-dialog>Cancel</button><button type="submit" class="danger-button">Confirm</button></div>
      </form>
    </dialog>'''
html=sub_once(html,r'<dialog id="delete-dialog"[^>]*>.*?</dialog>',delete_dialog,"delete confirmation dialog")

recycle_dialog=r'''<dialog id="recycle-bin-dialog" class="modal recycle-bin-modal">
      <div class="modal-card recycle-bin-card">
        <div class="recycle-bin-header"><div class="recycle-bin-title"><span class="recycle-bin-title-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M7 8.5h10l-.7 11H7.7z"></path><path d="M9 8.5V6.2h6v2.3M5.5 8.5h13M9.5 11.5v5M14.5 11.5v5"></path></svg></span><div><h3>Recycle Bin</h3><p><span id="recycle-bin-count">0 items</span> · Restore items or remove them permanently.</p></div></div><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        <div class="recycle-bin-browser"><div class="recycle-bin-columns" aria-hidden="true"><span>Name</span><span>Original location</span><span>Date deleted</span><span>Type</span><span>Actions</span></div><div id="recycle-bin-list" class="recycle-bin-list"></div><div id="recycle-bin-empty" class="recycle-bin-empty" hidden><span class="recycle-empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M7 8.5h10l-.7 11H7.7z"></path><path d="M9 8.5V6.2h6v2.3M5.5 8.5h13"></path></svg></span><strong>Recycle Bin is empty</strong><small>Deleted files and folders will appear here.</small></div></div>
        <div id="recycle-bin-error" class="alert" role="alert" hidden></div>
      </div>
    </dialog>'''
html=sub_once(html,r'<dialog id="recycle-bin-dialog"[^>]*>.*?</dialog>',recycle_dialog,"computer style recycle bin")

confirmation_dialog=r'''<dialog id="confirmation-dialog" class="modal confirmation-modal">
      <div class="modal-card confirmation-card"><div class="operation-heading"><h3 id="confirmation-title">Confirm action</h3><button id="confirmation-close" type="button" class="operation-close" aria-label="Close">×</button></div><p id="confirmation-message" class="confirmation-message"></p><div class="modal-actions"><button id="confirmation-cancel" type="button" class="ghost compact">Cancel</button><button id="confirmation-confirm" type="button" class="primary compact-primary">Confirm</button></div></div>
    </dialog>'''
if 'id="confirmation-dialog"' not in html:
    html=replace_once(html,'    <dialog id="editor-dialog" class="modal editor-modal">',confirmation_dialog+'\n\n    <dialog id="editor-dialog" class="modal editor-modal">',"confirmation dialog insertion")
folder_svg='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 6.5h6l1.7 2H20.5v9H3.5z"></path><path d="M3.5 8.5h17"></path></svg>'
html=html.replace('<span class="destination-icon" aria-hidden="true">▣</span>','<span class="destination-icon" aria-hidden="true">'+folder_svg+'</span>')
html=html.replace('>▱</button>','>'+folder_svg+'</button>')
write(index_path,html)

js=replace_once(js,'const icon = document.createElement("span");\nicon.className = `file-kind ${entry.kind}`;\nicon.textContent = fileKindIcon(entry.kind);','const icon = buildFileIcon(entry.name, entry.kind);',"main file icons")
old_icon=r'''function fileKindIcon(kind) {
if (kind === "directory") return "▱";
if (kind === "file") return "▤";
if (kind === "symlink") return "↗";
return "◇";
}'''
new_icons=r'''function fileVisualType(name, kind) {
if (kind === "directory") return "folder";
if (kind === "symlink") return "link";
const lower = String(name || "").toLowerCase();
if (/\.(png|jpe?g|webp|gif|svg|bmp|ico)$/i.test(lower)) return "image";
if (/\.(zip|tar|tgz|gz|bz2|xz|7z|rar)$/i.test(lower)) return "archive";
if (/\.(db|sqlite|sqlite3|sql)$/i.test(lower)) return "database";
if (/\.(pem|crt|cer|key|p12|pfx)$/i.test(lower)) return "certificate";
if (/\.(sh|bash|zsh|py|js|mjs|cjs|ts|tsx|jsx|go|php|html?|css|scss|json|ya?ml|toml|xml|ini|conf|env|patch|diff)$/i.test(lower)) return "code";
if (/\.(txt|md|log|csv|tsv|rtf)$/i.test(lower)) return "text";
return "file";
}
function fileIconSVG(type) {
const common = 'viewBox="0 0 24 24" aria-hidden="true"';
const icons = {
folder:`<svg ${common}><path d="M3.2 7.2h6.1l1.8 2H20.8v9.2H3.2z"></path><path d="M3.2 9.2h17.6"></path></svg>`,
image:`<svg ${common}><rect x="4" y="4.5" width="16" height="15" rx="2"></rect><circle cx="9" cy="9.5" r="1.5"></circle><path d="m6.5 17 4.1-4.2 2.8 2.7 2.1-2.1 2 3.6"></path></svg>`,
text:`<svg ${common}><path d="M6.5 3.5h8l3 3v14h-11z"></path><path d="M14.5 3.5v3h3M9 11h6M9 14h6M9 17h4"></path></svg>`,
code:`<svg ${common}><path d="M6.5 3.5h8l3 3v14h-11z"></path><path d="M14.5 3.5v3h3M11 11l-2 2 2 2M14 11l2 2-2 2"></path></svg>`,
archive:`<svg ${common}><path d="M6 3.5h12v17H6z"></path><path d="M10 3.5v3h4v3h-4v3h4v3h-4M10 18h4"></path></svg>`,
database:`<svg ${common}><ellipse cx="12" cy="6" rx="7" ry="3"></ellipse><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"></path></svg>`,
certificate:`<svg ${common}><path d="M7 3.5h10v9H7z"></path><path d="m10 12.5-1 7 3-1.8 3 1.8-1-7M9.5 7.5h5"></path></svg>`,
link:`<svg ${common}><path d="M9.5 14.5 8 16a3 3 0 0 1-4.2-4.2l3-3A3 3 0 0 1 11 8.7M14.5 9.5 16 8a3 3 0 0 1 4.2 4.2l-3 3a3 3 0 0 1-4.2.1M8.5 15.5l7-7"></path></svg>`,
file:`<svg ${common}><path d="M6.5 3.5h8l3 3v14h-11z"></path><path d="M14.5 3.5v3h3"></path></svg>`};
return icons[type] || icons.file;
}
function fileTypeLabel(name, kind) { const type=fileVisualType(name,kind); return ({folder:"Folder",image:"Image",text:"Text document",code:"Code / config",archive:"Archive",database:"Database",certificate:"Certificate / key",link:"Shortcut / link",file:"File"})[type] || "File"; }
function buildFileIcon(name, kind) { const type=fileVisualType(name,kind); const icon=document.createElement("span"); icon.className=`file-kind ${kind} file-type-${type}`; icon.innerHTML=fileIconSVG(type); icon.title=fileTypeLabel(name,kind); return icon; }
function fileKindIcon(kind) { return kind === "directory" ? "Folder" : kind === "symlink" ? "Link" : "File"; }'''
js=replace_once(js,old_icon,new_icons,"file icon helpers")

recycle_pattern=r'''async function loadRecycleBin\(\) \{.*?\n\}\n(?=function fileVisualType|function fileKindIcon)'''
recycle_function=r'''async function loadRecycleBin() {
clearError("#recycle-bin-error");
try {
const data=await request("api/v1/files/recycle-bin");
const items=Array.isArray(data.items)?data.items:[];
const list=$("#recycle-bin-list"); list.replaceChildren();
$("#recycle-bin-count").textContent=`${items.length} item${items.length===1?"":"s"}`;
$("#recycle-bin-empty").hidden=items.length!==0;
items.forEach((item)=>{
const row=document.createElement("div"); row.className="recycle-bin-row";
const nameCell=document.createElement("div"); nameCell.className="recycle-bin-name-cell"; const icon=buildFileIcon(item.name,item.kind); const name=document.createElement("strong"); name.textContent=item.name; nameCell.append(icon,name);
const path=document.createElement("div"); path.className="recycle-bin-cell recycle-bin-path"; path.textContent=item.original_path;
const time=document.createElement("div"); time.className="recycle-bin-cell"; time.textContent=formatTimestamp(item.deleted_at);
const type=document.createElement("div"); type.className="recycle-bin-cell"; type.textContent=fileTypeLabel(item.name,item.kind);
const actions=document.createElement("div"); actions.className="recycle-bin-actions";
const restore=document.createElement("button"); restore.type="button"; restore.className="recycle-action-button"; restore.textContent="Restore";
restore.addEventListener("click",async()=>{restore.disabled=true;try{await request("api/v1/files/recycle-bin/restore",{method:"POST",body:JSON.stringify({id:item.id})});await loadRecycleBin();await loadFiles(state.currentPath);}catch(error){showError("#recycle-bin-error",error.message);}finally{restore.disabled=false;}});
const purge=document.createElement("button"); purge.type="button"; purge.className="recycle-action-button danger"; purge.textContent="Delete permanently";
purge.addEventListener("click",async()=>{const confirmed=await showPanelConfirmation({title:"Delete permanently?",message:`Are you sure you want to permanently delete ${item.name}?`,confirmLabel:"Delete",danger:true});if(!confirmed)return;purge.disabled=true;try{await request("api/v1/files/recycle-bin/purge",{method:"POST",body:JSON.stringify({id:item.id})});await loadRecycleBin();}catch(error){showError("#recycle-bin-error",error.message);}finally{purge.disabled=false;}});
actions.append(restore,purge); row.append(nameCell,path,time,type,actions); list.append(row);
});
}catch(error){showError("#recycle-bin-error",error.message);}
}
'''
js=sub_once(js,recycle_pattern,recycle_function,"recycle bin browser behavior")

confirmation_helper=r'''function showPanelConfirmation({ title = "Confirm action", message = "Are you sure?", confirmLabel = "Confirm", danger = false } = {}) {
const dialog=$("#confirmation-dialog"), titleNode=$("#confirmation-title"), messageNode=$("#confirmation-message"), confirmButton=$("#confirmation-confirm"), cancelButton=$("#confirmation-cancel"), closeButton=$("#confirmation-close");
titleNode.textContent=title; messageNode.textContent=message; confirmButton.textContent=confirmLabel; confirmButton.className=danger?"danger-button":"primary compact-primary";
return new Promise((resolve)=>{let settled=false;const finish=(result)=>{if(settled)return;settled=true;dialog.oncancel=null;confirmButton.onclick=null;cancelButton.onclick=null;closeButton.onclick=null;closeDialog(dialog);resolve(result);};confirmButton.onclick=()=>finish(true);cancelButton.onclick=()=>finish(false);closeButton.onclick=()=>finish(false);dialog.oncancel=(event)=>{event.preventDefault();finish(false);};openDialog("#confirmation-dialog");confirmButton.focus();});
}
'''
js=replace_once(js,'function openDialog(selector) {',confirmation_helper+'function openDialog(selector) {',"panel confirmation helper")
old_update=r'''if (!window.confirm(`Update HYZoraX Control Panel ${status.current_version} to ${status.latest_version}? The panel will restart automatically.`)) {
button.disabled = false;
return;
}'''
new_update=r'''const updateConfirmed = await showPanelConfirmation({ title: "Confirm update", message: `Update HYZoraX Control Panel ${status.current_version} to ${status.latest_version}? The panel will restart automatically.`, confirmLabel: "Update" });
if (!updateConfirmed) { button.disabled = false; return; }'''
js=replace_once(js,old_update,new_update,"panel update confirmation")

editor_helpers=r'''function updateEditorLineNumbers() { const textarea=$("#editor-content"), gutter=$("#editor-line-numbers"); if(!textarea||!gutter)return; const lines=Math.max(1,textarea.value.split("\n").length); gutter.textContent=Array.from({length:lines},(_,index)=>index+1).join("\n"); gutter.scrollTop=textarea.scrollTop; }
function insertEditorTab(event) { if(event.key!=="Tab")return; event.preventDefault(); const textarea=event.currentTarget,start=textarea.selectionStart,end=textarea.selectionEnd; textarea.setRangeText("  ",start,end,"end"); textarea.dispatchEvent(new Event("input",{bubbles:true})); }
'''
js=replace_once(js,'async function openEditor(path) {',editor_helpers+'async function openEditor(path) {',"editor helpers")
js=replace_once(js,'$("#editor-path").textContent = data.path;\n$("#editor-content").value = data.content;\nclearError("#editor-error");','$("#editor-path").textContent = data.path;\n$("#editor-name").textContent = data.name || data.path.split("/").filter(Boolean).pop() || "Edit text file";\n$("#editor-content").value = data.content;\n$("#editor-status").textContent = "Ready";\nupdateEditorLineNumbers();\nclearError("#editor-error");',"editor open polish")
editor_marker='$("#editor-form").addEventListener("submit", async (event) => {'
editor_listeners=r'''$("#editor-content").addEventListener("input",()=>{$("#editor-status").textContent="Modified";updateEditorLineNumbers();});
$("#editor-content").addEventListener("scroll",updateEditorLineNumbers);
$("#editor-content").addEventListener("keydown",(event)=>{if(event.key==="Tab"){insertEditorTab(event);return;}if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="s"){event.preventDefault();$("#editor-form").requestSubmit();}});
'''
js=replace_once(js,editor_marker,editor_listeners+editor_marker,"editor listeners")
js=replace_once(js,'state.editorHash = data.sha256;\ncloseDialog($("#editor-dialog"));','state.editorHash = data.sha256;\n$("#editor-status").textContent = "Saved";\ncloseDialog($("#editor-dialog"));',"editor saved status")
js=js.replace('\n$("#recycle-bin-refresh").addEventListener("click", loadRecycleBin);','')
if "window.confirm(" in js: raise SystemExit("native browser confirm remains after V1.5.4 patch")
write(js_path,js)

css+=r'''

/* V1.5.4 File Manager visual polish */
.file-kind{flex:0 0 auto}.file-kind svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}.file-kind.file-type-folder{color:#d49618;background:rgba(244,181,57,.12)}.file-kind.file-type-image{color:#466bd9;background:rgba(70,107,217,.10)}.file-kind.file-type-code{color:#14836a;background:rgba(20,131,106,.09)}.file-kind.file-type-text{color:#2f78c8;background:rgba(47,120,200,.09)}.file-kind.file-type-archive{color:#b47120;background:rgba(180,113,32,.10)}.file-kind.file-type-database{color:#7957b7;background:rgba(121,87,183,.10)}.file-kind.file-type-certificate{color:#59718f;background:rgba(89,113,143,.10)}.file-kind.file-type-link{color:#69819d;background:rgba(105,129,157,.10)}
.destination-icon svg,.destination-browse svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.confirm-action-card{gap:14px!important}.confirm-action-message{margin:0!important;color:var(--text);font-size:14px;line-height:1.55}.confirm-action-message strong{overflow-wrap:anywhere}.confirmation-modal{width:min(92vw,430px)}.confirmation-card{gap:16px;padding:18px}.confirmation-message{margin:0!important;color:#385778;font-size:14px;line-height:1.55}
.editor-modal{width:min(96vw,1180px);max-height:92vh;overflow:hidden}.editor-card{height:min(88vh,820px);max-height:88vh;display:grid;grid-template-rows:auto minmax(0,1fr) auto auto;gap:10px;padding:14px;overflow:hidden}.editor-header{display:flex;align-items:center;justify-content:space-between;gap:12px;min-width:0}.editor-title-group{min-width:0;display:flex;align-items:center;gap:10px}.editor-file-icon{width:38px;height:38px;flex:0 0 auto;display:grid;place-items:center;border-radius:10px;color:#1767e8;background:rgba(65,160,244,.11)}.editor-file-icon svg{width:21px;height:21px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}.editor-title-group h3{margin:0!important;font-size:17px!important;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.editor-path{max-width:min(70vw,760px);margin:2px 0 0!important;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font-size:10px}.editor-header-tools{display:flex;align-items:center;gap:8px}.editor-encoding{padding:5px 8px;border:1px solid var(--line);border-radius:7px;color:#53708e;background:#f7faff;font-size:10px;font-weight:800}.editor-workspace{min-height:0;display:grid;grid-template-columns:auto minmax(0,1fr);overflow:hidden;border:1px solid var(--line-strong);border-radius:11px;background:#fbfdff}.editor-line-numbers{min-width:48px;height:100%;margin:0;overflow:hidden;padding:12px 10px 12px 8px;border-right:1px solid var(--line);color:#91a4bb;background:#f2f6fb;text-align:right;user-select:none;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;line-height:1.6}#editor-content{width:100%;height:100%;min-height:0;resize:none;overflow:auto;padding:12px 14px;border:0;border-radius:0;background:#fff;box-shadow:none!important;font-size:12px;line-height:1.6;tab-size:2}#editor-content:focus{border:0;background:#fff;box-shadow:none!important}.editor-footer{display:flex;align-items:center;justify-content:space-between;gap:12px}.editor-status{color:var(--muted);font-size:11px}.editor-footer .modal-actions{margin:0}
.image-preview-modal{width:min(96vw,1200px)!important;max-height:92vh!important;overflow:hidden!important}.image-preview-card{height:min(90vh,900px);max-height:90vh;display:grid;grid-template-rows:auto minmax(0,1fr) auto auto;gap:10px;padding:14px;overflow:hidden}.image-preview-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;min-width:0}.image-preview-header>div{min-width:0}.image-preview-header h3{margin:0!important;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:17px!important}.image-preview-path{max-width:min(78vw,940px)!important}.image-preview-stage{width:100%;min-width:0;min-height:0!important;max-height:none!important;height:100%;overflow:hidden!important;padding:10px!important;border-radius:11px}.image-preview-stage img{display:block;width:auto;height:auto;max-width:100%!important;max-height:100%!important;object-fit:contain;box-shadow:none!important}.image-preview-footer{display:flex;align-items:center;justify-content:flex-end;gap:10px}
.recycle-bin-modal{width:min(96vw,1180px)!important;max-height:90vh;overflow:hidden}.recycle-bin-card{height:min(84vh,760px);display:grid;grid-template-rows:auto minmax(0,1fr) auto;gap:12px;padding:16px;overflow:hidden}.recycle-bin-header{display:flex;align-items:center;justify-content:space-between;gap:12px}.recycle-bin-title{min-width:0;display:flex;align-items:center;gap:10px}.recycle-bin-title-icon,.recycle-empty-icon{display:grid;place-items:center;color:#376b9d}.recycle-bin-title-icon{width:38px;height:38px;border-radius:10px;background:rgba(65,160,244,.10)}.recycle-bin-title-icon svg,.recycle-empty-icon svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}.recycle-bin-title h3{margin:0!important;font-size:18px!important}.recycle-bin-title p{margin:2px 0 0!important;color:var(--muted);font-size:11px}.recycle-bin-browser{min-height:0;display:grid;grid-template-rows:auto minmax(0,1fr);overflow:hidden;border:1px solid var(--line);border-radius:11px;background:#fff}.recycle-bin-columns,.recycle-bin-row{display:grid;grid-template-columns:minmax(220px,1.5fr) minmax(220px,1.3fr) 160px 130px 210px;align-items:center;gap:12px}.recycle-bin-columns{padding:9px 12px;border-bottom:1px solid var(--line);color:#7890ad;background:#f6f9fd;font-size:10px;font-weight:850;text-transform:uppercase;letter-spacing:.06em}.recycle-bin-list{max-height:none!important;min-height:0;overflow:auto;display:block!important}.recycle-bin-row{padding:9px 12px!important;border:0!important;border-bottom:1px solid #edf2f8!important;border-radius:0!important;background:#fff!important}.recycle-bin-row:hover{background:#f9fbfe!important}.recycle-bin-name-cell{min-width:0;display:flex;align-items:center;gap:9px}.recycle-bin-name-cell strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.recycle-bin-cell{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#5f7895;font-size:11px}.recycle-bin-path{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10px}.recycle-bin-actions{display:flex;justify-content:flex-end;gap:6px}.recycle-action-button{min-height:32px;padding:5px 9px;border:1px solid var(--line-strong);border-radius:7px;color:#31577f;background:#fff;font-size:10px;font-weight:800}.recycle-action-button:hover{background:rgba(99,204,248,.10)}.recycle-action-button.danger{color:#cf303a;border-color:rgba(227,61,69,.22);background:rgba(227,61,69,.04)}.recycle-action-button.danger:hover{background:rgba(227,61,69,.09)}.recycle-bin-empty{min-height:0;height:100%;display:grid;place-items:center;align-content:center;gap:7px;color:var(--muted)}.recycle-bin-empty[hidden]{display:none!important}.recycle-bin-empty strong{color:#4d6886;font-size:14px}.recycle-bin-empty small{font-size:11px}.recycle-empty-icon{width:52px;height:52px;border-radius:14px;background:#f2f7fc}
@media(max-width:900px){.recycle-bin-columns{display:none}.recycle-bin-row{grid-template-columns:minmax(0,1fr) auto;gap:6px 10px}.recycle-bin-name-cell{grid-column:1}.recycle-bin-path,.recycle-bin-cell{grid-column:1}.recycle-bin-actions{grid-column:2;grid-row:1 / span 4;flex-direction:column;align-self:center}}
@media(max-width:680px){.editor-modal,.image-preview-modal,.recycle-bin-modal{width:calc(100vw - 16px)!important;max-height:94vh!important}.editor-card{height:90vh;max-height:90vh;padding:10px}.editor-line-numbers{min-width:40px;padding-inline:6px}.editor-encoding{display:none}.editor-path{max-width:70vw}.image-preview-card{height:88vh;max-height:88vh;padding:10px}.image-preview-stage{padding:6px!important}.image-preview-path{max-width:72vw!important}.recycle-bin-card{height:88vh;padding:10px}.recycle-bin-actions{grid-column:1;grid-row:auto;flex-direction:row;justify-content:flex-start}.recycle-bin-row{grid-template-columns:1fr}.recycle-bin-name-cell,.recycle-bin-path,.recycle-bin-cell,.recycle-bin-actions{grid-column:1}.recycle-bin-title p{display:none}}
'''
write(css_path,css)

for rel in (assets_test_path,app_test_path): write(rel,read(rel).replace("Version 1.5.3","Version 1.5.4"))
assets=read(assets_test_path)
if "TestFileManagerV154PolishedEditorPreviewRecycleConfirmations" not in assets:
    assets+=r'''

func TestFileManagerV154PolishedEditorPreviewRecycleConfirmations(t *testing.T) {
	htmlBytes, err := Assets.ReadFile("static/index.html"); if err != nil { t.Fatal(err) }
	javascriptBytes, err := Assets.ReadFile("static/app.js"); if err != nil { t.Fatal(err) }
	cssBytes, err := Assets.ReadFile("static/app.css"); if err != nil { t.Fatal(err) }
	html, javascript, css := string(htmlBytes), string(javascriptBytes), string(cssBytes)
	for _, fragment := range []string{`id="editor-line-numbers"`, `id="confirmation-dialog"`, `recycle-bin-columns`, `Are you sure you want to move`, `id="recycle-bin-count"`} { if !strings.Contains(html, fragment) { t.Fatalf("V1.5.4 UI is missing %q", fragment) } }
	if strings.Contains(html, "Maximum 1 MB. If the file changes elsewhere after opening, saving is rejected until you reopen it.") { t.Fatal("obsolete editor note is still present") }
	if strings.Contains(html, `id="recycle-bin-refresh"`) { t.Fatal("Recycle Bin refresh button should not exist") }
	for _, fragment := range []string{`showPanelConfirmation`, `fileVisualType`, `buildFileIcon`, `updateEditorLineNumbers`, `Confirm update`, `Delete permanently?`} { if !strings.Contains(javascript, fragment) { t.Fatalf("V1.5.4 behavior is missing %q", fragment) } }
	if strings.Contains(javascript, "window.confirm(") { t.Fatal("native browser confirm remains") }
	for _, fragment := range []string{`.editor-workspace`, `.image-preview-card`, `.recycle-bin-columns`, `.file-kind.file-type-folder`, `.confirmation-modal`} { if !strings.Contains(css, fragment) { t.Fatalf("V1.5.4 styling is missing %q", fragment) } }
}
'''
write(assets_test_path,assets)
print("Applied HYZoraX Control Panel V1.5.4 File Manager UI polish")
