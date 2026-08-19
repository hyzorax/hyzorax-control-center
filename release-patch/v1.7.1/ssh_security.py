#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: ssh_security.py <hyzorax-control-source-root>")
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
# Helper protocol + guarded SSH apply action.
# ---------------------------------------------------------------------------
replace_once("internal/helper/protocol.go", "const ProtocolVersion = 18", "const ProtocolVersion = 19", "helper protocol")

security_path = "internal/helper/security_linux.go"
security = read(security_path)
security = security.replace('import (\n\t"context"', 'import (\n\t"bytes"\n\t"context"\n\t"encoding/json"\n\t"errors"\n\t"io"', 1)
security = security.replace('\t"os/exec"\n\t"strconv"', '\t"os/exec"\n\t"path/filepath"\n\t"strconv"', 1)
security = security.replace('const securityMaxListeners = 256', '''const securityMaxListeners = 256
const securitySSHManagedPath = "/etc/ssh/sshd_config.d/10-hyzorax-security.conf"
const securitySSHManagedMarker = "# Managed by HYZoraX Control Panel SSH Security"''', 1)

security = security.replace('publicCount := 0', 'allInterfacesCount := 0', 1)
security = security.replace('case "public":\n\t\t\tpublicCount++', 'case "all_interfaces":\n\t\t\tallInterfacesCount++', 1)
security = security.replace('"mode":      "read_only"', '"mode":      "guarded"', 1)
security = security.replace('"public":        publicCount,', '"all_interfaces": allInterfacesCount,', 1)

security = security.replace('''\t\t"keyboard_interactive": "unknown",
\t}''', '''\t\t"keyboard_interactive": "unknown",
\t\t"root_key_detected":    false,
\t\t"managed":              false,
\t}''', 1)
security = security.replace('''\tvalues := securityParseSSH(string(out))
\tresult["config_valid"] = true''', '''\tvalues := securityParseSSH(string(out))
\tresult["config_valid"] = true
\tresult["root_key_detected"] = securityRootKeyDetected()
\tresult["managed"] = securitySSHManagedOwned()''', 1)
security = security.replace('''\t\t"kbdinteractiveauthentication": true,
\t}''', '''\t\t"kbdinteractiveauthentication": true,
\t\t"authenticationmethods":        true,
\t}''', 1)
security = security.replace('case "0.0.0.0", "::", "*":\n\t\treturn "public"', 'case "0.0.0.0", "::", "*":\n\t\treturn "all_interfaces"', 1)

append_code = r'''

type securitySSHApplyInput struct {
    RootLogin    string `json:"root_login"`
    PasswordAuth string `json:"password_auth"`
}

func securityDecodeSSHApplyInput(raw []byte) (securitySSHApplyInput, *Error) {
    input := securitySSHApplyInput{}
    if len(raw) == 0 || len(raw) > 2048 {
        return input, &Error{Code: "invalid_request", Message: "SSH security request is missing or too large"}
    }
    decoder := json.NewDecoder(bytes.NewReader(raw))
    decoder.DisallowUnknownFields()
    if err := decoder.Decode(&input); err != nil {
        return input, &Error{Code: "invalid_request", Message: "SSH security request is invalid"}
    }
    if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
        return input, &Error{Code: "invalid_request", Message: "SSH security request contains extra data"}
    }
    switch input.RootLogin {
    case "keep", "password_and_keys", "keys_only":
    default:
        return input, &Error{Code: "invalid_request", Message: "Unsupported root-login policy"}
    }
    switch input.PasswordAuth {
    case "keep", "enabled", "disabled":
    default:
        return input, &Error{Code: "invalid_request", Message: "Unsupported password-authentication policy"}
    }
    return input, nil
}

func securitySSHApply(ctx context.Context, raw []byte) (map[string]any, *Error) {
    if os.Geteuid() != 0 {
        return nil, &Error{Code: "security_privilege_required", Message: "SSH security changes require the privileged helper"}
    }
    input, operationError := securityDecodeSSHApplyInput(raw)
    if operationError != nil {
        return nil, operationError
    }
    if _, err := os.Stat("/usr/sbin/sshd"); err != nil {
        return nil, &Error{Code: "ssh_not_installed", Message: "OpenSSH server is not installed"}
    }

    current := securitySSH(ctx)
    if valid, _ := current["config_valid"].(bool); !valid {
        return nil, &Error{Code: "ssh_config_unreadable", Message: "Effective SSH configuration is not valid/readable"}
    }
    currentRoot := strings.ToLower(strings.TrimSpace(asSecurityString(current["permit_root_login"])))
    currentPassword := strings.ToLower(strings.TrimSpace(asSecurityString(current["password_auth"])))
    currentPubkey := strings.ToLower(strings.TrimSpace(asSecurityString(current["pubkey_auth"])))
    currentMethods := strings.ToLower(strings.TrimSpace(asSecurityString(current["authentication_methods"])))
    if currentMethods != "" && currentMethods != "unknown" && currentMethods != "any" {
        return nil, &Error{Code: "ssh_custom_authentication", Message: "Custom SSH AuthenticationMethods are active; HYZoraX will not override them automatically"}
    }

    desiredRoot := currentRoot
    desiredPassword := currentPassword
    if input.RootLogin == "password_and_keys" {
        desiredRoot = "yes"
    } else if input.RootLogin == "keys_only" {
        desiredRoot = "prohibit-password"
    }
    if input.PasswordAuth == "enabled" {
        desiredPassword = "yes"
    } else if input.PasswordAuth == "disabled" {
        desiredPassword = "no"
    }

    rootRequested := input.RootLogin != "keep" && desiredRoot != currentRoot
    passwordRequested := input.PasswordAuth != "keep" && desiredPassword != currentPassword
    if !rootRequested && !passwordRequested {
        return map[string]any{"changed": false, "ssh": current}, nil
    }

    hardensRoot := rootRequested && desiredRoot == "prohibit-password"
    disablesPassword := passwordRequested && desiredPassword == "no"
    if hardensRoot || disablesPassword {
        rootKey, _ := current["root_key_detected"].(bool)
        rootCanUseKeys := desiredRoot == "yes" || desiredRoot == "prohibit-password"
        if currentPubkey != "yes" || !rootKey || !rootCanUseKeys {
            return nil, &Error{Code: "ssh_lockout_risk", Message: "HYZoraX refused this change because a usable root public-key login was not detected. Add and verify a root SSH key before removing password access"}
        }
    }

    existing, existed, owned, existingValues, err := securitySSHManagedRead()
    if err != nil {
        return nil, &Error{Code: "ssh_managed_config_read_failed", Message: "HYZoraX SSH security configuration could not be inspected"}
    }
    if existed && !owned {
        return nil, &Error{Code: "ssh_managed_config_conflict", Message: "The HYZoraX SSH security drop-in path exists but is not HYZoraX-managed"}
    }

    rootDirective := existingValues["permitrootlogin"]
    passwordDirective := existingValues["passwordauthentication"]
    if input.RootLogin == "password_and_keys" {
        rootDirective = "yes"
    } else if input.RootLogin == "keys_only" {
        rootDirective = "prohibit-password"
    }
    if input.PasswordAuth == "enabled" {
        passwordDirective = "yes"
    } else if input.PasswordAuth == "disabled" {
        passwordDirective = "no"
    }

    content := securitySSHManagedContent(rootDirective, passwordDirective)
    if err := securitySSHManagedWrite(content); err != nil {
        return nil, &Error{Code: "ssh_managed_config_write_failed", Message: "HYZoraX SSH security configuration could not be written"}
    }
    rollback := func() {
        if existed {
            _ = securitySSHManagedWrite(existing)
        } else {
            _ = os.Remove(securitySSHManagedPath)
        }
        _ = securitySSHReload(ctx)
    }

    if out, err := exec.CommandContext(ctx, "/usr/sbin/sshd", "-t").CombinedOutput(); err != nil {
        _ = out
        rollback()
        return nil, &Error{Code: "ssh_validation_failed", Message: "OpenSSH rejected the proposed HYZoraX security configuration; the previous configuration was restored"}
    }
    if err := securitySSHReload(ctx); err != nil {
        rollback()
        return nil, &Error{Code: "ssh_reload_failed", Message: "OpenSSH could not reload the proposed security configuration; the previous configuration was restored"}
    }

    effectiveOut, err := exec.CommandContext(ctx, "/usr/sbin/sshd", "-T").CombinedOutput()
    if err != nil {
        rollback()
        return nil, &Error{Code: "ssh_verification_failed", Message: "OpenSSH effective configuration could not be verified; the previous configuration was restored"}
    }
    effective := securityParseSSH(string(effectiveOut))
    if rootDirective != "" && effective["permitrootlogin"] != rootDirective {
        rollback()
        return nil, &Error{Code: "ssh_override_conflict", Message: "Another SSH configuration overrides the requested root-login policy; HYZoraX restored the previous configuration"}
    }
    if passwordDirective != "" && effective["passwordauthentication"] != passwordDirective {
        rollback()
        return nil, &Error{Code: "ssh_override_conflict", Message: "Another SSH configuration overrides the requested password-authentication policy; HYZoraX restored the previous configuration"}
    }

    return map[string]any{"changed": true, "ssh": securitySSH(ctx)}, nil
}

func securitySSHManagedRead() ([]byte, bool, bool, map[string]string, error) {
    values := map[string]string{}
    content, err := os.ReadFile(securitySSHManagedPath)
    if errors.Is(err, os.ErrNotExist) {
        return nil, false, false, values, nil
    }
    if err != nil {
        return nil, false, false, values, err
    }
    text := string(content)
    owned := strings.HasPrefix(text, securitySSHManagedMarker+"\n")
    if owned {
        for _, line := range strings.Split(text, "\n") {
            fields := strings.Fields(strings.TrimSpace(line))
            if len(fields) < 2 || strings.HasPrefix(fields[0], "#") {
                continue
            }
            key := strings.ToLower(fields[0])
            switch key {
            case "permitrootlogin", "passwordauthentication":
                values[key] = strings.ToLower(fields[1])
            default:
                return content, true, false, map[string]string{}, nil
            }
        }
    }
    return content, true, owned, values, nil
}

func securitySSHManagedContent(rootLogin, passwordAuth string) []byte {
    lines := []string{securitySSHManagedMarker, "# Changes are validated before ssh.service is reloaded."}
    if rootLogin != "" {
        lines = append(lines, "PermitRootLogin "+rootLogin)
    }
    if passwordAuth != "" {
        lines = append(lines, "PasswordAuthentication "+passwordAuth)
    }
    return []byte(strings.Join(lines, "\n") + "\n")
}

func securitySSHManagedWrite(content []byte) error {
    directory := filepath.Dir(securitySSHManagedPath)
    if err := os.MkdirAll(directory, 0755); err != nil {
        return err
    }
    temporary, err := os.CreateTemp(directory, ".hyzorax-ssh-security-*")
    if err != nil {
        return err
    }
    temporaryPath := temporary.Name()
    defer os.Remove(temporaryPath)
    if err := temporary.Chmod(0644); err != nil {
        _ = temporary.Close()
        return err
    }
    if _, err := temporary.Write(content); err != nil {
        _ = temporary.Close()
        return err
    }
    if err := temporary.Sync(); err != nil {
        _ = temporary.Close()
        return err
    }
    if err := temporary.Close(); err != nil {
        return err
    }
    return os.Rename(temporaryPath, securitySSHManagedPath)
}

func securitySSHReload(ctx context.Context) error {
    if err := exec.CommandContext(ctx, "/usr/bin/systemctl", "reload", "ssh.service").Run(); err == nil {
        return nil
    }
    return exec.CommandContext(ctx, "/usr/bin/systemctl", "reload", "sshd.service").Run()
}

func securitySSHManagedOwned() bool {
    content, err := os.ReadFile(securitySSHManagedPath)
    return err == nil && strings.HasPrefix(string(content), securitySSHManagedMarker+"\n")
}

func securityRootKeyDetected() bool {
    for _, path := range []string{"/root/.ssh/authorized_keys", "/root/.ssh/authorized_keys2"} {
        content, err := os.ReadFile(path)
        if err != nil {
            continue
        }
        for _, line := range strings.Split(string(content), "\n") {
            line = strings.TrimSpace(line)
            if line != "" && !strings.HasPrefix(line, "#") {
                return true
            }
        }
    }
    return false
}

func asSecurityString(value any) string {
    text, _ := value.(string)
    return text
}
'''
security = security.rstrip() + append_code + "\n"
write(security_path, security)

# Add authentication_methods to summary after parse.
security = read(security_path)
marker = '''\tif value := values["kbdinteractiveauthentication"]; value != "" {
\t\tresult["keyboard_interactive"] = value
\t}
\treturn result
}'''
replacement = '''\tif value := values["kbdinteractiveauthentication"]; value != "" {
\t\tresult["keyboard_interactive"] = value
\t}
\tif value := values["authenticationmethods"]; value != "" {
\t\tresult["authentication_methods"] = value
\t} else {
\t\tresult["authentication_methods"] = "unknown"
\t}
\treturn result
}'''
if marker not in security:
    raise SystemExit("SSH summary tail marker not found")
write(security_path, security.replace(marker, replacement, 1))

server_path = "internal/helper/server_linux.go"
server = read(server_path)
marker = '\tcase "service.status":\n'
if marker not in server:
    raise SystemExit("service.status dispatch marker not found")
case = '''\tcase "security.ssh.apply":
\t\tif request.Target != "" || len(request.Params) == 0 {
\t\t\tresponse.Error = &Error{Code: "invalid_request", Message: "SSH security apply request must contain fixed policy parameters and no target"}
\t\t\treturn response
\t\t}
\t\tdata, operationError := securitySSHApply(ctx, request.Params)
\t\tif operationError != nil {
\t\t\tresponse.Error = operationError
\t\t\treturn response
\t\t}
\t\tresponse.OK = true
\t\tresponse.Data = data
\t\treturn response
'''
server = server.replace(marker, case + marker, 1)
write(server_path, server)

# ---------------------------------------------------------------------------
# Tests: rename wildcard scope and cover strict input/guard helpers.
# ---------------------------------------------------------------------------
test_path = "internal/helper/security_linux_test.go"
tests = read(test_path).replace('Scope != "public"', 'Scope != "all_interfaces"').replace('Scope != "public"', 'Scope != "all_interfaces"')
tests += r'''

func TestSecurityDecodeSSHApplyInput(t *testing.T) {
    input, operationError := securityDecodeSSHApplyInput([]byte(`{"root_login":"keys_only","password_auth":"disabled"}`))
    if operationError != nil || input.RootLogin != "keys_only" || input.PasswordAuth != "disabled" {
        t.Fatalf("unexpected input: %#v %#v", input, operationError)
    }
    if _, operationError := securityDecodeSSHApplyInput([]byte(`{"root_login":"nope","password_auth":"enabled"}`)); operationError == nil || operationError.Code != "invalid_request" {
        t.Fatalf("invalid root policy accepted: %#v", operationError)
    }
    if _, operationError := securityDecodeSSHApplyInput([]byte(`{"root_login":"keep","password_auth":"enabled","command":"reboot"}`)); operationError == nil || operationError.Code != "invalid_request" {
        t.Fatalf("unknown field accepted: %#v", operationError)
    }
}

func TestSecuritySSHManagedContent(t *testing.T) {
    text := string(securitySSHManagedContent("prohibit-password", "no"))
    if !strings.Contains(text, securitySSHManagedMarker) || !strings.Contains(text, "PermitRootLogin prohibit-password") || !strings.Contains(text, "PasswordAuthentication no") {
        t.Fatalf("unexpected managed config: %q", text)
    }
}

func TestSecuritySSHApplyDispatchRejectsMissingParamsAndTarget(t *testing.T) {
    server := &Server{}
    missing := server.dispatch(context.Background(), Request{Version: ProtocolVersion, ID: "id", CorrelationID: "c", ActorID: "a", Action: "security.ssh.apply"})
    if missing.OK || missing.Error == nil || missing.Error.Code != "invalid_request" {
        t.Fatalf("missing params accepted: %+v", missing)
    }
    targeted := server.dispatch(context.Background(), Request{Version: ProtocolVersion, ID: "id2", CorrelationID: "c", ActorID: "a", Action: "security.ssh.apply", Target: "ssh.service", Params: []byte(`{"root_login":"keep","password_auth":"keep"}`)})
    if targeted.OK || targeted.Error == nil || targeted.Error.Code != "invalid_request" {
        t.Fatalf("target accepted: %+v", targeted)
    }
}
'''
# test file needs strings import.
tests = tests.replace('import (\n\t"context"\n\t"testing"', 'import (\n\t"context"\n\t"strings"\n\t"testing"', 1)
write(test_path, tests)

write("internal/helper/security_ssh_acceptance_test.go", r'''//go:build integration && linux

package helper

import (
    "context"
    "errors"
    "os"
    "testing"
    "time"
)

func TestSecuritySSHApplyAcceptance(t *testing.T) {
    if os.Getenv("HYZORAX_SECURITY_SSH_ACCEPTANCE") != "1" {
        t.Skip("opt-in integration test")
    }
    if os.Geteuid() != 0 {
        t.Fatal("root required")
    }
    old, readErr := os.ReadFile(securitySSHManagedPath)
    existed := readErr == nil
    if readErr != nil && !errors.Is(readErr, os.ErrNotExist) {
        t.Fatal(readErr)
    }
    defer func() {
        if existed {
            _ = securitySSHManagedWrite(old)
        } else {
            _ = os.Remove(securitySSHManagedPath)
        }
        ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
        defer cancel()
        _ = securitySSHReload(ctx)
    }()

    ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
    defer cancel()
    hardened, operationError := securitySSHApply(ctx, []byte(`{"root_login":"keys_only","password_auth":"disabled"}`))
    if operationError != nil {
        t.Fatalf("hardening failed: code=%s message=%s", operationError.Code, operationError.Message)
    }
    if changed, _ := hardened["changed"].(bool); !changed {
        t.Fatalf("hardening unexpectedly reported no change: %#v", hardened)
    }
    ssh := securitySSH(ctx)
    if ssh["permit_root_login"] != "prohibit-password" || ssh["password_auth"] != "no" {
        t.Fatalf("hardening not effective: %#v", ssh)
    }

    relaxed, operationError := securitySSHApply(ctx, []byte(`{"root_login":"password_and_keys","password_auth":"enabled"}`))
    if operationError != nil {
        t.Fatalf("restore policy failed: code=%s message=%s", operationError.Code, operationError.Message)
    }
    if changed, _ := relaxed["changed"].(bool); !changed {
        t.Fatalf("restore unexpectedly reported no change: %#v", relaxed)
    }
    ssh = securitySSH(ctx)
    if ssh["permit_root_login"] != "yes" || ssh["password_auth"] != "yes" {
        t.Fatalf("restore policy not effective: %#v", ssh)
    }
}
''')

# ---------------------------------------------------------------------------
# Authenticated HTTP write endpoint with audit.
# ---------------------------------------------------------------------------
http_path = "internal/httpapi/security.go"
http = read(http_path)
http = http.replace('import (\n\t"net/http"', 'import (\n\t"encoding/json"\n\t"io"\n\t"net/http"', 1)
http += r'''

type securitySSHApplyRequest struct {
    RootLogin    string `json:"root_login"`
    PasswordAuth string `json:"password_auth"`
}

func (a *App) handleSecuritySSHApply(writer http.ResponseWriter, request *http.Request) {
    request.Body = http.MaxBytesReader(writer, request.Body, 2048)
    decoder := json.NewDecoder(request.Body)
    decoder.DisallowUnknownFields()
    input := securitySSHApplyRequest{}
    if err := decoder.Decode(&input); err != nil {
        writeError(writer, http.StatusBadRequest, "invalid_request", "SSH security request is invalid.")
        return
    }
    if err := decoder.Decode(&struct{}{}); err != io.EOF {
        writeError(writer, http.StatusBadRequest, "invalid_request", "SSH security request contains extra data.")
        return
    }
    params, err := json.Marshal(input)
    if err != nil {
        writeError(writer, http.StatusInternalServerError, "request_prepare_failed", "SSH security request could not be prepared.")
        return
    }
    session := currentSession(request.Context())
    callID, err := cryptoutil.RandomID()
    if err != nil {
        writeError(writer, http.StatusInternalServerError, "request_id_failed", "SSH security request could not be prepared.")
        return
    }
    response, err := a.helper.Call(request.Context(), helper.Request{
        ID: callID, CorrelationID: requestID(request.Context()), ActorID: session.User.ID,
        Action: "security.ssh.apply", Params: params,
    })
    if err != nil {
        a.audit(request, "security.ssh.apply", "ssh", "helper_unavailable", nil)
        writeError(writer, http.StatusServiceUnavailable, "helper_unavailable", "Privileged SSH security helper is unavailable.")
        return
    }
    if !response.OK || response.Error != nil {
        code, message := "ssh_security_failed", "SSH security policy could not be applied."
        status := http.StatusInternalServerError
        if response.Error != nil {
            code, message = response.Error.Code, response.Error.Message
            switch code {
            case "invalid_request", "ssh_not_installed":
                status = http.StatusBadRequest
            case "ssh_lockout_risk", "ssh_custom_authentication", "ssh_managed_config_conflict", "ssh_override_conflict":
                status = http.StatusConflict
            }
        }
        a.audit(request, "security.ssh.apply", "ssh", "failed", map[string]any{"code": code})
        writeError(writer, status, code, message)
        return
    }
    a.audit(request, "security.ssh.apply", "ssh", "success", map[string]any{"root_login": input.RootLogin, "password_auth": input.PasswordAuth})
    writeJSON(writer, http.StatusOK, response.Data)
}
'''
write(http_path, http)

app_path = "internal/httpapi/app.go"
app = read(app_path)
route_marker = '\tmux.Handle("GET /api/v1/security/summary", a.requireAuth(http.HandlerFunc(a.handleSecuritySummary)))\n'
if route_marker not in app:
    raise SystemExit("security summary route marker not found")
app = app.replace(route_marker, route_marker + '\tmux.Handle("POST /api/v1/security/ssh/apply", a.requireAuth(http.HandlerFunc(a.handleSecuritySSHApply)))\n', 1)
write(app_path, app)

# ---------------------------------------------------------------------------
# Security UI: compact header, correct wildcard wording, guarded SSH dialog.
# ---------------------------------------------------------------------------
html_path = "internal/web/static/index.html"
html = read(html_path)
old_intro = '''          <div class="security-intro">
            <div>
              <p class="eyebrow">READ-ONLY FOUNDATION</p>
              <h3>Security posture</h3>
              <p>Live visibility into SSH, firewall, Fail2ban and listening network ports. Change controls will be added in guarded Security Center phases.</p>
            </div>
            <span class="security-mode-badge">Observation only</span>
          </div>'''
new_intro = '''          <div class="security-toolbar">
            <div><p class="eyebrow">GUARDED SECURITY</p><h3>Security posture</h3></div>
            <div class="security-toolbar-meta"><span class="security-mode-badge">Live status</span><span class="security-mode-badge guarded">Guarded changes</span></div>
          </div>'''
if old_intro not in html:
    raise SystemExit("security intro marker not found")
html = html.replace(old_intro, new_intro, 1)
old_ssh = '''              <dl class="security-kv"><div><dt>Port</dt><dd id="security-ssh-port">—</dd></div><div><dt>Root login</dt><dd id="security-ssh-root">—</dd></div><div><dt>Password auth</dt><dd id="security-ssh-password">—</dd></div><div><dt>Public keys</dt><dd id="security-ssh-pubkey">—</dd></div></dl>
            </article>'''
new_ssh = '''              <dl class="security-kv"><div><dt>Port</dt><dd id="security-ssh-port">—</dd></div><div><dt>Root login</dt><dd id="security-ssh-root">—</dd></div><div><dt>Password auth</dt><dd id="security-ssh-password">—</dd></div><div><dt>Public keys</dt><dd id="security-ssh-pubkey">—</dd></div><div><dt>Root key</dt><dd id="security-ssh-root-key">—</dd></div></dl>
              <div class="security-card-actions"><button id="security-ssh-manage" type="button" class="security-manage-button" disabled>Manage SSH</button></div>
            </article>'''
if old_ssh not in html:
    raise SystemExit("SSH card marker not found")
html = html.replace(old_ssh, new_ssh, 1)
html = html.replace('<h4>Network exposure</h4>', '<h4>Network bindings</h4>', 1)
html = html.replace('<div><dt>Public</dt><dd id="security-public-count">—</dd></div>', '<div><dt>All interfaces</dt><dd id="security-all-interfaces-count">—</dd></div>', 1)

# Dialog is a sibling of views inside main.
applications_marker = '        <section id="applications-view" class="content applications-view" hidden>'
if applications_marker not in html:
    raise SystemExit("applications view marker not found")
ssh_dialog = '''        <dialog id="security-ssh-dialog" class="modal security-ssh-modal">
          <form id="security-ssh-form" class="modal-card security-ssh-form">
            <div class="operation-heading"><div><p class="eyebrow">SSH SECURITY</p><h3>Manage SSH access</h3></div><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
            <div class="security-ssh-current"><span>SSH port <strong id="security-ssh-dialog-port">—</strong></span><span id="security-ssh-dialog-key" class="security-state neutral">Key status unknown</span></div>
            <label>Root login<select id="security-ssh-root-policy" name="root_login"><option value="keep">Keep current policy</option><option value="password_and_keys">Password + keys</option><option value="keys_only">Keys only</option></select></label>
            <label>Password authentication<select id="security-ssh-password-policy" name="password_auth"><option value="keep">Keep current policy</option><option value="enabled">Enabled</option><option value="disabled">Disabled</option></select></label>
            <p id="security-ssh-guard-note" class="security-guard-note">HYZoraX validates sshd configuration before reload. Existing SSH sessions are not stopped.</p>
            <div id="security-ssh-error" class="alert" role="alert" hidden></div>
            <div class="modal-actions"><button type="button" class="ghost compact" data-close-dialog>Cancel</button><button type="submit" class="primary compact-primary">Apply SSH policy</button></div>
          </form>
        </dialog>

'''
html = html.replace(applications_marker, ssh_dialog + applications_marker, 1)
html = html.replace('Version 1.7.0', 'Version 1.7.1')
write(html_path, html)

css_path = "internal/web/static/app.css"
css = read(css_path)
css += r'''

/* V1.7.1 Security Center — guarded SSH controls */
.security-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:64px;padding:12px 16px;border:1px solid #d7e8fb;border-radius:14px;background:rgba(255,255,255,.88);box-shadow:0 10px 28px rgba(37,102,178,.06)}
.security-toolbar h3{margin:2px 0 0;color:#17385f;font-size:18px}.security-toolbar .eyebrow{margin:0}.security-toolbar-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.security-mode-badge.guarded{border-color:#bdebdc;background:#effbf7;color:#188764}.security-card-actions{display:flex;justify-content:flex-end;margin-top:14px;padding-top:12px;border-top:1px solid #edf3fa}.security-manage-button{min-height:34px;padding:6px 12px;border:1px solid #2478ee;border-radius:8px;color:#fff;background:#2478ee;font-size:11px;font-weight:850;box-shadow:0 7px 18px rgba(36,120,238,.15)}.security-manage-button:hover:not(:disabled){background:#1767dc}.security-manage-button:disabled{color:#9badc1;border-color:#d6e0eb;background:#eef3f8;box-shadow:none;cursor:not-allowed}.security-scope.all_interfaces{border-color:#f1d49e;background:#fff9ec;color:#94620e}.security-ssh-modal{width:min(560px,calc(100vw - 28px))}.security-ssh-form{gap:14px}.security-ssh-form select{width:100%;min-height:44px;padding:9px 11px;border:1px solid var(--line-strong);border-radius:9px;color:var(--ink);background:#fff;font:inherit;font-size:.7rem}.security-ssh-form select:focus{outline:2px solid rgba(47,137,246,.14);border-color:#3b8ef5}.security-ssh-current{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:#f7faff;color:#6783a2;font-size:.65rem}.security-ssh-current strong{color:#234e79}.security-guard-note{margin:0;padding:10px 12px;border:1px solid #d9e7f6;border-radius:10px;background:#f7fbff;color:#627f9f;font-size:.62rem;line-height:1.5}.security-guard-note.warning{border-color:#efd79f;background:#fff9eb;color:#8b6418}@media(max-width:720px){.security-toolbar{align-items:flex-start;flex-direction:column}.security-toolbar-meta{width:100%}.security-ssh-current{align-items:flex-start;flex-direction:column}}
'''
write(css_path, css)

js_path = "internal/web/static/app.js"
js = read(js_path)
js = js.replace('function securityYesNo(value){return value?"Yes":"No";}', 'let securitySnapshot=null;\nfunction securityYesNo(value){return value?"Yes":"No";}', 1)
js = js.replace('const ssh=data.ssh||{},firewall=data.firewall||{},fail2ban=data.fail2ban||{},exposure=data.exposure||{},listeners=Array.isArray(data.listeners)?data.listeners:[];', 'securitySnapshot=data;const ssh=data.ssh||{},firewall=data.firewall||{},fail2ban=data.fail2ban||{},exposure=data.exposure||{},listeners=Array.isArray(data.listeners)?data.listeners:[];', 1)
old_ssh_render = '$("#security-ssh-port").textContent=ssh.port||"—";$("#security-ssh-root").textContent=securitySSHLabel(ssh.permit_root_login);$("#security-ssh-password").textContent=securitySSHLabel(ssh.password_auth);$("#security-ssh-pubkey").textContent=securitySSHLabel(ssh.pubkey_auth);'
new_ssh_render = '$("#security-ssh-port").textContent=ssh.port||"—";$("#security-ssh-root").textContent=securitySSHLabel(ssh.permit_root_login);$("#security-ssh-password").textContent=securitySSHLabel(ssh.password_auth);$("#security-ssh-pubkey").textContent=securitySSHLabel(ssh.pubkey_auth);$("#security-ssh-root-key").textContent=ssh.root_key_detected?"Detected":"Not detected";$("#security-ssh-manage").disabled=!(ssh.installed&&ssh.active&&ssh.config_valid);'
if old_ssh_render not in js:
    raise SystemExit("SSH render marker not found")
js = js.replace(old_ssh_render, new_ssh_render, 1)
old_counts = 'const publicCount=Number(exposure.public||0),localCount=Number(exposure.local||0),networkCount=Number(exposure.network_bound||0),total=Number(exposure.total||listeners.length);$("#security-public-count").textContent=String(publicCount);$("#security-local-count").textContent=String(localCount);$("#security-network-count").textContent=String(networkCount);$("#security-total-count").textContent=String(total);$("#security-listener-count").textContent=`${total} listener${total===1?"":"s"}`;'
new_counts = 'const allInterfacesCount=Number(exposure.all_interfaces||0),localCount=Number(exposure.local||0),networkCount=Number(exposure.network_bound||0),total=Number(exposure.total||listeners.length);$("#security-all-interfaces-count").textContent=String(allInterfacesCount);$("#security-local-count").textContent=String(localCount);$("#security-network-count").textContent=String(networkCount);$("#security-total-count").textContent=String(total);$("#security-listener-count").textContent=`${total} listener${total===1?"":"s"}`;'
if old_counts not in js:
    raise SystemExit("security count marker not found")
js = js.replace(old_counts, new_counts, 1)
old_exposure = 'if(publicCount>0){securitySetState("#security-exposure-status",`${publicCount} public`,"attention");$("#security-exposure-detail").textContent="Wildcard listeners are reachable on server network interfaces unless filtered by firewall rules.";}else{securitySetState("#security-exposure-status","No wildcard ports","ok");$("#security-exposure-detail").textContent="No wildcard TCP/UDP listeners were detected in this snapshot.";}'
new_exposure = 'if(allInterfacesCount>0){securitySetState("#security-exposure-status",`${allInterfacesCount} all-interface`,"attention");$("#security-exposure-detail").textContent="Wildcard listeners accept connections on all server interfaces. Internet reachability still depends on routing and firewall rules.";}else{securitySetState("#security-exposure-status","No wildcard listeners","ok");$("#security-exposure-detail").textContent="No all-interface TCP/UDP listeners were detected in this snapshot.";}'
if old_exposure not in js:
    raise SystemExit("security exposure marker not found")
js = js.replace(old_exposure, new_exposure, 1)
old_scope = 'badge.className=`security-scope ${listener.scope||"network"}`;badge.textContent=listener.scope==="public"?"Public":listener.scope==="local"?"Local only":"Bound address";'
new_scope = 'badge.className=`security-scope ${listener.scope||"network"}`;badge.textContent=listener.scope==="all_interfaces"?"All interfaces":listener.scope==="local"?"Local only":"Bound address";'
if old_scope not in js:
    raise SystemExit("security listener scope marker not found")
js = js.replace(old_scope, new_scope, 1)

security_functions = r'''
function openSecuritySSHDialog(){
const ssh=securitySnapshot?.ssh||{};clearError("#security-ssh-error");
$("#security-ssh-dialog-port").textContent=ssh.port||"—";
const keyDetected=!!ssh.root_key_detected;securitySetState("#security-ssh-dialog-key",keyDetected?"Root key detected":"Root key not detected",keyDetected?"ok":"attention");
const root=String(ssh.permit_root_login||"").toLowerCase();$("#security-ssh-root-policy").value=root==="yes"?"password_and_keys":["prohibit-password","without-password"].includes(root)?"keys_only":"keep";
const password=String(ssh.password_auth||"").toLowerCase();$("#security-ssh-password-policy").value=password==="yes"?"enabled":password==="no"?"disabled":"keep";
const note=$("#security-ssh-guard-note");note.classList.toggle("warning",!keyDetected);note.textContent=keyDetected?"HYZoraX detected a root authorized key. Restrictive SSH changes will still be validated before reload; existing SSH sessions are not stopped.":"No root authorized key was detected. HYZoraX will block changes that would remove password access and could lock you out.";
openDialog("#security-ssh-dialog");
}
async function applySecuritySSHPolicy(event){
event.preventDefault();const form=event.currentTarget;clearError("#security-ssh-error");
const rootLogin=$("#security-ssh-root-policy").value,passwordAuth=$("#security-ssh-password-policy").value;
if(rootLogin==="keep"&&passwordAuth==="keep"){closeDialog($("#security-ssh-dialog"));showToast("SSH policy unchanged.");return;}
const restrictive=rootLogin==="keys_only"||passwordAuth==="disabled";
const confirmed=await showPanelConfirmation({title:"Apply SSH security policy?",message:restrictive?"This changes future SSH logins. HYZoraX will validate the configuration and refuse the change if a safe root key path is not detected. Existing SSH sessions stay open.":"HYZoraX will validate the SSH configuration before reloading the service. Existing SSH sessions stay open.",confirmLabel:"Apply"});if(!confirmed)return;
setBusy(form,true);try{await request("api/v1/security/ssh/apply",{method:"POST",body:JSON.stringify({root_login:rootLogin,password_auth:passwordAuth})});closeDialog($("#security-ssh-dialog"));showToast("SSH security policy applied.");await loadSecurity();}catch(error){if(error.status===401){showLogin();return}showError("#security-ssh-error",error.message);}finally{setBusy(form,false);}
}
'''
load_marker = 'async function loadSecurity(){clearError("#security-error");'
if load_marker not in js:
    raise SystemExit("loadSecurity marker not found")
js = js.replace(load_marker, security_functions + '\n' + load_marker, 1)
listener_marker = '$("#nginx-install-button").addEventListener("click",()=>installApplication("nginx","Nginx"));'
if listener_marker not in js:
    raise SystemExit("listener insertion marker not found")
js = js.replace(listener_marker, '$("#security-ssh-manage").addEventListener("click",openSecuritySSHDialog);\n$("#security-ssh-form").addEventListener("submit",applySecuritySSHPolicy);\n' + listener_marker, 1)
write(js_path, js)

for rel in ("internal/web/assets_test.go", "internal/httpapi/app_test.go"):
    text = read(rel)
    if "1.7.0" not in text:
        raise SystemExit(f"V1.7.0 marker missing in {rel}")
    write(rel, text.replace("1.7.0", "1.7.1"))

print("Applied HYZoraX V1.7.1 guarded SSH Security controls")
