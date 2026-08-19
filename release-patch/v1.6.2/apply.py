#!/usr/bin/env python3
from pathlib import Path
import re
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

builtin_path = "internal/installer/builtin.go"
builtin = read(builtin_path)
if "func PHP84Manifest()" not in builtin:
    insert = r'''

func PHP84Manifest() Manifest {
    return Manifest{
        SchemaVersion: ManifestSchemaVersion,
        ID:            "php84",
        Name:          "PHP 8.4 FPM",
        SupportedOS:   []OSConstraint{{ID: "ubuntu", Version: "24.04"}},
        Versions:      []VersionSpec{{Version: "8.4", Default: true, Repository: "ondrej-php"}},
        Repositories: []RepositorySpec{{
            ID:             "ondrej-php",
            Kind:           "apt",
            Source:         "https://ppa.launchpadcontent.net/ondrej/php/ubuntu noble main",
            KeyFingerprint: "B8DC7E53946656EFBCE4C1DD71DAEAAB4AD4CAB6",
        }},
        Resources: ResourceRequirements{
            MinMemoryBytes: 256 * 1024 * 1024,
            MinDiskBytes:   512 * 1024 * 1024,
        },
        Preflight: []CheckSpec{
            {ID: "arch-x86-64", Kind: "arch", Params: map[string]string{"value": "x86_64"}},
            {ID: "php84-package-absent", Kind: "package_absent", Params: map[string]string{"name": "php8.4-fpm"}},
            {ID: "php84-service-absent", Kind: "service_absent", Params: map[string]string{"name": "php8.4-fpm"}},
        },
        InstallSteps: []OperationSpec{
            {ID: "ensure-php-repository", Action: "apt.repository.ensure", Params: map[string]string{"id": "ondrej-php"}},
            {ID: "install-php84-packages", Action: "apt.package.install", Params: map[string]string{"set": "php84-core"}},
            {ID: "enable-php84-fpm", Action: "service.enable", Params: map[string]string{"name": "php8.4-fpm"}},
            {ID: "start-php84-fpm", Action: "service.start", Params: map[string]string{"name": "php8.4-fpm"}},
        },
        HealthChecks: []CheckSpec{
            {ID: "php84-config-valid", Kind: "config_valid", Params: map[string]string{"component": "php84"}},
            {ID: "php84-service-active", Kind: "service_active", Params: map[string]string{"name": "php8.4-fpm"}},
            {ID: "php84-unix-socket", Kind: "unix_socket", Params: map[string]string{"path": "/run/php/php8.4-fpm.sock"}},
            {ID: "php84-modules", Kind: "php_modules", Params: map[string]string{"profile": "hyzorax-core"}},
        },
        UninstallSteps: []OperationSpec{
            {ID: "stop-php84-fpm", Action: "service.stop", Params: map[string]string{"name": "php8.4-fpm"}},
            {ID: "disable-php84-fpm", Action: "service.disable", Params: map[string]string{"name": "php8.4-fpm"}},
            {ID: "remove-php84-packages", Action: "apt.package.remove", Params: map[string]string{"set": "php84-core"}},
        },
        RollbackPolicy: "required",
        RollbackSteps: []OperationSpec{
            {ID: "rollback-stop-php84", Action: "service.stop", Params: map[string]string{"name": "php8.4-fpm"}},
            {ID: "rollback-remove-packages", Action: "apt.package.remove", Params: map[string]string{"set": "php84-core"}},
            {ID: "rollback-remove-repository", Action: "file.remove", Params: map[string]string{"managed": "ondrej-php-repository"}},
        },
    }
}
'''
    marker = "func BuiltinCatalog() (*Catalog, error) {"
    if marker not in builtin:
        raise SystemExit("BuiltinCatalog marker not found")
    builtin = builtin.replace(marker, insert + "\n" + marker, 1)
    builtin = builtin.replace("return NewCatalog([]Manifest{NginxManifest()})", "return NewCatalog([]Manifest{NginxManifest(), PHP84Manifest()})", 1)
    write(builtin_path, builtin)

# Add typed PHP health vocabulary while preserving prior check kinds.
manifest_path = "internal/installer/manifest.go"
manifest = read(manifest_path)
match = re.search(r'var allowedCheckKinds = map\[string\]struct\{\}\{\n(?P<body>.*?)\n\}', manifest, re.DOTALL)
if not match:
    raise SystemExit("allowedCheckKinds block not found")
body = match.group("body")
entries = set(re.findall(r'"([a-z_]+)"\s*:', body))
entries.update({"unix_socket", "php_modules"})
new_body = "\n".join(f'\t"{name}": {{}} ,' for name in sorted(entries)).replace("{} ,", "{},")
new_block = "var allowedCheckKinds = map[string]struct{}{\n" + new_body + "\n}"
manifest = manifest[:match.start()] + new_block + manifest[match.end():]
write(manifest_path, manifest)

php_test = r'''package installer

import "testing"

func TestPHP84ManifestIsValidAndPinned(t *testing.T) {
    manifest := PHP84Manifest()
    if err := ValidateManifest(manifest); err != nil { t.Fatal(err) }
    if len(manifest.Repositories) != 1 { t.Fatalf("repositories=%#v", manifest.Repositories) }
    repo := manifest.Repositories[0]
    if repo.ID != "ondrej-php" || repo.Source != "https://ppa.launchpadcontent.net/ondrej/php/ubuntu noble main" {
        t.Fatalf("unexpected PHP repository: %#v", repo)
    }
    if repo.KeyFingerprint != "B8DC7E53946656EFBCE4C1DD71DAEAAB4AD4CAB6" {
        t.Fatalf("unexpected PHP repository fingerprint: %q", repo.KeyFingerprint)
    }
    if manifest.RollbackPolicy != "required" || len(manifest.RollbackSteps) == 0 { t.Fatal("PHP rollback must be required") }
    catalog, err := BuiltinCatalog(); if err != nil { t.Fatal(err) }
    plan, err := catalog.BuildPlan([]string{"php84"}); if err != nil { t.Fatal(err) }
    if len(plan.Steps) != 1 || plan.Steps[0].ComponentID != "php84" { t.Fatalf("plan=%#v", plan) }
}
'''
write("internal/installer/php84_test.go", php_test)

helper_php = r'''//go:build linux

package helper

import (
    "bufio"
    "context"
    "errors"
    "fmt"
    "os"
    "os/exec"
    "path/filepath"
    "sort"
    "strings"
)

const php84ServiceName = "php8.4-fpm"
const php84ConfigDirectory = "/etc/php/8.4"
const php84SocketPath = "/run/php/php8.4-fpm.sock"
const php84PPA = "ppa:ondrej/php"
const php84RepositoryURL = "ppa.launchpadcontent.net/ondrej/php/ubuntu"
const php84RepositoryFingerprint = "B8DC7E53946656EFBCE4C1DD71DAEAAB4AD4CAB6"

var php84Packages = []string{
    "php8.4-fpm", "php8.4-cli", "php8.4-common", "php8.4-opcache", "php8.4-readline",
    "php8.4-bcmath", "php8.4-curl", "php8.4-gd", "php8.4-intl", "php8.4-mbstring",
    "php8.4-mysql", "php8.4-pgsql", "php8.4-sqlite3", "php8.4-xml", "php8.4-zip", "php8.4-redis",
}

var php84RequiredModules = []string{
    "bcmath", "curl", "gd", "intl", "mbstring", "mysqli", "mysqlnd", "pdo", "pdo_mysql",
    "pdo_pgsql", "pdo_sqlite", "pgsql", "redis", "sqlite3", "xml", "zip", "zend opcache",
}

func installerPHP84Preflight(ctx context.Context) (map[string]any, *Error) {
    if os.Geteuid() != 0 { return nil, &Error{Code:"installer_privilege_required", Message:"PHP 8.4 installer must run in the privileged helper"} }
    osID, osVersion, err := php84OSRelease()
    if err != nil || osID != "ubuntu" || osVersion != "24.04" { return nil, &Error{Code:"unsupported_os", Message:"PHP 8.4 installer supports Ubuntu 24.04 only"} }
    archCommand := exec.CommandContext(ctx, "/usr/bin/uname", "-m")
    archOutput, err := archCommand.CombinedOutput()
    if err != nil || strings.TrimSpace(string(archOutput)) != "x86_64" { return nil, &Error{Code:"unsupported_arch", Message:"PHP 8.4 installer supports x86-64 only"} }
    if php84InstallationExists(ctx) { return nil, &Error{Code:"component_exists", Message:"PHP 8.4 is already installed or configured; clean-install acceptance will not overwrite it"} }
    repositoryPresent, err := php84RepositoryPresent()
    if err != nil { return nil, &Error{Code:"preflight_failed", Message:"PHP repository state could not be inspected"} }
    if repositoryPresent { return nil, &Error{Code:"repository_exists", Message:"Ondrej PHP repository already exists; HYZoraX will not adopt or overwrite it"} }
    return map[string]any{"component":"php84","ready":true,"existing_php84":false,"existing_repository":false,"public_listener":false}, nil
}

func installerPHP84Install(ctx context.Context) (map[string]any, *Error) {
    if _, operationError := installerPHP84Preflight(ctx); operationError != nil { return nil, operationError }
    if err := php84AptPrerequisites(ctx); err != nil { return nil, &Error{Code:"prerequisite_install_failed", Message:"PHP repository prerequisites could not be installed"} }
    if err := php84AddRepository(ctx); err != nil { return nil, &Error{Code:"repository_add_failed", Message:"Ondrej PHP repository could not be added"} }
    if err := php84VerifyRepository(ctx); err != nil {
        _ = php84RemoveRepository(ctx)
        return nil, &Error{Code:"repository_verification_failed", Message:"PHP repository signing fingerprint verification failed"}
    }
    if err := php84AptUpdate(ctx); err != nil { _ = php84RemoveRepository(ctx); return nil, &Error{Code:"apt_update_failed", Message:"Ubuntu package index update failed after adding PHP repository"} }
    if err := php84AptInstall(ctx); err != nil { _, _ = installerPHP84Rollback(ctx); return nil, &Error{Code:"package_install_failed", Message:"PHP 8.4 package installation failed"} }
    if err := php84Systemctl(ctx, "enable"); err != nil { _, _ = installerPHP84Rollback(ctx); return nil, &Error{Code:"service_enable_failed", Message:"PHP 8.4 FPM could not be enabled"} }
    if err := php84Systemctl(ctx, "restart"); err != nil { _, _ = installerPHP84Rollback(ctx); return nil, &Error{Code:"service_start_failed", Message:"PHP 8.4 FPM could not be started"} }
    health, operationError := installerPHP84Health(ctx)
    if operationError != nil { _, _ = installerPHP84Rollback(ctx); return nil, operationError }
    health["installed"] = true
    health["repository_fingerprint"] = php84RepositoryFingerprint
    return health, nil
}

func installerPHP84Health(ctx context.Context) (map[string]any, *Error) {
    configCommand := exec.CommandContext(ctx, "/usr/sbin/php-fpm8.4", "-t")
    configOutput, err := configCommand.CombinedOutput()
    if err != nil { return nil, &Error{Code:"config_invalid", Message:"PHP 8.4 FPM configuration test failed"} }
    if err := php84Systemctl(ctx, "is-active"); err != nil { return nil, &Error{Code:"service_unhealthy", Message:"PHP 8.4 FPM service is not active"} }
    info, err := os.Stat(php84SocketPath)
    if err != nil || info.Mode()&os.ModeSocket == 0 { return nil, &Error{Code:"socket_missing", Message:"PHP 8.4 FPM Unix socket is not available"} }
    listen, err := php84PoolListen()
    if err != nil || listen != php84SocketPath { return nil, &Error{Code:"public_listener_blocked", Message:"PHP 8.4 FPM must use the expected Unix socket and no public TCP listener"} }
    versionCommand := exec.CommandContext(ctx, "/usr/bin/php8.4", "-v")
    versionOutput, err := versionCommand.CombinedOutput()
    if err != nil || !strings.Contains(string(versionOutput), "PHP 8.4") { return nil, &Error{Code:"version_check_failed", Message:"PHP 8.4 CLI version check failed"} }
    modulesCommand := exec.CommandContext(ctx, "/usr/bin/php8.4", "-m")
    modulesOutput, err := modulesCommand.CombinedOutput()
    if err != nil { return nil, &Error{Code:"module_check_failed", Message:"PHP 8.4 module inventory failed"} }
    modules := map[string]bool{}
    scanner := bufio.NewScanner(strings.NewReader(string(modulesOutput)))
    for scanner.Scan() { value := strings.ToLower(strings.TrimSpace(scanner.Text())); if value != "" && !strings.HasPrefix(value,"[") { modules[value]=true } }
    var missing []string
    for _, required := range php84RequiredModules { if !modules[required] { missing = append(missing, required) } }
    if len(missing) > 0 { return nil, &Error{Code:"module_check_failed", Message:"Required PHP 8.4 modules are missing: "+strings.Join(missing, ", ")} }
    return map[string]any{"component":"php84","active":true,"config_valid":true,"socket":php84SocketPath,"public_listener":false,"version":strings.TrimSpace(strings.Split(string(versionOutput),"\n")[0]),"config_test":strings.TrimSpace(string(configOutput)),"required_modules":len(php84RequiredModules)}, nil
}

func installerPHP84Rollback(ctx context.Context) (map[string]any, *Error) {
    _ = php84Systemctl(ctx, "disable-now")
    if err := php84AptPurge(ctx); err != nil { return nil, &Error{Code:"rollback_failed", Message:"PHP 8.4 package rollback failed"} }
    if err := php84RemoveRepository(ctx); err != nil { return nil, &Error{Code:"rollback_failed", Message:"PHP repository rollback failed"} }
    _ = php84AptUpdate(ctx)
    if php84InstallationExists(ctx) { return nil, &Error{Code:"rollback_verify_failed", Message:"PHP 8.4 remains installed or configured after rollback"} }
    repositoryPresent, err := php84RepositoryPresent()
    if err != nil || repositoryPresent { return nil, &Error{Code:"rollback_verify_failed", Message:"PHP repository remains configured after rollback"} }
    return map[string]any{"component":"php84","rolled_back":true,"repository_removed":true,"public_listener":false}, nil
}

func php84OSRelease() (string,string,error) {
    content, err := os.ReadFile("/etc/os-release"); if err != nil { return "","",err }
    values := map[string]string{}
    scanner := bufio.NewScanner(strings.NewReader(string(content)))
    for scanner.Scan() { line:=strings.TrimSpace(scanner.Text()); if line=="" || strings.HasPrefix(line,"#") { continue }; parts:=strings.SplitN(line,"=",2); if len(parts)==2 { values[parts[0]]=strings.Trim(parts[1],"\"") } }
    return values["ID"], values["VERSION_ID"], scanner.Err()
}

func php84InstallationExists(ctx context.Context) bool {
    for _, path := range []string{"/usr/bin/php8.4","/usr/sbin/php-fpm8.4",php84ConfigDirectory} { if _,err:=os.Lstat(path); err==nil { return true } }
    command := exec.CommandContext(ctx, "/usr/bin/dpkg-query", "-W", "-f=${Status}", "php8.4-fpm")
    output, err := command.CombinedOutput(); return err==nil && strings.TrimSpace(string(output))=="install ok installed"
}

func php84RepositoryPresent() (bool,error) {
    paths := []string{"/etc/apt/sources.list"}
    matches, err := filepath.Glob("/etc/apt/sources.list.d/*"); if err != nil { return false,err }; paths=append(paths,matches...)
    for _, path := range paths { content,err:=os.ReadFile(path); if err!=nil { if errors.Is(err,os.ErrNotExist){continue}; continue }; if strings.Contains(string(content),php84RepositoryURL) || strings.Contains(string(content),php84PPA) { return true,nil } }
    return false,nil
}

func php84AptPrerequisites(ctx context.Context) error {
    args:=[]string{"-o","DPkg::Lock::Timeout=120","-o","Acquire::Retries=3","-y","--no-install-recommends","install","software-properties-common","gnupg","ca-certificates"}
    command:=exec.CommandContext(ctx,"/usr/bin/apt-get",args...); command.Env=append(os.Environ(),"DEBIAN_FRONTEND=noninteractive","NEEDRESTART_MODE=l"); _,err:=command.CombinedOutput(); return err
}
func php84AptUpdate(ctx context.Context) error { command:=exec.CommandContext(ctx,"/usr/bin/apt-get","-o","DPkg::Lock::Timeout=120","-o","Acquire::Retries=3","update"); command.Env=append(os.Environ(),"DEBIAN_FRONTEND=noninteractive"); _,err:=command.CombinedOutput(); return err }
func php84AptInstall(ctx context.Context) error { args:=[]string{"-o","DPkg::Lock::Timeout=120","-o","Acquire::Retries=3","-y","--no-install-recommends","install"}; args=append(args,php84Packages...); command:=exec.CommandContext(ctx,"/usr/bin/apt-get",args...); command.Env=append(os.Environ(),"DEBIAN_FRONTEND=noninteractive","NEEDRESTART_MODE=l"); _,err:=command.CombinedOutput(); return err }
func php84AptPurge(ctx context.Context) error { args:=[]string{"-o","DPkg::Lock::Timeout=120","-y","purge"}; args=append(args,php84Packages...); command:=exec.CommandContext(ctx,"/usr/bin/apt-get",args...); command.Env=append(os.Environ(),"DEBIAN_FRONTEND=noninteractive","NEEDRESTART_MODE=l"); _,err:=command.CombinedOutput(); return err }

func php84AddRepository(ctx context.Context) error { command:=exec.CommandContext(ctx,"/usr/bin/add-apt-repository","--yes",php84PPA); command.Env=append(os.Environ(),"LC_ALL=C.UTF-8"); _,err:=command.CombinedOutput(); return err }
func php84RemoveRepository(ctx context.Context) error { present,err:=php84RepositoryPresent(); if err!=nil || !present { return err }; command:=exec.CommandContext(ctx,"/usr/bin/add-apt-repository","--yes","--remove",php84PPA); command.Env=append(os.Environ(),"LC_ALL=C.UTF-8"); _,commandErr:=command.CombinedOutput(); return commandErr }

func php84VerifyRepository(ctx context.Context) error {
    present,err:=php84RepositoryPresent(); if err!=nil || !present { return errors.New("expected PHP repository source is missing") }
    candidates:=[]string{"/etc/apt/trusted.gpg"}
    for _,pattern:=range []string{"/etc/apt/trusted.gpg.d/*","/etc/apt/keyrings/*"} { matches,_:=filepath.Glob(pattern); candidates=append(candidates,matches...) }
    for _,path:=range candidates { info,err:=os.Stat(path); if err!=nil || !info.Mode().IsRegular(){continue}; command:=exec.CommandContext(ctx,"/usr/bin/gpg","--batch","--show-keys","--with-colons",path); output,err:=command.CombinedOutput(); if err!=nil{continue}; for _,line:=range strings.Split(string(output),"\n") { fields:=strings.Split(line,":"); if len(fields)>9 && fields[0]=="fpr" && strings.EqualFold(fields[9],php84RepositoryFingerprint){return nil} } }
    return errors.New("expected PHP repository signing fingerprint was not found")
}

func php84Systemctl(ctx context.Context, action string) error { var args []string; switch action { case "enable": args=[]string{"enable",php84ServiceName}; case "restart":args=[]string{"restart",php84ServiceName}; case "is-active":args=[]string{"is-active","--quiet",php84ServiceName}; case "disable-now":args=[]string{"disable","--now",php84ServiceName}; default:return errors.New("systemctl action is not allow-listed") }; command:=exec.CommandContext(ctx,"/usr/bin/systemctl",args...); _,err:=command.CombinedOutput(); return err }

func php84PoolListen() (string,error) { content,err:=os.ReadFile("/etc/php/8.4/fpm/pool.d/www.conf"); if err!=nil{return "",err}; scanner:=bufio.NewScanner(strings.NewReader(string(content))); for scanner.Scan(){ line:=strings.TrimSpace(scanner.Text()); if line==""||strings.HasPrefix(line,";"){continue}; if strings.HasPrefix(line,"listen") { parts:=strings.SplitN(line,"=",2); if len(parts)==2 && strings.TrimSpace(parts[0])=="listen" { return strings.TrimSpace(parts[1]),nil } } }; return "",fmt.Errorf("PHP FPM listen directive not found") }

func php84PackageList() []string { result:=append([]string(nil),php84Packages...); sort.Strings(result); return result }
'''
write("internal/helper/installer_php84_linux.go", helper_php)

acceptance = r'''//go:build integration && linux

package helper

import (
    "context"
    "os"
    "testing"
    "time"
)

func TestPHP84InstallerAcceptance(t *testing.T) {
    if os.Getenv("HYZORAX_INSTALLER_ACCEPTANCE")!="1" { t.Skip("real installer acceptance is opt-in") }
    if os.Geteuid()!=0 { t.Fatal("real installer acceptance must run as root") }
    ctx,cancel:=context.WithTimeout(context.Background(),12*time.Minute);defer cancel()
    server:=&Server{}
    call:=func(action string) Response { t.Helper(); return server.dispatch(ctx,Request{Version:ProtocolVersion,ID:action,CorrelationID:"v162-acceptance",ActorID:"github-actions",Action:action,Target:"php84"}) }
    defer func(){ _=call("installer.php84.rollback") }()
    preflight:=call("installer.php84.preflight"); if !preflight.OK||preflight.Error!=nil{t.Fatalf("preflight failed: %+v",preflight)}
    install:=call("installer.php84.install"); if !install.OK||install.Error!=nil{t.Fatalf("install failed: %+v",install)}
    health:=call("installer.php84.health"); if !health.OK||health.Error!=nil||health.Data["active"]!=true||health.Data["config_valid"]!=true||health.Data["public_listener"]!=false{t.Fatalf("health failed: %+v",health)}
    rollback:=call("installer.php84.rollback"); if !rollback.OK||rollback.Error!=nil||rollback.Data["rolled_back"]!=true{t.Fatalf("rollback failed: %+v",rollback)}
}

func TestPHP84InstallerRejectsExistingState(t *testing.T) {
    if os.Getenv("HYZORAX_INSTALLER_ACCEPTANCE")!="1" { t.Skip("real installer acceptance is opt-in") }
    if os.Geteuid()!=0 { t.Fatal("real installer acceptance must run as root") }
    ctx,cancel:=context.WithTimeout(context.Background(),30*time.Second);defer cancel()
    if !php84InstallationExists(ctx) { present,_:=php84RepositoryPresent(); if !present { t.Skip("runner has no existing PHP 8.4/repository state") } }
    server:=&Server{}
    response:=server.dispatch(ctx,Request{Version:ProtocolVersion,ID:"existing-php84",CorrelationID:"v162-existing",ActorID:"github-actions",Action:"installer.php84.preflight",Target:"php84"})
    if response.OK||response.Error==nil||(response.Error.Code!="component_exists"&&response.Error.Code!="repository_exists") { t.Fatalf("existing PHP state was not refused safely: %+v",response) }
}
'''
write("internal/helper/installer_php84_acceptance_test.go", acceptance)

replace_once("internal/helper/protocol.go", "const ProtocolVersion = 11", "const ProtocolVersion = 12", "helper protocol")
server_path="internal/helper/server_linux.go"
server=read(server_path)
old_timeout='''\tif strings.HasPrefix(request.Action, "installer.nginx.") {\n\t\ttimeout = 10 * time.Minute\n\t}'''
new_timeout='''\tif strings.HasPrefix(request.Action, "installer.nginx.") || strings.HasPrefix(request.Action, "installer.php84.") {\n\t\ttimeout = 12 * time.Minute\n\t}'''
if old_timeout not in server: raise SystemExit("installer timeout marker not found")
server=server.replace(old_timeout,new_timeout,1)
marker='''\tdefault:\n\t\tresponse.Error = &Error{Code: "action_denied", Message: "action is not allow-listed"}\n\t\treturn response\n\t}\n}'''
cases='''\tcase "installer.php84.preflight":\n\t\tif request.Target != "php84" || len(request.Params) != 0 { response.Error=&Error{Code:"invalid_request",Message:"PHP 8.4 installer request must not contain arbitrary parameters"}; return response }\n\t\tdata,operationError:=installerPHP84Preflight(ctx); if operationError!=nil{response.Error=operationError;return response}; response.OK=true;response.Data=data;return response\n\tcase "installer.php84.install":\n\t\tif request.Target != "php84" || len(request.Params) != 0 { response.Error=&Error{Code:"invalid_request",Message:"PHP 8.4 installer request must not contain arbitrary parameters"}; return response }\n\t\tdata,operationError:=installerPHP84Install(ctx); if operationError!=nil{response.Error=operationError;return response}; response.OK=true;response.Data=data;return response\n\tcase "installer.php84.health":\n\t\tif request.Target != "php84" || len(request.Params) != 0 { response.Error=&Error{Code:"invalid_request",Message:"PHP 8.4 health request must not contain arbitrary parameters"}; return response }\n\t\tdata,operationError:=installerPHP84Health(ctx); if operationError!=nil{response.Error=operationError;return response}; response.OK=true;response.Data=data;return response\n\tcase "installer.php84.rollback":\n\t\tif request.Target != "php84" || len(request.Params) != 0 { response.Error=&Error{Code:"invalid_request",Message:"PHP 8.4 rollback request must not contain arbitrary parameters"}; return response }\n\t\tdata,operationError:=installerPHP84Rollback(ctx); if operationError!=nil{response.Error=operationError;return response}; response.OK=true;response.Data=data;return response\n'''
if marker not in server: raise SystemExit("helper dispatch marker not found")
server=server.replace(marker,cases+marker,1)
write(server_path,server)

policy_path="internal/helper/policy_test.go"
policy=read(policy_path)
policy += r'''

func TestInstallerPHP84ActionsRejectParametersAndWrongTarget(t *testing.T) {
    server:=&Server{}
    base:=Request{Version:ProtocolVersion,ID:"id",CorrelationID:"correlation",ActorID:"actor",Action:"installer.php84.preflight"}
    wrong:=base;wrong.Target="php83";response:=server.dispatch(context.Background(),wrong)
    if response.OK||response.Error==nil||response.Error.Code!="invalid_request"{t.Fatalf("wrong target accepted: %+v",response)}
    params:=base;params.Target="php84";params.Params=[]byte(`{"repository":"evil"}`);response=server.dispatch(context.Background(),params)
    if response.OK||response.Error==nil||response.Error.Code!="invalid_request"{t.Fatalf("arbitrary params accepted: %+v",response)}
}
'''
write(policy_path,policy)

replace_all("internal/web/static/index.html","Version 1.6.1","Version 1.6.2","UI version")
replace_all("internal/web/assets_test.go","1.6.1","1.6.2","asset version")
replace_all("internal/httpapi/app_test.go","Version 1.6.1","Version 1.6.2","HTTP UI version")
print("Applied HYZoraX Control Panel V1.6.2 PHP 8.4 FPM installer acceptance")
