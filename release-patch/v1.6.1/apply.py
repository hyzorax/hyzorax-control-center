#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply.py <hyzorax-control-source-root>")
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

def replace_all(rel, old, new, label):
    text = read(rel)
    if old not in text:
        raise SystemExit(f"{label}: marker not found in {rel}")
    write(rel, text.replace(old, new))

nginx_manifest = r'''package installer

func NginxManifest() Manifest {
    return Manifest{
        SchemaVersion: ManifestSchemaVersion,
        ID:            "nginx",
        Name:          "Nginx",
        SupportedOS:   []OSConstraint{{ID: "ubuntu", Version: "24.04"}},
        Versions:      []VersionSpec{{Version: "ubuntu-24.04", Default: true}},
        Ports:          []PortSpec{{Protocol: "tcp", Port: 80, MustBeFree: true}},
        Resources: ResourceRequirements{
            MinMemoryBytes: 256 * 1024 * 1024,
            MinDiskBytes:   256 * 1024 * 1024,
        },
        Preflight: []CheckSpec{
            {ID: "arch-x86-64", Kind: "arch", Params: map[string]string{"value": "x86_64"}},
            {ID: "nginx-package-absent", Kind: "package_absent", Params: map[string]string{"name": "nginx"}},
            {ID: "nginx-service-absent", Kind: "service_absent", Params: map[string]string{"name": "nginx"}},
        },
        InstallSteps: []OperationSpec{
            {ID: "install-package", Action: "apt.package.install", Params: map[string]string{"name": "nginx"}},
            {ID: "enable-service", Action: "service.enable", Params: map[string]string{"name": "nginx"}},
            {ID: "start-service", Action: "service.start", Params: map[string]string{"name": "nginx"}},
        },
        HealthChecks: []CheckSpec{
            {ID: "nginx-config-valid", Kind: "config_valid", Params: map[string]string{"component": "nginx"}},
            {ID: "nginx-service-active", Kind: "service_active", Params: map[string]string{"name": "nginx"}},
            {ID: "nginx-local-http", Kind: "http_local", Params: map[string]string{"url": "http://127.0.0.1/"}},
        },
        UninstallSteps: []OperationSpec{
            {ID: "stop-service", Action: "service.stop", Params: map[string]string{"name": "nginx"}},
            {ID: "disable-service", Action: "service.disable", Params: map[string]string{"name": "nginx"}},
            {ID: "remove-package", Action: "apt.package.remove", Params: map[string]string{"name": "nginx"}},
        },
        RollbackPolicy: "required",
        RollbackSteps: []OperationSpec{
            {ID: "rollback-stop", Action: "service.stop", Params: map[string]string{"name": "nginx"}},
            {ID: "rollback-disable", Action: "service.disable", Params: map[string]string{"name": "nginx"}},
            {ID: "rollback-remove", Action: "apt.package.remove", Params: map[string]string{"name": "nginx"}},
        },
        BackupRequirements: nil,
    }
}

func BuiltinCatalog() (*Catalog, error) {
    return NewCatalog([]Manifest{NginxManifest()})
}
'''
write("internal/installer/builtin.go", nginx_manifest)

nginx_manifest_test = r'''package installer

import "testing"

func TestNginxManifestIsValidAndPlannable(t *testing.T) {
    manifest := NginxManifest()
    if err := ValidateManifest(manifest); err != nil {
        t.Fatal(err)
    }
    catalog, err := BuiltinCatalog()
    if err != nil {
        t.Fatal(err)
    }
    plan, err := catalog.BuildPlan([]string{"nginx"})
    if err != nil {
        t.Fatal(err)
    }
    if len(plan.Steps) != 1 || plan.Steps[0].ComponentID != "nginx" {
        t.Fatalf("unexpected Nginx plan: %#v", plan)
    }
    if len(manifest.Ports) != 1 || manifest.Ports[0].Port != 80 || !manifest.Ports[0].MustBeFree {
        t.Fatalf("Nginx port preflight changed unexpectedly: %#v", manifest.Ports)
    }
    if manifest.RollbackPolicy != "required" || len(manifest.RollbackSteps) == 0 {
        t.Fatal("Nginx rollback policy is not mandatory")
    }
}
'''
write("internal/installer/builtin_test.go", nginx_manifest_test)

# Expand typed health-check vocabulary. These are validation-only in this release;
# the root acceptance health checks are independently fixed in the helper.
manifest_path = "internal/installer/manifest.go"
manifest = read(manifest_path)
old_checks = '''var allowedCheckKinds = map[string]struct{}{
	"arch":            {},
	"disk":            {},
	"memory":          {},
	"os":              {},
	"package_absent":  {},
	"path_writable":   {},
	"port_free":       {},
	"service_absent":  {},
}'''
if old_checks not in manifest:
    old_checks = '''var allowedCheckKinds = map[string]struct{}{
    "arch": {},
    "disk": {},
    "memory": {},
    "os": {},
    "package_absent": {},
    "path_writable": {},
    "port_free": {},
    "service_absent": {},
}'''
new_checks = '''var allowedCheckKinds = map[string]struct{}{
	"arch":            {},
	"config_valid":    {},
	"disk":            {},
	"http_local":      {},
	"memory":          {},
	"os":              {},
	"package_absent":  {},
	"path_writable":   {},
	"port_free":       {},
	"service_absent":  {},
	"service_active":  {},
}'''
if old_checks not in manifest:
    raise SystemExit("allowed check kinds marker not found")
write(manifest_path, manifest.replace(old_checks, new_checks, 1))

helper_nginx = r'''//go:build linux

package helper

import (
    "bytes"
    "context"
    "errors"
    "fmt"
    "net/http"
    "os"
    "os/exec"
    "strings"
    "time"
)

const nginxServiceName = "nginx"
const nginxConfigDirectory = "/etc/nginx"

func installerNginxPreflight(ctx context.Context) (map[string]any, *Error) {
    if os.Geteuid() != 0 {
        return nil, &Error{Code: "installer_privilege_required", Message: "Nginx installer must run in the privileged helper"}
    }
    installed, err := dpkgPackageInstalled(ctx, "nginx")
    if err != nil {
        return nil, &Error{Code: "preflight_failed", Message: "Nginx package state could not be determined"}
    }
    if installed {
        return nil, &Error{Code: "component_exists", Message: "Nginx is already installed; clean-install acceptance will not overwrite it"}
    }
    if _, err := os.Lstat(nginxConfigDirectory); err == nil {
        return nil, &Error{Code: "config_exists", Message: "Existing /etc/nginx prevents clean Nginx installation"}
    } else if !errors.Is(err, os.ErrNotExist) {
        return nil, &Error{Code: "preflight_failed", Message: "Existing Nginx configuration path could not be inspected"}
    }
    free, err := tcpPortFree(ctx, 80)
    if err != nil {
        return nil, &Error{Code: "preflight_failed", Message: "TCP port 80 availability could not be determined"}
    }
    if !free {
        return nil, &Error{Code: "port_in_use", Message: "TCP port 80 is already in use; HYZoraX will not reclaim it"}
    }
    return map[string]any{
        "component": "nginx",
        "ready": true,
        "port_80_free": true,
        "existing_package": false,
        "existing_config": false,
        "firewall_changed": false,
    }, nil
}

func installerNginxInstall(ctx context.Context) (map[string]any, *Error) {
    if _, preflightError := installerNginxPreflight(ctx); preflightError != nil {
        return nil, preflightError
    }
    if err := runApt(ctx, "update"); err != nil {
        return nil, &Error{Code: "apt_update_failed", Message: "Ubuntu package index update failed"}
    }
    if err := runApt(ctx, "install", "nginx"); err != nil {
        return nil, &Error{Code: "package_install_failed", Message: "Nginx package installation failed"}
    }
    if err := runSystemctl(ctx, "enable", nginxServiceName); err != nil {
        return nil, &Error{Code: "service_enable_failed", Message: "Nginx could not be enabled at boot"}
    }
    if err := runSystemctl(ctx, "restart", nginxServiceName); err != nil {
        return nil, &Error{Code: "service_start_failed", Message: "Nginx could not be started"}
    }
    health, operationError := installerNginxHealth(ctx)
    if operationError != nil {
        return nil, operationError
    }
    health["installed"] = true
    health["firewall_changed"] = false
    return health, nil
}

func installerNginxHealth(ctx context.Context) (map[string]any, *Error) {
    configOutput, err := runCommandCombined(ctx, nil, "/usr/sbin/nginx", "-t")
    if err != nil {
        return nil, &Error{Code: "config_invalid", Message: "Nginx configuration test failed"}
    }
    if err := runSystemctl(ctx, "is-active", "--quiet", nginxServiceName); err != nil {
        return nil, &Error{Code: "service_unhealthy", Message: "Nginx service is not active"}
    }
    client := &http.Client{Timeout: 3 * time.Second}
    request, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://127.0.0.1/", nil)
    if err != nil {
        return nil, &Error{Code: "health_check_failed", Message: "Nginx local HTTP health request could not be created"}
    }
    response, err := client.Do(request)
    if err != nil {
        return nil, &Error{Code: "http_health_failed", Message: "Nginx did not answer the local HTTP health check"}
    }
    _ = response.Body.Close()
    if response.StatusCode < 200 || response.StatusCode >= 500 {
        return nil, &Error{Code: "http_health_failed", Message: fmt.Sprintf("Nginx local HTTP health returned status %d", response.StatusCode)}
    }
    versionOutput, _ := runCommandCombined(ctx, nil, "/usr/sbin/nginx", "-v")
    return map[string]any{
        "component": "nginx",
        "active": true,
        "config_valid": true,
        "local_http_status": response.StatusCode,
        "version": strings.TrimSpace(string(versionOutput)),
        "config_test": strings.TrimSpace(string(configOutput)),
    }, nil
}

func installerNginxRollback(ctx context.Context) (map[string]any, *Error) {
    _ = runSystemctl(ctx, "disable", "--now", nginxServiceName)
    if err := runApt(ctx, "purge", "nginx", "nginx-common"); err != nil {
        return nil, &Error{Code: "rollback_failed", Message: "Nginx package rollback failed"}
    }
    installed, err := dpkgPackageInstalled(ctx, "nginx")
    if err != nil {
        return nil, &Error{Code: "rollback_verify_failed", Message: "Nginx rollback state could not be verified"}
    }
    if installed {
        return nil, &Error{Code: "rollback_verify_failed", Message: "Nginx remains installed after rollback"}
    }
    return map[string]any{"component": "nginx", "rolled_back": true, "firewall_changed": false}, nil
}

func runApt(ctx context.Context, operation string, packages ...string) error {
    args := []string{"-o", "DPkg::Lock::Timeout=120", "-o", "Acquire::Retries=3", "-y"}
    switch operation {
    case "update":
        args = append(args, "update")
    case "install":
        if len(packages) != 1 || packages[0] != "nginx" { return errors.New("package is not allow-listed") }
        args = append(args, "--no-install-recommends", "install", "nginx")
    case "purge":
        if len(packages) != 2 || packages[0] != "nginx" || packages[1] != "nginx-common" { return errors.New("package rollback set is not allow-listed") }
        args = append(args, "purge", "nginx", "nginx-common")
    default:
        return errors.New("apt operation is not allow-listed")
    }
    environment := append(os.Environ(), "DEBIAN_FRONTEND=noninteractive", "NEEDRESTART_MODE=l")
    _, err := runCommandCombined(ctx, environment, "/usr/bin/apt-get", args...)
    return err
}

func runSystemctl(ctx context.Context, action string, extra ...string) error {
    allowed := false
    switch action {
    case "enable", "restart", "is-active": allowed = true
    case "disable": allowed = len(extra) == 2 && extra[0] == "--now" && extra[1] == nginxServiceName
    }
    if !allowed { return errors.New("systemctl action is not allow-listed") }
    if action != "disable" {
        if len(extra) == 0 || extra[len(extra)-1] != nginxServiceName { return errors.New("service is not allow-listed") }
    }
    args := append([]string{action}, extra...)
    _, err := runCommandCombined(ctx, nil, "/usr/bin/systemctl", args...)
    return err
}

func dpkgPackageInstalled(ctx context.Context, name string) (bool, error) {
    if name != "nginx" { return false, errors.New("package is not allow-listed") }
    output, err := runCommandCombined(ctx, nil, "/usr/bin/dpkg-query", "-W", "-f=${Status}", name)
    if err != nil {
        var exitError *exec.ExitError
        if errors.As(err, &exitError) { return false, nil }
        return false, err
    }
    return strings.TrimSpace(string(output)) == "install ok installed", nil
}

func tcpPortFree(ctx context.Context, port int) (bool, error) {
    if port != 80 { return false, errors.New("port is not allow-listed") }
    output, err := runCommandCombined(ctx, nil, "/usr/bin/ss", "-H", "-ltn", "sport", "=", ":80")
    if err != nil { return false, err }
    return strings.TrimSpace(string(output)) == "", nil
}

func runCommandCombined(ctx context.Context, environment []string, executable string, args ...string) ([]byte, error) {
    command := exec.CommandContext(ctx, executable, args...)
    if environment != nil { command.Env = environment }
    var output bytes.Buffer
    command.Stdout = &output
    command.Stderr = &output
    err := command.Run()
    return output.Bytes(), err
}
'''
write("internal/helper/installer_nginx_linux.go", helper_nginx)

integration_test = r'''//go:build integration && linux

package helper

import (
    "context"
    "os"
    "testing"
    "time"
)

func TestNginxInstallerAcceptance(t *testing.T) {
    if os.Getenv("HYZORAX_INSTALLER_ACCEPTANCE") != "1" { t.Skip("real installer acceptance is opt-in") }
    if os.Geteuid() != 0 { t.Fatal("real installer acceptance must run as root") }
    ctx, cancel := context.WithTimeout(context.Background(), 8*time.Minute)
    defer cancel()
    server := &Server{}
    call := func(action string) Response {
        t.Helper()
        return server.dispatch(ctx, Request{Version: ProtocolVersion, ID: action, CorrelationID: "v161-acceptance", ActorID: "github-actions", Action: action, Target: "nginx"})
    }
    defer func(){ _ = call("installer.nginx.rollback") }()
    preflight := call("installer.nginx.preflight")
    if !preflight.OK || preflight.Error != nil { t.Fatalf("preflight failed: %+v", preflight) }
    install := call("installer.nginx.install")
    if !install.OK || install.Error != nil { t.Fatalf("install failed: %+v", install) }
    health := call("installer.nginx.health")
    if !health.OK || health.Error != nil || health.Data["active"] != true || health.Data["config_valid"] != true { t.Fatalf("health failed: %+v", health) }
    rollback := call("installer.nginx.rollback")
    if !rollback.OK || rollback.Error != nil || rollback.Data["rolled_back"] != true { t.Fatalf("rollback failed: %+v", rollback) }
}
'''
write("internal/helper/installer_nginx_acceptance_test.go", integration_test)

# Bump helper protocol: new privileged action surface.
replace_once("internal/helper/protocol.go", "const ProtocolVersion = 10", "const ProtocolVersion = 11", "helper protocol")

server_path = "internal/helper/server_linux.go"
server = read(server_path)
# Installer operations need package-manager time; preserve existing filesystem timeout extension.
old_timeout = '''	timeout := 15 * time.Second
	if request.Action == "filesystem.delete" || request.Action == "filesystem.trash" || request.Action == "filesystem.recycle.purge" {
		timeout = 60 * time.Second
	}'''
new_timeout = '''	timeout := 15 * time.Second
	if request.Action == "filesystem.delete" || request.Action == "filesystem.trash" || request.Action == "filesystem.recycle.purge" {
		timeout = 60 * time.Second
	}
	if strings.HasPrefix(request.Action, "installer.nginx.") {
		timeout = 10 * time.Minute
	}'''
if old_timeout not in server:
    # V1.5 base used a direct 15-second context; V1.6.0 should have the extended block, but fail closed if not.
    raise SystemExit("helper timeout marker not found")
server = server.replace(old_timeout, new_timeout, 1)
marker = '''	default:
		response.Error = &Error{Code: "action_denied", Message: "action is not allow-listed"}
		return response
	}
}'''
installer_cases = '''	case "installer.nginx.preflight":
		if request.Target != "nginx" || len(request.Params) != 0 {
			response.Error = &Error{Code: "invalid_request", Message: "Nginx installer request must not contain arbitrary parameters"}
			return response
		}
		data, operationError := installerNginxPreflight(ctx)
		if operationError != nil { response.Error = operationError; return response }
		response.OK = true; response.Data = data; return response
	case "installer.nginx.install":
		if request.Target != "nginx" || len(request.Params) != 0 {
			response.Error = &Error{Code: "invalid_request", Message: "Nginx installer request must not contain arbitrary parameters"}
			return response
		}
		data, operationError := installerNginxInstall(ctx)
		if operationError != nil { response.Error = operationError; return response }
		response.OK = true; response.Data = data; return response
	case "installer.nginx.health":
		if request.Target != "nginx" || len(request.Params) != 0 {
			response.Error = &Error{Code: "invalid_request", Message: "Nginx health request must not contain arbitrary parameters"}
			return response
		}
		data, operationError := installerNginxHealth(ctx)
		if operationError != nil { response.Error = operationError; return response }
		response.OK = true; response.Data = data; return response
	case "installer.nginx.rollback":
		if request.Target != "nginx" || len(request.Params) != 0 {
			response.Error = &Error{Code: "invalid_request", Message: "Nginx rollback request must not contain arbitrary parameters"}
			return response
		}
		data, operationError := installerNginxRollback(ctx)
		if operationError != nil { response.Error = operationError; return response }
		response.OK = true; response.Data = data; return response
'''
if marker not in server:
    raise SystemExit("helper dispatch default marker not found")
server = server.replace(marker, installer_cases + marker, 1)
write(server_path, server)

policy_test_path = "internal/helper/policy_test.go"
policy_test = read(policy_test_path)
extra_test = r'''
func TestInstallerNginxActionsRejectParametersAndWrongTarget(t *testing.T) {
    server := &Server{}
    base := Request{Version: ProtocolVersion, ID: "id", CorrelationID: "correlation", ActorID: "actor", Action: "installer.nginx.preflight"}
    wrongTarget := base; wrongTarget.Target = "apache2"
    response := server.dispatch(context.Background(), wrongTarget)
    if response.OK || response.Error == nil || response.Error.Code != "invalid_request" { t.Fatalf("wrong target accepted: %+v", response) }
    withParams := base; withParams.Target = "nginx"; withParams.Params = []byte(`{"package":"curl"}`)
    response = server.dispatch(context.Background(), withParams)
    if response.OK || response.Error == nil || response.Error.Code != "invalid_request" { t.Fatalf("arbitrary installer params accepted: %+v", response) }
}
'''
policy_test += extra_test
write(policy_test_path, policy_test)

replace_all("internal/web/static/index.html", "Version 1.6.0", "Version 1.6.1", "UI version")
replace_all("internal/web/assets_test.go", "1.6.0", "1.6.1", "asset version")
replace_all("internal/httpapi/app_test.go", "Version 1.6.0", "Version 1.6.1", "HTTP UI version")
print("Applied HYZoraX Control Panel V1.6.1 Nginx installer acceptance")
