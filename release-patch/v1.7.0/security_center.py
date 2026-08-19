#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: security_center.py <hyzorax-control-source-root>")

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


# ---------------------------------------------------------------------------
# Helper protocol/action: fixed, read-only security summary.
# ---------------------------------------------------------------------------
replace_once(
    "internal/helper/protocol.go",
    "const ProtocolVersion = 17",
    "const ProtocolVersion = 18",
    "helper protocol",
)

server_path = "internal/helper/server_linux.go"
server = read(server_path)
marker = '\tcase "service.status":\n'
if marker not in server:
    raise SystemExit("service.status dispatch marker not found")
security_case = '''\tcase "security.summary":
\t\tif request.Target != "" || len(request.Params) != 0 {
\t\t\tresponse.Error = &Error{Code: "invalid_request", Message: "security summary request must not contain target or parameters"}
\t\t\treturn response
\t\t}
\t\tdata, operationError := securitySummary(ctx)
\t\tif operationError != nil {
\t\t\tresponse.Error = operationError
\t\t\treturn response
\t\t}
\t\tresponse.OK = true
\t\tresponse.Data = data
\t\treturn response
'''
server = server.replace(marker, security_case + marker, 1)
write(server_path, server)

security_helper = r'''package helper

import (
    "context"
    "errors"
    "os"
    "os/exec"
    "strconv"
    "strings"
)

const securityMaxListeners = 256

type securityListener struct {
    Protocol string `json:"protocol"`
    Address  string `json:"address"`
    Port     int    `json:"port"`
    Scope    string `json:"scope"`
}

func securitySummary(ctx context.Context) (map[string]any, *Error) {
    ssh := securitySSH(ctx)
    firewall := securityFirewall(ctx)
    fail2ban := securityFail2ban(ctx)
    listeners, listenerWarning := securityListeningPorts(ctx)

    publicCount := 0
    localCount := 0
    networkCount := 0
    for _, listener := range listeners {
        switch listener.Scope {
        case "public":
            publicCount++
        case "local":
            localCount++
        default:
            networkCount++
        }
    }

    warnings := make([]string, 0, 1)
    if listenerWarning != "" {
        warnings = append(warnings, listenerWarning)
    }

    return map[string]any{
        "mode":       "read_only",
        "ssh":        ssh,
        "firewall":   firewall,
        "fail2ban":   fail2ban,
        "listeners":  listeners,
        "exposure": map[string]any{
            "total":          len(listeners),
            "public":         publicCount,
            "local":          localCount,
            "network_bound":  networkCount,
            "truncated":      len(listeners) >= securityMaxListeners,
        },
        "warnings": warnings,
    }, nil
}

func securitySSH(ctx context.Context) map[string]any {
    result := map[string]any{
        "installed":           false,
        "active":              false,
        "enabled":             false,
        "config_valid":        false,
        "port":                0,
        "permit_root_login":   "unknown",
        "password_auth":       "unknown",
        "pubkey_auth":         "unknown",
        "keyboard_interactive": "unknown",
    }

    if _, err := os.Stat("/usr/sbin/sshd"); err != nil {
        return result
    }
    result["installed"] = true

    if out, err := exec.CommandContext(ctx, "/usr/bin/systemctl", "is-active", "ssh.service").CombinedOutput(); err == nil || len(out) > 0 {
        result["active"] = strings.TrimSpace(string(out)) == "active"
    }
    if out, err := exec.CommandContext(ctx, "/usr/bin/systemctl", "is-enabled", "ssh.service").CombinedOutput(); err == nil || len(out) > 0 {
        value := strings.TrimSpace(string(out))
        result["enabled"] = value == "enabled" || value == "enabled-runtime"
    }

    out, err := exec.CommandContext(ctx, "/usr/sbin/sshd", "-T").CombinedOutput()
    if err != nil {
        result["detail"] = "Effective SSH configuration could not be read."
        return result
    }
    values := securityParseSSH(string(out))
    result["config_valid"] = true
    if value := values["port"]; value != "" {
        if port, parseErr := strconv.Atoi(value); parseErr == nil {
            result["port"] = port
        }
    }
    if value := values["permitrootlogin"]; value != "" {
        result["permit_root_login"] = value
    }
    if value := values["passwordauthentication"]; value != "" {
        result["password_auth"] = value
    }
    if value := values["pubkeyauthentication"]; value != "" {
        result["pubkey_auth"] = value
    }
    if value := values["kbdinteractiveauthentication"]; value != "" {
        result["keyboard_interactive"] = value
    }
    return result
}

func securityParseSSH(text string) map[string]string {
    wanted := map[string]bool{
        "port": true,
        "permitrootlogin": true,
        "passwordauthentication": true,
        "pubkeyauthentication": true,
        "kbdinteractiveauthentication": true,
    }
    result := map[string]string{}
    for _, line := range strings.Split(text, "\n") {
        fields := strings.Fields(strings.TrimSpace(line))
        if len(fields) < 2 {
            continue
        }
        key := strings.ToLower(fields[0])
        if wanted[key] && result[key] == "" {
            result[key] = strings.ToLower(fields[1])
        }
    }
    return result
}

func securityFirewall(ctx context.Context) map[string]any {
    result := map[string]any{
        "provider":          "none",
        "available":         false,
        "active":            false,
        "nft_rules_present": false,
    }

    if _, err := os.Stat("/usr/sbin/ufw"); err == nil {
        result["provider"] = "ufw"
        result["available"] = true
        out, _ := exec.CommandContext(ctx, "/usr/sbin/ufw", "status").CombinedOutput()
        status := strings.ToLower(strings.TrimSpace(string(out)))
        result["active"] = strings.HasPrefix(status, "status: active")
    }

    nftPath := ""
    for _, candidate := range []string{"/usr/sbin/nft", "/usr/bin/nft"} {
        if _, err := os.Stat(candidate); err == nil {
            nftPath = candidate
            break
        }
    }
    if nftPath != "" {
        if result["provider"] == "none" {
            result["provider"] = "nftables"
            result["available"] = true
        }
        out, err := exec.CommandContext(ctx, nftPath, "list", "ruleset").CombinedOutput()
        if err == nil {
            hasRules := strings.TrimSpace(string(out)) != ""
            result["nft_rules_present"] = hasRules
            if result["provider"] == "nftables" {
                result["active"] = hasRules
            }
        }
    }
    return result
}

func securityFail2ban(ctx context.Context) map[string]any {
    result := map[string]any{
        "installed":       false,
        "active":          false,
        "sshd_jail":       false,
        "currently_banned": 0,
    }
    if _, err := os.Stat("/usr/bin/fail2ban-client"); err != nil {
        return result
    }
    result["installed"] = true

    if out, err := exec.CommandContext(ctx, "/usr/bin/fail2ban-client", "ping").CombinedOutput(); err == nil && strings.Contains(strings.ToLower(string(out)), "pong") {
        result["active"] = true
    }
    out, err := exec.CommandContext(ctx, "/usr/bin/fail2ban-client", "status", "sshd").CombinedOutput()
    if err == nil {
        text := string(out)
        result["sshd_jail"] = strings.Contains(text, "Status for the jail: sshd")
        if banned, ok := securityParseFail2banBanned(text); ok {
            result["currently_banned"] = banned
        }
    }
    return result
}

func securityParseFail2banBanned(text string) (int, bool) {
    for _, line := range strings.Split(text, "\n") {
        if !strings.Contains(strings.ToLower(line), "currently banned") {
            continue
        }
        parts := strings.SplitN(line, ":", 2)
        if len(parts) != 2 {
            continue
        }
        value, err := strconv.Atoi(strings.TrimSpace(parts[1]))
        if err == nil {
            return value, true
        }
    }
    return 0, false
}

func securityListeningPorts(ctx context.Context) ([]securityListener, string) {
    if _, err := os.Stat("/usr/bin/ss"); err != nil {
        return []securityListener{}, "Listening-port inventory is unavailable because /usr/bin/ss is missing."
    }
    out, err := exec.CommandContext(ctx, "/usr/bin/ss", "-H", "-lntu").CombinedOutput()
    if err != nil {
        return []securityListener{}, "Listening-port inventory could not be collected."
    }
    return securityParseListeners(string(out), securityMaxListeners), ""
}

func securityParseListeners(text string, limit int) []securityListener {
    result := make([]securityListener, 0)
    for _, line := range strings.Split(text, "\n") {
        fields := strings.Fields(strings.TrimSpace(line))
        if len(fields) < 5 {
            continue
        }
        address, port, ok := securityParseEndpoint(fields[4])
        if !ok {
            continue
        }
        result = append(result, securityListener{
            Protocol: strings.ToLower(fields[0]),
            Address:  address,
            Port:     port,
            Scope:    securityAddressScope(address),
        })
        if len(result) >= limit {
            break
        }
    }
    return result
}

func securityParseEndpoint(value string) (string, int, bool) {
    value = strings.TrimSpace(value)
    if value == "" {
        return "", 0, false
    }
    index := strings.LastIndex(value, ":")
    if index < 0 || index == len(value)-1 {
        return "", 0, false
    }
    host := strings.TrimSpace(value[:index])
    portText := strings.TrimSpace(value[index+1:])
    if portText == "*" || portText == "" {
        return "", 0, false
    }
    port, err := strconv.Atoi(portText)
    if err != nil || port < 1 || port > 65535 {
        return "", 0, false
    }
    host = strings.TrimPrefix(host, "[")
    host = strings.TrimSuffix(host, "]")
    if zone := strings.LastIndex(host, "%"); zone > 0 {
        host = host[:zone]
    }
    if host == "" {
        host = "*"
    }
    return host, port, true
}

func securityAddressScope(address string) string {
    address = strings.ToLower(strings.TrimSpace(address))
    switch address {
    case "127.0.0.1", "::1", "localhost":
        return "local"
    case "0.0.0.0", "::", "*":
        return "public"
    default:
        return "network"
    }
}

var _ = errors.New
'''
# Remove the intentionally unused sentinel import cleanly before writing.
security_helper = security_helper.replace('    "errors"\n', '').replace('\nvar _ = errors.New\n', '\n')
write("internal/helper/security_linux.go", security_helper)

security_helper_test = r'''package helper

import (
    "context"
    "testing"
)

func TestSecuritySummaryRejectsDynamicInput(t *testing.T) {
    server := &Server{}
    base := Request{Version: ProtocolVersion, ID: "id", CorrelationID: "correlation", ActorID: "actor", Action: "security.summary"}

    withTarget := base
    withTarget.Target = "ssh.service"
    response := server.dispatch(context.Background(), withTarget)
    if response.OK || response.Error == nil || response.Error.Code != "invalid_request" {
        t.Fatalf("security summary target accepted: %+v", response)
    }

    withParams := base
    withParams.Params = []byte(`{"command":"ufw disable"}`)
    response = server.dispatch(context.Background(), withParams)
    if response.OK || response.Error == nil || response.Error.Code != "invalid_request" {
        t.Fatalf("security summary params accepted: %+v", response)
    }
}

func TestSecurityParseSSH(t *testing.T) {
    values := securityParseSSH("port 22\npermitrootlogin prohibit-password\npasswordauthentication no\npubkeyauthentication yes\nkbdinteractiveauthentication no\n")
    if values["port"] != "22" || values["permitrootlogin"] != "prohibit-password" || values["passwordauthentication"] != "no" || values["pubkeyauthentication"] != "yes" {
        t.Fatalf("unexpected SSH values: %#v", values)
    }
}

func TestSecurityParseListeners(t *testing.T) {
    input := "tcp LISTEN 0 4096 0.0.0.0:22 0.0.0.0:*\n" +
        "tcp LISTEN 0 4096 127.0.0.1:5432 0.0.0.0:*\n" +
        "udp UNCONN 0 0 [::]:53 [::]:*\n" +
        "tcp LISTEN 0 4096 [::1]:6379 [::]:*\n"
    listeners := securityParseListeners(input, 20)
    if len(listeners) != 4 {
        t.Fatalf("unexpected listener count: %#v", listeners)
    }
    if listeners[0].Scope != "public" || listeners[1].Scope != "local" || listeners[2].Scope != "public" || listeners[3].Scope != "local" {
        t.Fatalf("unexpected listener scopes: %#v", listeners)
    }
}

func TestSecurityParseFail2banBanned(t *testing.T) {
    value, ok := securityParseFail2banBanned("Status for the jail: sshd\n   |- Currently failed: 0\n   `- Currently banned: 3\n")
    if !ok || value != 3 {
        t.Fatalf("unexpected banned value: %d %v", value, ok)
    }
}
'''
write("internal/helper/security_linux_test.go", security_helper_test)

# ---------------------------------------------------------------------------
# Authenticated HTTP read-only endpoint.
# ---------------------------------------------------------------------------
security_http = r'''package httpapi

import (
    "net/http"

    "github.com/hyzorax/hyzorax-control/internal/cryptoutil"
    "github.com/hyzorax/hyzorax-control/internal/helper"
)

func (a *App) handleSecuritySummary(writer http.ResponseWriter, request *http.Request) {
    session := currentSession(request.Context())
    callID, err := cryptoutil.RandomID()
    if err != nil {
        writeError(writer, http.StatusInternalServerError, "request_id_failed", "Security status request could not be prepared.")
        return
    }
    response, err := a.helper.Call(request.Context(), helper.Request{
        ID:            callID,
        CorrelationID: requestID(request.Context()),
        ActorID:       session.User.ID,
        Action:        "security.summary",
    })
    if err != nil {
        writeError(writer, http.StatusServiceUnavailable, "security_status_unavailable", "Security status could not be read from the privileged helper.")
        return
    }
    if !response.OK || response.Error != nil {
        message := "Security status could not be collected."
        if response.Error != nil && response.Error.Message != "" {
            message = response.Error.Message
        }
        writeError(writer, http.StatusServiceUnavailable, "security_status_unavailable", message)
        return
    }
    writeJSON(writer, http.StatusOK, response.Data)
}
'''
write("internal/httpapi/security.go", security_http)

app_go = "internal/httpapi/app.go"
app = read(app_go)
route_marker = '\tmux.Handle("GET /api/v1/system/summary", a.requireAuth(http.HandlerFunc(a.handleSystemSummary)))\n'
if route_marker not in app:
    raise SystemExit("system summary route marker not found")
app = app.replace(route_marker, route_marker + '\tmux.Handle("GET /api/v1/security/summary", a.requireAuth(http.HandlerFunc(a.handleSecuritySummary)))\n', 1)
write(app_go, app)

# ---------------------------------------------------------------------------
# Security Center UI: activate sidebar, add read-only summary cards/table.
# ---------------------------------------------------------------------------
index_path = "internal/web/static/index.html"
html = read(index_path)
old_security_link = '<a href="#security"><span>◇</span>Security <em>Soon</em></a>'
new_security_link = '<a href="#security" data-view="security"><span>◇</span>Security</a>'
if old_security_link not in html:
    raise SystemExit("Security sidebar marker not found")
html = html.replace(old_security_link, new_security_link, 1)
if "Version 1.6.10" not in html:
    raise SystemExit("V1.6.10 footer marker not found")
html = html.replace("Version 1.6.10", "Version 1.7.0", 1)

section_match = re.search(r'(?m)^\s*<section id="applications-view"[^>]*>', html)
if not section_match:
    raise SystemExit("Applications section marker not found")
security_section = '''        <section id="security-view" class="content security-view" hidden>
          <div id="security-error" class="error" hidden></div>
          <div class="security-intro">
            <div>
              <p class="eyebrow">READ-ONLY FOUNDATION</p>
              <h3>Security posture</h3>
              <p>Live visibility into SSH, firewall, Fail2ban and listening network ports. Change controls will be added in guarded Security Center phases.</p>
            </div>
            <span class="security-mode-badge">Observation only</span>
          </div>

          <div class="security-card-grid">
            <article class="security-card">
              <div class="security-card-head"><span class="security-card-icon">SSH</span><span id="security-ssh-status" class="security-state neutral">Checking</span></div>
              <h4>SSH access</h4>
              <p id="security-ssh-detail">Reading effective SSH configuration…</p>
              <dl class="security-kv"><div><dt>Port</dt><dd id="security-ssh-port">—</dd></div><div><dt>Root login</dt><dd id="security-ssh-root">—</dd></div><div><dt>Password auth</dt><dd id="security-ssh-password">—</dd></div><div><dt>Public keys</dt><dd id="security-ssh-pubkey">—</dd></div></dl>
            </article>

            <article class="security-card">
              <div class="security-card-head"><span class="security-card-icon">FW</span><span id="security-firewall-status" class="security-state neutral">Checking</span></div>
              <h4>Firewall</h4>
              <p id="security-firewall-detail">Detecting host firewall state…</p>
              <dl class="security-kv"><div><dt>Provider</dt><dd id="security-firewall-provider">—</dd></div><div><dt>Active</dt><dd id="security-firewall-active">—</dd></div><div><dt>nft rules</dt><dd id="security-firewall-nft">—</dd></div></dl>
            </article>

            <article class="security-card">
              <div class="security-card-head"><span class="security-card-icon">F2</span><span id="security-fail2ban-status" class="security-state neutral">Checking</span></div>
              <h4>Fail2ban</h4>
              <p id="security-fail2ban-detail">Checking intrusion protection…</p>
              <dl class="security-kv"><div><dt>Installed</dt><dd id="security-fail2ban-installed">—</dd></div><div><dt>SSH jail</dt><dd id="security-fail2ban-jail">—</dd></div><div><dt>Currently banned</dt><dd id="security-fail2ban-banned">—</dd></div></dl>
            </article>

            <article class="security-card">
              <div class="security-card-head"><span class="security-card-icon">NET</span><span id="security-exposure-status" class="security-state neutral">Checking</span></div>
              <h4>Network exposure</h4>
              <p id="security-exposure-detail">Inventorying listening TCP/UDP ports…</p>
              <dl class="security-kv"><div><dt>Public</dt><dd id="security-public-count">—</dd></div><div><dt>Local</dt><dd id="security-local-count">—</dd></div><div><dt>Bound address</dt><dd id="security-network-count">—</dd></div><div><dt>Total</dt><dd id="security-total-count">—</dd></div></dl>
            </article>
          </div>

          <div class="security-listeners-card">
            <div class="security-listeners-head"><div><p class="eyebrow">NETWORK VISIBILITY</p><h3>Listening ports</h3></div><span id="security-listener-count" class="security-mode-badge">0 listeners</span></div>
            <div class="security-table-wrap">
              <table class="security-table">
                <thead><tr><th>Protocol</th><th>Address</th><th>Port</th><th>Scope</th></tr></thead>
                <tbody id="security-listener-body"><tr><td colspan="4" class="security-empty">Loading listening ports…</td></tr></tbody>
              </table>
            </div>
            <p id="security-warning" class="security-warning" hidden></p>
          </div>
        </section>

'''
html = html[:section_match.start()] + security_section + html[section_match.start():]
write(index_path, html)

# ---------------------------------------------------------------------------
# SPA routing/rendering.
# ---------------------------------------------------------------------------
js_path = "internal/web/static/app.js"
js = read(js_path)
old_hash = 'return ["overview","applications","files"].includes(value)?value:"overview";'
if old_hash not in js:
    raise SystemExit("viewFromHash marker not found")
js = js.replace(old_hash, 'return ["overview","security","applications","files"].includes(value)?value:"overview";', 1)

old_selected = 'const selected=["applications","files"].includes(view)?view:"overview";'
if old_selected not in js:
    raise SystemExit("switchView selected marker not found")
js = js.replace(old_selected, 'const selected=["security","applications","files"].includes(view)?view:"overview";', 1)

old_toggle = '$("#overview-view").hidden=selected!=="overview";\n$("#applications-view").hidden=selected!=="applications";'
if old_toggle not in js:
    raise SystemExit("view toggle marker not found")
js = js.replace(old_toggle, '$("#overview-view").hidden=selected!=="overview";\n$("#security-view").hidden=selected!=="security";\n$("#applications-view").hidden=selected!=="applications";', 1)

old_meta = 'const meta={overview:["Control Panel","System overview","Refresh dashboard"],applications:["Software","Applications","Refresh applications"],files:["Server filesystem","File Manager","Refresh directory"]}[selected];'
new_meta = 'const meta={overview:["Control Panel","System overview","Refresh dashboard"],security:["Security","Security Center","Refresh security status"],applications:["Software","Applications","Refresh applications"],files:["Server filesystem","File Manager","Refresh directory"]}[selected];'
if old_meta not in js:
    raise SystemExit("view metadata marker not found")
js = js.replace(old_meta, new_meta, 1)

old_loader = 'if(selected==="files") await loadFiles(state.filesLoaded?state.currentPath:"/");\nelse if(selected==="applications") await loadApplications();\nelse {await refreshDashboard();scheduleDashboardLive();}'
new_loader = 'if(selected==="files") await loadFiles(state.filesLoaded?state.currentPath:"/");\nelse if(selected==="security") await loadSecurity();\nelse if(selected==="applications") await loadApplications();\nelse {await refreshDashboard();scheduleDashboardLive();}'
if old_loader not in js:
    raise SystemExit("view loader marker not found")
js = js.replace(old_loader, new_loader, 1)

security_js = r'''
function securityYesNo(value){return value?"Yes":"No";}
function securitySetState(id,label,kind){const node=$(id);node.textContent=label;node.className=`security-state ${kind||"neutral"}`;}
function securitySSHLabel(value){return ({yes:"Yes",no:"No","prohibit-password":"Keys only","without-password":"Keys only","forced-commands-only":"Restricted"})[String(value||"").toLowerCase()]||String(value||"Unknown");}
function renderSecurity(data){
const ssh=data.ssh||{},firewall=data.firewall||{},fail2ban=data.fail2ban||{},exposure=data.exposure||{},listeners=Array.isArray(data.listeners)?data.listeners:[];
if(!ssh.installed){securitySetState("#security-ssh-status","Not installed","attention");$("#security-ssh-detail").textContent="OpenSSH server is not installed.";}
else if(ssh.active&&ssh.config_valid){securitySetState("#security-ssh-status","Active","ok");$("#security-ssh-detail").textContent="OpenSSH is active and its effective configuration is readable.";}
else{securitySetState("#security-ssh-status",ssh.active?"Needs attention":"Inactive","attention");$("#security-ssh-detail").textContent=ssh.detail||"OpenSSH is installed but not fully healthy.";}
$("#security-ssh-port").textContent=ssh.port||"—";$("#security-ssh-root").textContent=securitySSHLabel(ssh.permit_root_login);$("#security-ssh-password").textContent=securitySSHLabel(ssh.password_auth);$("#security-ssh-pubkey").textContent=securitySSHLabel(ssh.pubkey_auth);
const provider=String(firewall.provider||"none");$("#security-firewall-provider").textContent=provider==="none"?"None detected":provider.toUpperCase();$("#security-firewall-active").textContent=securityYesNo(!!firewall.active);$("#security-firewall-nft").textContent=securityYesNo(!!firewall.nft_rules_present);
if(firewall.active){securitySetState("#security-firewall-status","Active","ok");$("#security-firewall-detail").textContent="A host firewall ruleset is active.";}else if(firewall.available){securitySetState("#security-firewall-status","Inactive","attention");$("#security-firewall-detail").textContent="Firewall tooling is present but no active protection was detected.";}else{securitySetState("#security-firewall-status","Not detected","attention");$("#security-firewall-detail").textContent="No supported UFW or nftables firewall state was detected.";}
$("#security-fail2ban-installed").textContent=securityYesNo(!!fail2ban.installed);$("#security-fail2ban-jail").textContent=securityYesNo(!!fail2ban.sshd_jail);$("#security-fail2ban-banned").textContent=String(fail2ban.currently_banned??0);
if(fail2ban.active&&fail2ban.sshd_jail){securitySetState("#security-fail2ban-status","Protecting SSH","ok");$("#security-fail2ban-detail").textContent="Fail2ban is active with an SSH jail.";}else if(fail2ban.installed){securitySetState("#security-fail2ban-status","Needs attention","attention");$("#security-fail2ban-detail").textContent="Fail2ban is installed but SSH protection is not fully active.";}else{securitySetState("#security-fail2ban-status","Not installed","neutral");$("#security-fail2ban-detail").textContent="Fail2ban is not installed.";}
const publicCount=Number(exposure.public||0),localCount=Number(exposure.local||0),networkCount=Number(exposure.network_bound||0),total=Number(exposure.total||listeners.length);$("#security-public-count").textContent=String(publicCount);$("#security-local-count").textContent=String(localCount);$("#security-network-count").textContent=String(networkCount);$("#security-total-count").textContent=String(total);$("#security-listener-count").textContent=`${total} listener${total===1?"":"s"}`;
if(publicCount>0){securitySetState("#security-exposure-status",`${publicCount} public`,"attention");$("#security-exposure-detail").textContent="Wildcard listeners are reachable on server network interfaces unless filtered by firewall rules.";}else{securitySetState("#security-exposure-status","No wildcard ports","ok");$("#security-exposure-detail").textContent="No wildcard TCP/UDP listeners were detected in this snapshot.";}
const body=$("#security-listener-body");body.replaceChildren();if(!listeners.length){const row=document.createElement("tr"),cell=document.createElement("td");cell.colSpan=4;cell.className="security-empty";cell.textContent="No listening TCP/UDP ports were returned.";row.appendChild(cell);body.appendChild(row);}else listeners.forEach((listener)=>{const row=document.createElement("tr");[String(listener.protocol||"—").toUpperCase(),String(listener.address||"—"),String(listener.port||"—")].forEach((value)=>{const cell=document.createElement("td");cell.textContent=value;row.appendChild(cell);});const scope=document.createElement("td"),badge=document.createElement("span");badge.className=`security-scope ${listener.scope||"network"}`;badge.textContent=listener.scope==="public"?"Public":listener.scope==="local"?"Local only":"Bound address";scope.appendChild(badge);row.appendChild(scope);body.appendChild(row);});
const warnings=Array.isArray(data.warnings)?data.warnings.filter(Boolean):[];$("#security-warning").hidden=!warnings.length;$("#security-warning").textContent=warnings.join(" ");
}
async function loadSecurity(){clearError("#security-error");$("#refresh-button").disabled=true;try{const data=await request("api/v1/security/summary");renderSecurity(data);}catch(error){if(error.status===401){showLogin();return}showError("#security-error",error.message);}finally{$("#refresh-button").disabled=false;}}
'''
insert_before = 'function applicationStatusLabel(status)'
if insert_before not in js:
    raise SystemExit("applicationStatusLabel insertion marker not found")
js = js.replace(insert_before, security_js + '\n' + insert_before, 1)

old_refresh = 'if (state.currentView === "files") loadFiles(state.currentPath);\nelse if (state.currentView === "applications") loadApplications();\nelse refreshDashboard();'
new_refresh = 'if (state.currentView === "files") loadFiles(state.currentPath);\nelse if (state.currentView === "security") loadSecurity();\nelse if (state.currentView === "applications") loadApplications();\nelse refreshDashboard();'
if old_refresh not in js:
    raise SystemExit("refresh handler marker not found")
js = js.replace(old_refresh, new_refresh, 1)
write(js_path, js)

# ---------------------------------------------------------------------------
# Security Center styling; append to existing stylesheet to avoid disturbing UI.
# ---------------------------------------------------------------------------
css_path = "internal/web/static/app.css"
css = read(css_path)
security_css = r'''

/* V1.7.0 Security Center — read-only foundation */
.security-view{display:flex;flex-direction:column;gap:22px}
.security-view[hidden]{display:none!important}
.security-intro,.security-listeners-card,.security-card{background:rgba(255,255,255,.88);border:1px solid #d7e8fb;box-shadow:0 14px 36px rgba(37,102,178,.08)}
.security-intro{display:flex;align-items:center;justify-content:space-between;gap:24px;border-radius:18px;padding:24px 26px}
.security-intro h3,.security-listeners-head h3{margin:4px 0 7px;color:#17385f;font-size:21px}
.security-intro p:not(.eyebrow){margin:0;max-width:820px;color:#6a86a8;line-height:1.55}
.security-mode-badge{display:inline-flex;align-items:center;justify-content:center;white-space:nowrap;border:1px solid #bfdbfb;background:#f5faff;color:#2166b5;border-radius:999px;padding:8px 13px;font-size:12px;font-weight:800}
.security-card-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}
.security-card{border-radius:18px;padding:20px;min-width:0}
.security-card-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:15px}
.security-card-icon{width:44px;height:44px;border-radius:13px;background:linear-gradient(145deg,#52c9ef,#2478eb);color:white;display:inline-flex;align-items:center;justify-content:center;font-weight:900;font-size:12px;box-shadow:0 9px 22px rgba(35,124,232,.2)}
.security-card h4{margin:0 0 6px;color:#17385f;font-size:16px}
.security-card>p{margin:0 0 16px;color:#6c87a8;font-size:12px;line-height:1.45;min-height:35px}
.security-state{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:6px 10px;font-size:10px;font-weight:900;border:1px solid #d5e5f7;background:#f5f9fe;color:#597a9f}
.security-state.ok{border-color:#bdebdc;background:#effbf7;color:#188764}
.security-state.attention{border-color:#f1d49e;background:#fff9ec;color:#9b6810}
.security-kv{margin:0;display:grid;gap:8px}
.security-kv div{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-top:8px;border-top:1px solid #edf3fa}
.security-kv dt{font-size:11px;color:#8098b5}
.security-kv dd{margin:0;text-align:right;color:#284f7c;font-size:12px;font-weight:800;overflow-wrap:anywhere}
.security-listeners-card{border-radius:18px;overflow:hidden}
.security-listeners-head{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:22px 24px;border-bottom:1px solid #e4eef9}
.security-table-wrap{overflow:auto}
.security-table{width:100%;border-collapse:collapse;min-width:580px}
.security-table th{padding:13px 22px;text-align:left;background:#f5f9fe;color:#748eab;font-size:10px;letter-spacing:.06em;text-transform:uppercase}
.security-table td{padding:13px 22px;border-top:1px solid #edf3fa;color:#2d547f;font-size:12px}
.security-table td:nth-child(3){font-weight:800}
.security-scope{display:inline-flex;border-radius:999px;padding:5px 9px;font-size:10px;font-weight:900;border:1px solid #d4e5f7;background:#f5f9fe;color:#5a7898}
.security-scope.public{border-color:#f2c3c8;background:#fff2f3;color:#b83744}
.security-scope.local{border-color:#bdebdc;background:#effbf7;color:#188764}
.security-scope.network{border-color:#c9dcf4;background:#f3f8ff;color:#356fae}
.security-empty{text-align:center!important;color:#8299b3!important;padding:28px!important}
.security-warning{margin:0;padding:12px 22px;border-top:1px solid #f3dfb8;background:#fff9ed;color:#8f6518;font-size:11px}
@media(max-width:1180px){.security-card-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:720px){.security-intro,.security-listeners-head{align-items:flex-start;flex-direction:column}.security-card-grid{grid-template-columns:1fr}.security-card>p{min-height:0}}
'''
if "V1.7.0 Security Center" in css:
    raise SystemExit("Security Center CSS already present")
write(css_path, css + security_css)

# ---------------------------------------------------------------------------
# Version/UI test updates.
# ---------------------------------------------------------------------------
for rel in ("internal/web/assets_test.go", "internal/httpapi/app_test.go"):
    text = read(rel)
    if "1.6.10" not in text:
        raise SystemExit(f"V1.6.10 test marker missing in {rel}")
    text = text.replace("1.6.10", "1.7.0")
    write(rel, text)

# Strengthen existing HTML presence test if its marker is available.
app_test = read("internal/httpapi/app_test.go")
needle = '`data-view="files"`, `id="file-path-form"`'
if needle in app_test:
    app_test = app_test.replace(needle, '`data-view="security"`, `id="security-view"`, `data-view="files"`, `id="file-path-form"`', 1)
    write("internal/httpapi/app_test.go", app_test)

print("Applied HYZoraX V1.7.0 read-only Security Center foundation")
