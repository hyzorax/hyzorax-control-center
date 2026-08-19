#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: core_catalog.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()

def read(rel):
    return (root / rel).read_text(encoding="utf-8")

def write(rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def replace_once(rel, old, new, label):
    text = read(rel)
    if old not in text:
        raise SystemExit(f"{label}: marker not found in {rel}")
    write(rel, text.replace(old, new, 1))

# ---------- Applications HTML: complete the accepted core catalog ----------
html_path = "internal/web/static/index.html"
html = read(html_path)
if 'Version 1.6.9' not in html:
    raise SystemExit("V1.6.9 sidebar version marker not found")
html = html.replace('Version 1.6.9', 'Version 1.6.10', 1)
html = html.replace('<span id="applications-visible-count">2 apps</span>', '<span id="applications-visible-count">7 apps</span>', 1)

node_marker = '''              <article id="node24-card" class="software-row" role="row" data-app-name="node.js 24 lts javascript runtime" data-app-status="checking">'''
if node_marker not in html:
    raise SystemExit("Node.js Applications row marker not found")
pre_node_rows = '''              <article id="nginx-card" class="software-row" role="row" data-app-name="nginx web server reverse proxy" data-app-status="checking">
                <div class="software-app" role="cell"><span class="software-app-icon">NX</span><div><strong>Nginx</strong><small id="nginx-detail">Checking server status…</small></div></div>
                <div class="software-value" role="cell"><small>Target</small><strong>Ubuntu 24.04</strong></div>
                <div class="software-value" role="cell"><small>Installed</small><strong id="nginx-version">—</strong></div>
                <div role="cell"><span id="nginx-status" class="application-status neutral">Checking…</span></div>
                <div class="software-action" role="cell"><button id="nginx-install-button" type="button" class="software-install" disabled>Install</button></div>
              </article>

              <article id="php84-card" class="software-row" role="row" data-app-name="php 8.4 fpm runtime" data-app-status="checking">
                <div class="software-app" role="cell"><span class="software-app-icon">PHP</span><div><strong>PHP 8.4 FPM</strong><small id="php84-detail">Checking server status…</small></div></div>
                <div class="software-value" role="cell"><small>Target</small><strong>8.4</strong></div>
                <div class="software-value" role="cell"><small>Installed</small><strong id="php84-version">—</strong></div>
                <div role="cell"><span id="php84-status" class="application-status neutral">Checking…</span></div>
                <div class="software-action" role="cell"><button id="php84-install-button" type="button" class="software-install" disabled>Install</button></div>
              </article>

              <article id="postgresql18-card" class="software-row" role="row" data-app-name="postgresql 18 database postgres" data-app-status="checking">
                <div class="software-app" role="cell"><span class="software-app-icon">PG</span><div><strong>PostgreSQL 18</strong><small id="postgresql18-detail">Checking server status…</small></div></div>
                <div class="software-value" role="cell"><small>Target</small><strong>18</strong></div>
                <div class="software-value" role="cell"><small>Installed</small><strong id="postgresql18-version">—</strong></div>
                <div role="cell"><span id="postgresql18-status" class="application-status neutral">Checking…</span></div>
                <div class="software-action" role="cell"><button id="postgresql18-install-button" type="button" class="software-install" disabled>Install</button></div>
              </article>

              <article id="redis-card" class="software-row" role="row" data-app-name="redis cache key value database" data-app-status="checking">
                <div class="software-app" role="cell"><span class="software-app-icon">R</span><div><strong>Redis</strong><small id="redis-detail">Checking server status…</small></div></div>
                <div class="software-value" role="cell"><small>Target</small><strong>Ubuntu 24.04</strong></div>
                <div class="software-value" role="cell"><small>Installed</small><strong id="redis-version">—</strong></div>
                <div role="cell"><span id="redis-status" class="application-status neutral">Checking…</span></div>
                <div class="software-action" role="cell"><button id="redis-install-button" type="button" class="software-install" disabled>Install</button></div>
              </article>

'''
html = html.replace(node_marker, pre_node_rows + node_marker, 1)

empty_marker = '              <div id="applications-empty" class="software-empty" hidden>No applications match this filter.</div>'
if empty_marker not in html:
    raise SystemExit("Applications empty-state marker not found")
fail2ban_row = '''              <article id="fail2ban-card" class="software-row" role="row" data-app-name="fail2ban ssh protection security" data-app-status="checking">
                <div class="software-app" role="cell"><span class="software-app-icon">F2</span><div><strong>Fail2ban SSH Protection</strong><small id="fail2ban-detail">Checking server status…</small></div></div>
                <div class="software-value" role="cell"><small>Target</small><strong>Ubuntu 24.04</strong></div>
                <div class="software-value" role="cell"><small>Installed</small><strong id="fail2ban-version">—</strong></div>
                <div role="cell"><span id="fail2ban-status" class="application-status neutral">Checking…</span></div>
                <div class="software-action" role="cell"><button id="fail2ban-install-button" type="button" class="software-install" disabled>Install</button></div>
              </article>

'''
html = html.replace(empty_marker, fail2ban_row + empty_marker, 1)
write(html_path, html)

# ---------- Applications backend: expose all already-accepted helper installers ----------
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

type applicationSpec struct {
    ID        string
    Health    string
    Preflight string
}

var coreApplicationSpecs = []applicationSpec{
    {ID: "nginx", Health: "installer.nginx.health", Preflight: "installer.nginx.preflight"},
    {ID: "php84", Health: "installer.php84.health", Preflight: "installer.php84.preflight"},
    {ID: "postgresql18", Health: "installer.postgresql18.health", Preflight: "installer.postgresql18.preflight"},
    {ID: "redis", Health: "installer.redis.health", Preflight: "installer.redis.preflight"},
    {ID: "node24", Health: "installer.node24.health", Preflight: "installer.node24.preflight"},
    {ID: "composer", Health: "installer.composer.health", Preflight: "installer.composer.preflight"},
    {ID: "fail2ban", Health: "installer.fail2ban.health", Preflight: "installer.fail2ban.preflight"},
}

func (a *App) applicationHelperCall(ctx context.Context, actorID, correlationID, action, target string, longRunning bool) (helper.Response, error) {
    callID, err := cryptoutil.RandomID()
    if err != nil {
        return helper.Response{}, err
    }
    request := helper.Request{ID: callID, CorrelationID: correlationID, ActorID: actorID, Action: action, Target: target}
    if longRunning {
        client := helper.Client{Socket: a.config.Helper.Socket, Timeout: 12 * time.Minute}
        return client.Call(ctx, request)
    }
    return a.helper.Call(ctx, request)
}

func applicationMetadata(id string) applicationState {
    state := applicationState{ID: id, Status: "blocked", Installable: false}
    switch id {
    case "nginx":
        state.Name = "Nginx"
        state.TargetVersion = "Ubuntu 24.04"
    case "php84":
        state.Name = "PHP 8.4 FPM"
        state.TargetVersion = "8.4"
    case "postgresql18":
        state.Name = "PostgreSQL 18"
        state.TargetVersion = "18"
    case "redis":
        state.Name = "Redis"
        state.TargetVersion = "Ubuntu 24.04"
    case "node24":
        state.Name = "Node.js 24 LTS"
        state.TargetVersion = "24.19.0"
    case "composer":
        state.Name = "Composer"
        state.TargetVersion = "2.10.2"
        state.Dependency = "PHP 8.4"
    case "fail2ban":
        state.Name = "Fail2ban SSH Protection"
        state.TargetVersion = "Ubuntu 24.04"
        state.Dependency = "OpenSSH"
    }
    return state
}

func applicationStateFromResponses(id string, health, preflight helper.Response) applicationState {
    state := applicationMetadata(id)
    if health.OK && health.Error == nil {
        state.Status = "installed"
        state.Installed = true
        state.Healthy = true
        state.Installable = false
        state.Detail = "Installed and healthy."
        if version, ok := health.Data["version"].(string); ok {
            state.Version = version
        }
        if npm, ok := health.Data["npm_version"].(string); ok {
            state.NPMVersion = npm
        }
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
    state.Detail = preflight.Error.Message
    switch preflight.Error.Code {
    case "component_exists":
        state.Status = "attention"
        state.Installed = true
    case "dependency_missing":
        state.Status = "dependency"
    case "path_conflict", "config_exists", "repository_exists", "cluster_exists", "port_in_use", "port_busy":
        state.Status = "conflict"
    case "unsupported_os", "unsupported_arch":
        state.Status = "unsupported"
    default:
        state.Status = "blocked"
    }
    return state
}

func (a *App) inspectApplication(request *http.Request, spec applicationSpec) (applicationState, error) {
    session := currentSession(request.Context())
    correlationID := requestID(request.Context())
    health, err := a.applicationHelperCall(request.Context(), session.User.ID, correlationID, spec.Health, spec.ID, false)
    if err != nil {
        return applicationState{}, err
    }
    if health.OK && health.Error == nil {
        return applicationStateFromResponses(spec.ID, health, helper.Response{}), nil
    }
    preflight, err := a.applicationHelperCall(request.Context(), session.User.ID, correlationID, spec.Preflight, spec.ID, false)
    if err != nil {
        return applicationState{}, err
    }
    return applicationStateFromResponses(spec.ID, health, preflight), nil
}

func (a *App) handleApplicationsStatus(writer http.ResponseWriter, request *http.Request) {
    states := make(map[string]any, len(coreApplicationSpecs))
    for _, spec := range coreApplicationSpecs {
        state, err := a.inspectApplication(request, spec)
        if err != nil {
            writeError(writer, http.StatusServiceUnavailable, "applications_status_unavailable", "Application status could not be read from the privileged helper.")
            return
        }
        states[spec.ID] = state
    }
    writeJSON(writer, http.StatusOK, states)
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
            case "component_exists", "path_conflict", "dependency_missing", "config_exists", "repository_exists", "cluster_exists", "port_in_use", "port_busy":
                status = http.StatusConflict
            case "unsupported_os", "unsupported_arch", "invalid_request":
                status = http.StatusBadRequest
            }
        }
        a.audit(request, action, id, "failed", map[string]any{"code": code})
        writeError(writer, status, code, message)
        return
    }
    a.audit(request, action, id, "success", map[string]any{"version": response.Data["version"]})
    writeJSON(writer, http.StatusOK, response.Data)
}

func (a *App) handleNginxInstall(writer http.ResponseWriter, request *http.Request) {
    a.installApplication(writer, request, "nginx", "installer.nginx.install")
}

func (a *App) handlePHP84Install(writer http.ResponseWriter, request *http.Request) {
    a.installApplication(writer, request, "php84", "installer.php84.install")
}

func (a *App) handlePostgreSQL18Install(writer http.ResponseWriter, request *http.Request) {
    a.installApplication(writer, request, "postgresql18", "installer.postgresql18.install")
}

func (a *App) handleRedisInstall(writer http.ResponseWriter, request *http.Request) {
    a.installApplication(writer, request, "redis", "installer.redis.install")
}

func (a *App) handleNode24Install(writer http.ResponseWriter, request *http.Request) {
    a.installApplication(writer, request, "node24", "installer.node24.install")
}

func (a *App) handleComposerInstall(writer http.ResponseWriter, request *http.Request) {
    a.installApplication(writer, request, "composer", "installer.composer.install")
}

func (a *App) handleFail2banInstall(writer http.ResponseWriter, request *http.Request) {
    a.installApplication(writer, request, "fail2ban", "installer.fail2ban.install")
}
'''
write("internal/httpapi/applications.go", applications_go)

# ---------- Routes ----------
app_go = "internal/httpapi/app.go"
app = read(app_go)
old_routes = '''\tmux.Handle("GET /api/v1/applications/status", a.requireAuth(http.HandlerFunc(a.handleApplicationsStatus)))
\tmux.Handle("POST /api/v1/applications/node24/install", a.requireAuth(http.HandlerFunc(a.handleNode24Install)))
\tmux.Handle("POST /api/v1/applications/composer/install", a.requireAuth(http.HandlerFunc(a.handleComposerInstall)))
'''
new_routes = '''\tmux.Handle("GET /api/v1/applications/status", a.requireAuth(http.HandlerFunc(a.handleApplicationsStatus)))
\tmux.Handle("POST /api/v1/applications/nginx/install", a.requireAuth(http.HandlerFunc(a.handleNginxInstall)))
\tmux.Handle("POST /api/v1/applications/php84/install", a.requireAuth(http.HandlerFunc(a.handlePHP84Install)))
\tmux.Handle("POST /api/v1/applications/postgresql18/install", a.requireAuth(http.HandlerFunc(a.handlePostgreSQL18Install)))
\tmux.Handle("POST /api/v1/applications/redis/install", a.requireAuth(http.HandlerFunc(a.handleRedisInstall)))
\tmux.Handle("POST /api/v1/applications/node24/install", a.requireAuth(http.HandlerFunc(a.handleNode24Install)))
\tmux.Handle("POST /api/v1/applications/composer/install", a.requireAuth(http.HandlerFunc(a.handleComposerInstall)))
\tmux.Handle("POST /api/v1/applications/fail2ban/install", a.requireAuth(http.HandlerFunc(a.handleFail2banInstall)))
'''
if old_routes not in app:
    raise SystemExit("Applications route block not found")
write(app_go, app.replace(old_routes, new_routes, 1))

# ---------- Tests ----------
applications_test = r'''package httpapi

import (
    "testing"

    "github.com/hyzorax/hyzorax-control/internal/helper"
)

func TestApplicationMetadataCoversCoreCatalog(t *testing.T) {
    expected := map[string]string{
        "nginx": "Nginx",
        "php84": "PHP 8.4 FPM",
        "postgresql18": "PostgreSQL 18",
        "redis": "Redis",
        "node24": "Node.js 24 LTS",
        "composer": "Composer",
        "fail2ban": "Fail2ban SSH Protection",
    }
    if len(coreApplicationSpecs) != len(expected) {
        t.Fatalf("unexpected catalog size: %d", len(coreApplicationSpecs))
    }
    for _, spec := range coreApplicationSpecs {
        state := applicationMetadata(spec.ID)
        if state.Name != expected[spec.ID] || state.TargetVersion == "" {
            t.Fatalf("unexpected metadata for %s: %#v", spec.ID, state)
        }
    }
}

func TestApplicationStateReady(t *testing.T) {
    state := applicationStateFromResponses("php84", helper.Response{OK: false, Error: &helper.Error{Code: "version_check_failed", Message: "not installed"}}, helper.Response{OK: true, Data: map[string]any{"ready": true}})
    if state.Status != "not_installed" || !state.Installable || state.Installed {
        t.Fatalf("unexpected state: %#v", state)
    }
}

func TestApplicationStateComposerDependency(t *testing.T) {
    state := applicationStateFromResponses("composer", helper.Response{OK: false, Error: &helper.Error{Code: "command_check_failed", Message: "missing"}}, helper.Response{OK: false, Error: &helper.Error{Code: "dependency_missing", Message: "HYZoraX PHP 8.4 is required before Composer can be installed"}})
    if state.Status != "dependency" || state.Installable || state.Dependency != "PHP 8.4" {
        t.Fatalf("unexpected state: %#v", state)
    }
}

func TestApplicationStateInstalled(t *testing.T) {
    state := applicationStateFromResponses("node24", helper.Response{OK: true, Data: map[string]any{"version": "24.19.0", "npm_version": "11.6.2"}}, helper.Response{})
    if !state.Installed || !state.Healthy || state.Version != "24.19.0" || state.NPMVersion != "11.6.2" {
        t.Fatalf("unexpected state: %#v", state)
    }
}

func TestApplicationStateConflict(t *testing.T) {
    state := applicationStateFromResponses("nginx", helper.Response{OK: false, Error: &helper.Error{Code: "config_invalid", Message: "not healthy"}}, helper.Response{OK: false, Error: &helper.Error{Code: "config_exists", Message: "Existing /etc/nginx prevents clean installation"}})
    if state.Status != "conflict" || state.Installable {
        t.Fatalf("unexpected state: %#v", state)
    }
}
'''
write("internal/httpapi/applications_test.go", applications_test)

# ---------- Front-end data/render/install wiring ----------
js_path = "internal/web/static/app.js"
js = read(js_path)
old_render_version = 'version.textContent=data.version||"—";'
new_render_version = 'version.textContent=data.version||(data.installed?"Installed":"—");'
if old_render_version not in js:
    raise SystemExit("Applications installed-version render marker not found")
js = js.replace(old_render_version, new_render_version, 1)

old_load = 'try{const data=await request("api/v1/applications/status");renderApplication("node24",data.node24||{});renderApplication("composer",data.composer||{});}'
new_load = 'try{const data=await request("api/v1/applications/status");["nginx","php84","postgresql18","redis","node24","composer","fail2ban"].forEach((id)=>renderApplication(id,data[id]||{}));}'
if old_load not in js:
    raise SystemExit("Applications load marker not found")
js = js.replace(old_load, new_load, 1)

old_confirm = 'message:`HYZoraX will install the managed ${label} runtime on this server.`'
new_confirm = 'message:`HYZoraX will install and configure the managed ${label} component on this server.`'
if old_confirm not in js:
    raise SystemExit("Applications install confirmation marker not found")
js = js.replace(old_confirm, new_confirm, 1)

old_listeners = '''$("#node24-install-button").addEventListener("click",()=>installApplication("node24","Node.js 24 LTS"));
$("#composer-install-button").addEventListener("click",()=>installApplication("composer","Composer"));'''
new_listeners = '''$("#nginx-install-button").addEventListener("click",()=>installApplication("nginx","Nginx"));
$("#php84-install-button").addEventListener("click",()=>installApplication("php84","PHP 8.4 FPM"));
$("#postgresql18-install-button").addEventListener("click",()=>installApplication("postgresql18","PostgreSQL 18"));
$("#redis-install-button").addEventListener("click",()=>installApplication("redis","Redis"));
$("#node24-install-button").addEventListener("click",()=>installApplication("node24","Node.js 24 LTS"));
$("#composer-install-button").addEventListener("click",()=>installApplication("composer","Composer"));
$("#fail2ban-install-button").addEventListener("click",()=>installApplication("fail2ban","Fail2ban SSH Protection"));'''
if old_listeners not in js:
    raise SystemExit("Applications listener block not found")
js = js.replace(old_listeners, new_listeners, 1)
write(js_path, js)

# Update tests that pin the user-visible release number.
for rel in ("internal/web/assets_test.go", "internal/httpapi/app_test.go"):
    text = read(rel)
    if "1.6.9" not in text:
        raise SystemExit(f"V1.6.9 version marker missing in {rel}")
    write(rel, text.replace("1.6.9", "1.6.10"))

print("Applied HYZoraX V1.6.10 complete core Applications catalog")
