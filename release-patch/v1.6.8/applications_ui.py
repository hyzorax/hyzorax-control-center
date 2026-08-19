#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: applications_ui.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()

def read(rel): return (root / rel).read_text(encoding="utf-8")
def write(rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
def replace_once(rel, old, new, label):
    text = read(rel)
    if old not in text:
        raise SystemExit(f"{label}: marker not found in {rel}")
    write(rel, text.replace(old, new, 1))
def sub_once(rel, pattern, replacement, label):
    text = read(rel)
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    write(rel, updated)

# ---------- HTML: activate Applications and add its view ----------
html_path = "internal/web/static/index.html"
html = read(html_path)
old_nav = '<a href="#applications"><span>⬡</span>Applications <em>Soon</em></a>'
new_nav = '<a href="#applications" data-view="applications"><span>⬡</span>Applications</a>'
if old_nav not in html:
    raise SystemExit("Applications sidebar marker not found")
html = html.replace(old_nav, new_nav, 1)

applications_view = r'''        <section id="applications-view" class="content applications-view" hidden>
          <div class="applications-heading">
            <div><p class="eyebrow">Application runtimes</p><h1>Applications</h1><p class="muted">Install and verify HYZoraX-managed application runtimes.</p></div>
            <span class="badge">Guarded installers</span>
          </div>
          <div class="application-grid">
            <article id="node24-card" class="application-card">
              <div class="application-card-head"><div class="application-icon node-icon">JS</div><div><h3>Node.js 24 LTS</h3><p>HYZoraX-managed runtime</p></div><span id="node24-status" class="application-status neutral">Checking…</span></div>
              <div class="application-meta"><div><span>Target version</span><strong>24.19.0</strong></div><div><span>Installed version</span><strong id="node24-version">—</strong></div></div>
              <p id="node24-detail" class="application-detail">Checking server status…</p>
              <div class="application-actions"><button id="node24-install-button" type="button" class="primary compact-primary" disabled>Install</button></div>
            </article>
            <article id="composer-card" class="application-card">
              <div class="application-card-head"><div class="application-icon composer-icon">C</div><div><h3>Composer</h3><p>PHP dependency manager</p></div><span id="composer-status" class="application-status neutral">Checking…</span></div>
              <div class="application-meta"><div><span>Target version</span><strong>2.10.2</strong></div><div><span>Installed version</span><strong id="composer-version">—</strong></div></div>
              <p id="composer-detail" class="application-detail">Requires HYZoraX PHP 8.4.</p>
              <div class="application-actions"><button id="composer-install-button" type="button" class="primary compact-primary" disabled>Install</button></div>
            </article>
          </div>
          <div id="applications-error" class="alert" role="alert" hidden></div>
        </section>

'''
files_marker = '        <section id="files-view" class="content" hidden>'
if files_marker not in html:
    raise SystemExit("files view marker not found")
html = html.replace(files_marker, applications_view + files_marker, 1)
html = html.replace("Version 1.6.7", "Version 1.6.8")
write(html_path, html)

# ---------- Backend Applications API ----------
app_go = "internal/httpapi/app.go"
app = read(app_go)
route_marker = '\tmux.Handle("POST /api/v1/update/apply", a.requireAuth(http.HandlerFunc(a.handleUpdateApply)))\n'
new_routes = route_marker + '\tmux.Handle("GET /api/v1/applications/status", a.requireAuth(http.HandlerFunc(a.handleApplicationsStatus)))\n\tmux.Handle("POST /api/v1/applications/node24/install", a.requireAuth(http.HandlerFunc(a.handleNode24Install)))\n\tmux.Handle("POST /api/v1/applications/composer/install", a.requireAuth(http.HandlerFunc(a.handleComposerInstall)))\n'
if route_marker not in app:
    raise SystemExit("application route insertion marker not found")
app = app.replace(route_marker, new_routes, 1)
write(app_go, app)

applications_go = r'''package httpapi

import (
    "context"
    "net/http"
    "time"

    "github.com/hyzorax/hyzorax-control/internal/cryptoutil"
    "github.com/hyzorax/hyzorax-control/internal/helper"
)

type applicationState struct {
    ID            string `json:"id"`
    Name          string `json:"name"`
    TargetVersion string `json:"target_version"`
    Version       string `json:"version,omitempty"`
    NPMVersion    string `json:"npm_version,omitempty"`
    Status        string `json:"status"`
    Installed     bool   `json:"installed"`
    Healthy       bool   `json:"healthy"`
    Installable   bool   `json:"installable"`
    Detail        string `json:"detail"`
    Dependency    string `json:"dependency,omitempty"`
}

func (a *App) applicationHelperCall(ctx context.Context, actorID, correlationID, action, target string, longRunning bool) (helper.Response, error) {
    callID, err := cryptoutil.RandomID()
    if err != nil { return helper.Response{}, err }
    request := helper.Request{ID: callID, CorrelationID: correlationID, ActorID: actorID, Action: action, Target: target}
    if longRunning {
        client := helper.Client{Socket: a.config.Helper.Socket, Timeout: 12 * time.Minute}
        return client.Call(ctx, request)
    }
    return a.helper.Call(ctx, request)
}

func applicationStateFromResponses(id string, health, preflight helper.Response) applicationState {
    state := applicationState{ID: id, Status: "blocked", Installable: false}
    switch id {
    case "node24":
        state.Name = "Node.js 24 LTS"
        state.TargetVersion = "24.19.0"
    case "composer":
        state.Name = "Composer"
        state.TargetVersion = "2.10.2"
        state.Dependency = "PHP 8.4"
    }
    if health.OK && health.Error == nil {
        state.Status = "installed"
        state.Installed = true
        state.Healthy = true
        state.Installable = false
        state.Detail = "Installed and healthy."
        if version, ok := health.Data["version"].(string); ok { state.Version = version }
        if npm, ok := health.Data["npm_version"].(string); ok { state.NPMVersion = npm }
        return state
    }
    if preflight.OK && preflight.Error == nil {
        state.Status = "not_installed"
        state.Installable = true
        state.Detail = "Ready to install."
        return state
    }
    if preflight.Error == nil {
        state.Detail = "Status could not be determined."
        return state
    }
    switch preflight.Error.Code {
    case "component_exists":
        state.Status = "attention"
        state.Installed = true
        state.Detail = "HYZoraX-managed files exist, but the health check did not pass."
    case "dependency_missing":
        state.Status = "dependency"
        state.Detail = preflight.Error.Message
    case "path_conflict":
        state.Status = "conflict"
        state.Detail = preflight.Error.Message
    case "unsupported_os", "unsupported_arch":
        state.Status = "unsupported"
        state.Detail = preflight.Error.Message
    default:
        state.Detail = preflight.Error.Message
    }
    return state
}

func (a *App) inspectApplication(request *http.Request, id, healthAction, preflightAction string) (applicationState, error) {
    session := currentSession(request.Context())
    correlationID := requestID(request.Context())
    health, err := a.applicationHelperCall(request.Context(), session.User.ID, correlationID, healthAction, id, false)
    if err != nil { return applicationState{}, err }
    if health.OK && health.Error == nil { return applicationStateFromResponses(id, health, helper.Response{}), nil }
    preflight, err := a.applicationHelperCall(request.Context(), session.User.ID, correlationID, preflightAction, id, false)
    if err != nil { return applicationState{}, err }
    return applicationStateFromResponses(id, health, preflight), nil
}

func (a *App) handleApplicationsStatus(writer http.ResponseWriter, request *http.Request) {
    node, err := a.inspectApplication(request, "node24", "installer.node24.health", "installer.node24.preflight")
    if err != nil {
        writeError(writer, http.StatusServiceUnavailable, "applications_status_unavailable", "Application status could not be read from the privileged helper.")
        return
    }
    composer, err := a.inspectApplication(request, "composer", "installer.composer.health", "installer.composer.preflight")
    if err != nil {
        writeError(writer, http.StatusServiceUnavailable, "applications_status_unavailable", "Application status could not be read from the privileged helper.")
        return
    }
    writeJSON(writer, http.StatusOK, map[string]any{"node24": node, "composer": composer})
}

func (a *App) installApplication(writer http.ResponseWriter, request *http.Request, id, action string) {
    session := currentSession(request.Context())
    response, err := a.applicationHelperCall(request.Context(), session.User.ID, requestID(request.Context()), action, id, true)
    if err != nil {
        a.audit(request, action, id, "helper_unavailable", nil)
        writeError(writer, http.StatusServiceUnavailable, "helper_unavailable", "Privileged installer helper is unavailable.")
        return
    }
    if !response.OK || response.Error != nil {
        code, message := "application_install_failed", "Application installation failed."
        status := http.StatusInternalServerError
        if response.Error != nil {
            code, message = response.Error.Code, response.Error.Message
            switch code {
            case "component_exists", "path_conflict", "dependency_missing": status = http.StatusConflict
            case "unsupported_os", "unsupported_arch", "invalid_request": status = http.StatusBadRequest
            }
        }
        a.audit(request, action, id, "failed", map[string]any{"code": code})
        writeError(writer, status, code, message)
        return
    }
    a.audit(request, action, id, "success", map[string]any{"version": response.Data["version"]})
    writeJSON(writer, http.StatusOK, response.Data)
}

func (a *App) handleNode24Install(writer http.ResponseWriter, request *http.Request) {
    a.installApplication(writer, request, "node24", "installer.node24.install")
}

func (a *App) handleComposerInstall(writer http.ResponseWriter, request *http.Request) {
    a.installApplication(writer, request, "composer", "installer.composer.install")
}
'''
write("internal/httpapi/applications.go", applications_go)

applications_test = r'''package httpapi

import (
    "testing"
    "github.com/hyzorax/hyzorax-control/internal/helper"
)

func TestApplicationStateNodeReady(t *testing.T) {
    state := applicationStateFromResponses("node24", helper.Response{OK:false, Error:&helper.Error{Code:"version_check_failed",Message:"not installed"}}, helper.Response{OK:true,Data:map[string]any{"ready":true}})
    if state.Status!="not_installed" || !state.Installable || state.Installed { t.Fatalf("unexpected state: %#v", state) }
}
func TestApplicationStateComposerDependency(t *testing.T) {
    state := applicationStateFromResponses("composer", helper.Response{OK:false,Error:&helper.Error{Code:"command_check_failed",Message:"missing"}}, helper.Response{OK:false,Error:&helper.Error{Code:"dependency_missing",Message:"HYZoraX PHP 8.4 is required before Composer can be installed"}})
    if state.Status!="dependency" || state.Installable || state.Dependency!="PHP 8.4" { t.Fatalf("unexpected state: %#v", state) }
}
func TestApplicationStateInstalled(t *testing.T) {
    state := applicationStateFromResponses("node24", helper.Response{OK:true,Data:map[string]any{"version":"24.19.0","npm_version":"11.6.2"}}, helper.Response{})
    if !state.Installed || !state.Healthy || state.Version!="24.19.0" || state.NPMVersion!="11.6.2" { t.Fatalf("unexpected state: %#v", state) }
}
'''
write("internal/httpapi/applications_test.go", applications_test)

# ---------- JavaScript: Applications routing, status, install ----------
js_path = "internal/web/static/app.js"
js = read(js_path)
js = js.replace('updateBusy: false\n};', 'updateBusy: false,\napplicationsBusy: false\n};', 1)

old_show = 'await switchView(window.location.hash === "#files" ? "files" : "overview");'
new_show = 'await switchView(viewFromHash());'
if old_show not in js:
    raise SystemExit("showDashboard view marker not found")
js = js.replace(old_show, new_show, 1)

switch_pattern = r'async function switchView\(view\) \{.*?\n\}\nfunction stopDashboardLive\(\) \{'
new_switch = r'''function viewFromHash(){
const value=window.location.hash.replace(/^#/,"");
return ["overview","applications","files"].includes(value)?value:"overview";
}
async function switchView(view) {
stopDashboardLive();
const selected=["applications","files"].includes(view)?view:"overview";
state.currentView=selected;
$("#overview-view").hidden=selected!=="overview";
$("#applications-view").hidden=selected!=="applications";
$("#files-view").hidden=selected!=="files";
document.querySelectorAll("[data-view]").forEach((link)=>link.classList.toggle("active",link.dataset.view===selected));
const meta={overview:["Control Panel","System overview","Refresh dashboard"],applications:["Software","Applications","Refresh applications"],files:["Server filesystem","File Manager","Refresh directory"]}[selected];
$("#workspace-eyebrow").textContent=meta[0];
$("#workspace-title").textContent=meta[1];
$("#refresh-button").title=meta[2];
$(".sidebar").classList.remove("open");
if(selected==="files") await loadFiles(state.filesLoaded?state.currentPath:"/");
else if(selected==="applications") await loadApplications();
else {await refreshDashboard();scheduleDashboardLive();}
}
function applicationStatusLabel(status){return {installed:"Installed",not_installed:"Not installed",dependency:"Dependency required",conflict:"Conflict",attention:"Needs attention",unsupported:"Unsupported",blocked:"Blocked"}[status]||"Unknown";}
function renderApplication(prefix,data){
const badge=$(`#${prefix}-status`),version=$(`#${prefix}-version`),detail=$(`#${prefix}-detail`),button=$(`#${prefix}-install-button`);
badge.textContent=applicationStatusLabel(data.status);badge.className=`application-status ${data.status||"neutral"}`;
version.textContent=data.version||"—";
detail.textContent=data.detail||"Status unavailable.";
if(prefix==="node24"&&data.npm_version) detail.textContent=`Installed and healthy · npm ${data.npm_version}`;
button.disabled=!data.installable||state.applicationsBusy;
button.textContent=data.installed?"Installed":"Install";
}
async function loadApplications(){
if(state.applicationsBusy)return;clearError("#applications-error");$("#refresh-button").disabled=true;
try{const data=await request("api/v1/applications/status");renderApplication("node24",data.node24||{});renderApplication("composer",data.composer||{});}
catch(error){if(error.status===401){showLogin();return}showError("#applications-error",error.message);}
finally{$("#refresh-button").disabled=false;}
}
async function installApplication(component,label){
const confirmed=await showPanelConfirmation({title:`Install ${label}?`,message:`HYZoraX will install the managed ${label} runtime on this server.`,confirmLabel:"Install"});if(!confirmed)return;
state.applicationsBusy=true;clearError("#applications-error");const button=$(`#${component}-install-button`);button.disabled=true;button.textContent="Installing…";
try{await request(`api/v1/applications/${component}/install`,{method:"POST"});showToast(`${label} installed successfully.`);}
catch(error){showError("#applications-error",error.message);}
finally{state.applicationsBusy=false;await loadApplications();}
}
function stopDashboardLive() {'''
updated, count = re.subn(switch_pattern, lambda _m: new_switch, js, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f"switchView replacement failed: {count}")
js = updated

old_refresh = '''$("#refresh-button").addEventListener("click", () => {
if (state.currentView === "files") loadFiles(state.currentPath);
else refreshDashboard();
});'''
new_refresh = '''$("#refresh-button").addEventListener("click", () => {
if (state.currentView === "files") loadFiles(state.currentPath);
else if (state.currentView === "applications") loadApplications();
else refreshDashboard();
});
$("#node24-install-button").addEventListener("click",()=>installApplication("node24","Node.js 24 LTS"));
$("#composer-install-button").addEventListener("click",()=>installApplication("composer","Composer"));'''
if old_refresh not in js:
    raise SystemExit("refresh wiring marker not found")
js = js.replace(old_refresh, new_refresh, 1)
old_hash = '''window.addEventListener("hashchange", () => {
if (state.user) switchView(window.location.hash === "#files" ? "files" : "overview");
});'''
new_hash = '''window.addEventListener("hashchange", () => {
if (state.user) switchView(viewFromHash());
});'''
if old_hash not in js:
    raise SystemExit("hashchange marker not found")
js = js.replace(old_hash, new_hash, 1)
write(js_path, js)

# ---------- CSS ----------
css_path = "internal/web/static/app.css"
css = read(css_path)
css += r'''
/* V1.6.8 Applications */
.applications-view{display:flex;flex-direction:column;gap:1.1rem}.applications-view[hidden]{display:none!important}.applications-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem}.applications-heading h1{margin:.12rem 0 .3rem;font-size:2rem;color:var(--ink)}.application-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.application-card{display:flex;flex-direction:column;gap:1rem;min-height:270px;padding:1.25rem;border:1px solid var(--line);border-radius:18px;background:rgba(255,255,255,.9);box-shadow:0 16px 38px rgba(35,86,145,.08)}.application-card-head{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:.8rem}.application-card-head h3{margin:0 0 .18rem;font-size:1.02rem;color:var(--ink)}.application-card-head p{margin:0;color:var(--muted);font-size:.64rem}.application-icon{width:44px;height:44px;display:grid;place-items:center;border-radius:12px;background:linear-gradient(145deg,#66d9f7,#1768eb);color:#fff;font-weight:900;box-shadow:0 8px 22px rgba(42,121,233,.2)}.composer-icon{font-size:1.05rem}.application-status{padding:.38rem .58rem;border-radius:999px;font-size:.57rem;font-weight:850;white-space:nowrap;border:1px solid var(--line);background:#f5f8fc;color:#6f87a2}.application-status.installed{color:#087c5a;background:#eafaf4;border-color:#b9ead9}.application-status.not_installed{color:#426b98;background:#f2f7fd}.application-status.dependency{color:#936a16;background:#fff8e5;border-color:#f0dfa7}.application-status.conflict,.application-status.attention{color:#b03b47;background:#fff1f2;border-color:#f1c4c9}.application-status.unsupported,.application-status.blocked{color:#7a627f;background:#f7f1f8}.application-meta{display:grid;grid-template-columns:1fr 1fr;gap:.65rem}.application-meta>div{padding:.72rem .78rem;border:1px solid var(--line);border-radius:11px;background:#f8fbff}.application-meta span{display:block;margin-bottom:.24rem;color:#8096af;font-size:.55rem;font-weight:800;text-transform:uppercase;letter-spacing:.06em}.application-meta strong{color:#254f79;font-size:.78rem}.application-detail{flex:1;margin:0;color:#637f9e;font-size:.67rem;line-height:1.55}.application-actions{display:flex;justify-content:flex-end}.application-actions .primary{min-width:105px}.application-actions .primary:disabled{opacity:.55;cursor:not-allowed;box-shadow:none}@media(max-width:900px){.application-grid{grid-template-columns:1fr}}@media(max-width:620px){.applications-heading{display:block}.applications-heading .badge{display:inline-flex;margin-top:.55rem}.application-card-head{grid-template-columns:auto minmax(0,1fr)}.application-status{grid-column:1/-1;width:max-content}.application-meta{grid-template-columns:1fr}}
'''
write(css_path, css)

# Version expectations.
for rel in ("internal/web/assets_test.go", "internal/httpapi/app_test.go"):
    text = read(rel)
    if "1.6.7" not in text:
        raise SystemExit(f"version marker missing in {rel}")
    write(rel, text.replace("1.6.7", "1.6.8"))

print("Applied HYZoraX V1.6.8 Applications page and guarded Node/Composer install UI")
