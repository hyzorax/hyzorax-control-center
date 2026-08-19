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

html_path="internal/web/static/index.html"
js_path="internal/web/static/app.js"
css_path="internal/web/static/app.css"
assets_path="internal/web/assets_test.go"

html=read(html_path)
html=replace_once(html,"Version 1.5.5","Version 1.5.6","version")
editor=r'''<dialog id="editor-dialog" class="modal editor-modal">
      <form id="editor-form" class="modal-card editor-card">
        <div class="editor-header">
          <div class="editor-title-group"><span class="editor-file-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M7 3.75h7l3 3V20.25H7z"></path><path d="M14 3.75v3h3"></path><path d="M9.5 11h5M9.5 14h5M9.5 17h3.5"></path></svg></span><div><h3 id="editor-name">Edit text file</h3><p class="editor-path"><code id="editor-path"></code></p></div></div>
          <div class="editor-header-tools"><button id="editor-find-button" type="button" class="editor-tool-button" aria-label="Find in file" title="Find (Ctrl+F)"><svg viewBox="0 0 24 24"><circle cx="10.8" cy="10.8" r="5.8"></circle><path d="m15.2 15.2 4.2 4.2"></path></svg></button><button id="editor-maximize-button" type="button" class="editor-tool-button" aria-label="Maximize editor" title="Maximize"><svg class="maximize-icon" viewBox="0 0 24 24"><path d="M8 4H4v4M16 4h4v4M8 20H4v-4M16 20h4v-4"></path></svg><svg class="restore-icon" viewBox="0 0 24 24"><path d="M8 7h9v9H8z"></path><path d="M6 17H4V5h12v2"></path></svg></button><span class="editor-encoding">UTF-8</span><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        </div>
        <div id="editor-find-bar" class="editor-find-bar" hidden><span class="editor-find-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="10.8" cy="10.8" r="5.8"></circle><path d="m15.2 15.2 4.2 4.2"></path></svg></span><input id="editor-find-input" type="search" autocomplete="off" spellcheck="false" placeholder="Find in file" aria-label="Find in file"><span id="editor-find-count" class="editor-find-count">0 / 0</span><button id="editor-find-previous" type="button" class="editor-find-nav" aria-label="Previous match" title="Previous match (Shift+Enter)">↑</button><button id="editor-find-next" type="button" class="editor-find-nav" aria-label="Next match" title="Next match (Enter)">↓</button><button id="editor-find-close" type="button" class="editor-find-close" aria-label="Close find" title="Close find">×</button></div>
        <div class="editor-workspace"><pre id="editor-line-numbers" class="editor-line-numbers" aria-hidden="true">1</pre><textarea id="editor-content" name="content" spellcheck="false" aria-label="File contents"></textarea></div>
        <div id="editor-error" class="alert" role="alert" hidden></div>
        <div class="editor-footer"><span id="editor-status" class="editor-status">Ready · Ln 1, Col 1</span><div class="editor-shortcuts"><span>Ctrl+F Find</span><span>Ctrl+S Save</span><span>F3 Next</span></div><div class="modal-actions"><button type="button" class="ghost compact" data-close-dialog>Cancel</button><button type="submit" class="primary compact-primary">Save</button></div></div>
      </form>
    </dialog>'''
html=sub_once(html,r'<dialog id="editor-dialog" class="modal editor-modal">.*?</dialog>',editor,"editor dialog")
write(html_path,html)

js=read(js_path)
helpers=r'''
const editorFindState={query:"",matches:[],index:-1};
function updateEditorCursorStatus(){const editor=$("#editor-content");if(!editor)return;const pos=editor.selectionStart||0;const before=editor.value.slice(0,pos);const lines=before.split("\n");$("#editor-status").textContent=`Ready · Ln ${lines.length}, Col ${lines[lines.length-1].length+1}`;}
function collectEditorFindMatches(){const editor=$("#editor-content"),input=$("#editor-find-input"),query=input.value;editorFindState.query=query;editorFindState.matches=[];editorFindState.index=-1;if(!query){$("#editor-find-count").textContent="0 / 0";return;}const haystack=editor.value.toLocaleLowerCase(),needle=query.toLocaleLowerCase();let cursor=0;while(cursor<=haystack.length-needle.length){const index=haystack.indexOf(needle,cursor);if(index<0)break;editorFindState.matches.push(index);cursor=index+Math.max(needle.length,1);if(editorFindState.matches.length>=10000)break;}$("#editor-find-count").textContent=editorFindState.matches.length?`0 / ${editorFindState.matches.length}`:"0 / 0";}
function selectEditorFindMatch(direction=1){if($("#editor-find-input").value!==editorFindState.query)collectEditorFindMatches();const matches=editorFindState.matches;if(!matches.length)return;if(editorFindState.index<0)editorFindState.index=direction<0?matches.length-1:0;else editorFindState.index=(editorFindState.index+direction+matches.length)%matches.length;const start=matches[editorFindState.index],end=start+editorFindState.query.length,editor=$("#editor-content");editor.setSelectionRange(start,end);const line=editor.value.slice(0,start).split("\n").length,lineHeight=parseFloat(getComputedStyle(editor).lineHeight)||20;editor.scrollTop=Math.max(0,(line-4)*lineHeight);$("#editor-line-numbers").scrollTop=editor.scrollTop;$("#editor-find-count").textContent=`${editorFindState.index+1} / ${matches.length}`;updateEditorCursorStatus();}
function openEditorFind(){const bar=$("#editor-find-bar"),input=$("#editor-find-input"),editor=$("#editor-content");bar.hidden=false;if(!input.value&&editor.selectionStart!==editor.selectionEnd)input.value=editor.value.slice(editor.selectionStart,editor.selectionEnd).replace(/\n/g," ");collectEditorFindMatches();input.focus();input.select();}
function closeEditorFind(){$("#editor-find-bar").hidden=true;$("#editor-content").focus({preventScroll:true});}
function resetEditorFind(){editorFindState.query="";editorFindState.matches=[];editorFindState.index=-1;const input=$("#editor-find-input");if(input)input.value="";const count=$("#editor-find-count");if(count)count.textContent="0 / 0";const bar=$("#editor-find-bar");if(bar)bar.hidden=true;}
function toggleEditorMaximize(){const dialog=$("#editor-dialog"),maximized=dialog.classList.toggle("editor-maximized"),button=$("#editor-maximize-button");button.setAttribute("aria-label",maximized?"Restore editor":"Maximize editor");button.title=maximized?"Restore":"Maximize";requestAnimationFrame(()=>{updateEditorLineNumbers();updateEditorCursorStatus();$("#editor-content").focus({preventScroll:true});});}
'''
if "const editorFindState" not in js:
    js=replace_once(js,"function updateEditorLineNumbers() {",helpers+"function updateEditorLineNumbers() {","editor helpers")

# Reset editor chrome on open without depending on the surrounding implementation.
js=js.replace('openDialog("#editor-dialog");','resetEditorFind();\n$("#editor-dialog").classList.remove("editor-maximized");\nopenDialog("#editor-dialog");\nupdateEditorCursorStatus();',1)

wiring=r'''

/* V1.5.6 editor keyboard + toolbar wiring */
$("#editor-find-button").addEventListener("click",openEditorFind);
$("#editor-maximize-button").addEventListener("click",toggleEditorMaximize);
$("#editor-find-close").addEventListener("click",closeEditorFind);
$("#editor-find-next").addEventListener("click",()=>selectEditorFindMatch(1));
$("#editor-find-previous").addEventListener("click",()=>selectEditorFindMatch(-1));
$("#editor-find-input").addEventListener("input",collectEditorFindMatches);
$("#editor-find-input").addEventListener("keydown",(event)=>{if(event.key==="Enter"){event.preventDefault();selectEditorFindMatch(event.shiftKey?-1:1);}else if(event.key==="Escape"){event.preventDefault();closeEditorFind();}});
$("#editor-content").addEventListener("input",()=>{updateEditorCursorStatus();if(!$("#editor-find-bar").hidden)collectEditorFindMatches();});
$("#editor-content").addEventListener("click",updateEditorCursorStatus);
$("#editor-content").addEventListener("keyup",updateEditorCursorStatus);
document.addEventListener("keydown",(event)=>{const dialog=$("#editor-dialog");if(!dialog||!dialog.open)return;if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="f"){event.preventDefault();event.stopPropagation();openEditorFind();return;}if(event.key==="F3"){event.preventDefault();event.stopPropagation();selectEditorFindMatch(event.shiftKey?-1:1);}},true);
'''
if "V1.5.6 editor keyboard + toolbar wiring" not in js: js+=wiring
write(js_path,js)

css=read(css_path)
css+=r'''

/* V1.5.6 aaPanel-inspired editor workflow in HYZoraX styling */
.editor-modal{width:min(96vw,1450px);max-height:94vh}.editor-card{display:flex;flex-direction:column;width:100%;height:min(88vh,860px);min-height:560px;padding:0;overflow:hidden}.editor-header{padding:.9rem 1rem;border-bottom:1px solid var(--line);background:rgba(255,255,255,.98)}.editor-header-tools{gap:.42rem}.editor-tool-button{width:36px;height:36px;display:grid;place-items:center;border:1px solid var(--line);border-radius:9px;color:#54779f;background:#f8fbff}.editor-tool-button:hover{color:var(--blue-deep);border-color:var(--line-strong);background:rgba(99,204,248,.12)}.editor-tool-button svg{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.editor-tool-button .restore-icon{display:none}.editor-maximized .editor-tool-button .maximize-icon{display:none}.editor-maximized .editor-tool-button .restore-icon{display:block}.editor-find-bar{flex:0 0 auto;display:grid;grid-template-columns:22px minmax(160px,1fr) auto 34px 34px 34px;align-items:center;gap:.35rem;padding:.55rem .75rem;border-bottom:1px solid var(--line);background:#f7fbff}.editor-find-bar[hidden]{display:none!important}.editor-find-icon{display:grid;place-items:center;color:#5f7fa3}.editor-find-icon svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.8}.editor-find-bar input{min-width:0;padding:.48rem .65rem;border:1px solid var(--line-strong);border-radius:7px;background:white;font:inherit;color:var(--ink)}.editor-find-bar input:focus{outline:2px solid rgba(47,137,246,.18);border-color:#3b8ef5}.editor-find-count{min-width:64px;text-align:center;color:var(--muted);font-size:.64rem;font-weight:800;font-variant-numeric:tabular-nums}.editor-find-nav,.editor-find-close{width:32px;height:32px;border:1px solid var(--line);border-radius:7px;color:#55789f;background:white;font-weight:900}.editor-find-nav:hover,.editor-find-close:hover{color:var(--blue-deep);background:rgba(99,204,248,.12)}.editor-workspace{flex:1 1 auto;min-height:0;border:0;border-radius:0}.editor-line-numbers,#editor-content{height:100%;min-height:0;max-height:none}.editor-footer{flex:0 0 auto;display:grid;grid-template-columns:minmax(140px,1fr) auto auto;align-items:center;gap:.85rem;padding:.7rem 1rem;border-top:1px solid var(--line);background:rgba(255,255,255,.98)}.editor-shortcuts{display:flex;align-items:center;gap:.7rem;color:#8196af;font-size:.58rem;font-weight:750}.editor-maximized{width:calc(100vw - 20px)!important;max-width:none!important;height:calc(100dvh - 20px)!important;max-height:none!important;margin:10px!important}.editor-maximized .editor-card{width:100%;height:100%;max-height:none;min-height:0;border-radius:14px}.editor-maximized::backdrop{background:rgba(16,42,77,.34)}
@media(max-width:760px){.editor-modal{width:100%;max-width:none;max-height:96vh;margin:auto 0 0}.editor-card{height:90vh;min-height:0;border-radius:18px 18px 0 0}.editor-title-group .editor-path{max-width:54vw}.editor-find-bar{grid-template-columns:20px minmax(100px,1fr) auto 32px 32px 32px;padding:.5rem}.editor-find-count{min-width:48px}.editor-shortcuts{display:none}.editor-footer{grid-template-columns:1fr auto}.editor-maximized{width:100vw!important;height:100dvh!important;margin:0!important;border-radius:0}.editor-maximized .editor-card{border-radius:0}}
'''
write(css_path,css)

assets=read(assets_path)
if "TestV156EditorWorkflowAssets" not in assets:
    assets+=r'''

func TestV156EditorWorkflowAssets(t *testing.T) {
	htmlBytes, err := staticFiles.ReadFile("static/index.html"); if err != nil { t.Fatal(err) }
	javascriptBytes, err := staticFiles.ReadFile("static/app.js"); if err != nil { t.Fatal(err) }
	cssBytes, err := staticFiles.ReadFile("static/app.css"); if err != nil { t.Fatal(err) }
	html, javascript, css := string(htmlBytes), string(javascriptBytes), string(cssBytes)
	for _, f := range []string{`Version 1.5.6`,`id="editor-find-bar"`,`id="editor-find-input"`,`id="editor-maximize-button"`,`Ctrl+F Find`} { if !strings.Contains(html,f) { t.Fatalf("V1.5.6 editor HTML missing %q",f) } }
	for _, f := range []string{`openEditorFind`,`toggleEditorMaximize`,`selectEditorFindMatch`,`event.key.toLowerCase()==="f"`,`event.key==="F3"`} { if !strings.Contains(javascript,f) { t.Fatalf("V1.5.6 editor JS missing %q",f) } }
	for _, f := range []string{`.editor-find-bar`,`.editor-maximized`,`.editor-tool-button`,`.editor-shortcuts`} { if !strings.Contains(css,f) { t.Fatalf("V1.5.6 editor CSS missing %q",f) } }
}
'''
write(assets_path,assets)
print("Applied HYZoraX Control Panel V1.5.6 editor maximize + find workflow")
