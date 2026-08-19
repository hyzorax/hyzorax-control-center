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
if "func PostgreSQL18Manifest()" not in builtin:
    manifest = r'''

func PostgreSQL18Manifest() Manifest {
    return Manifest{
        SchemaVersion: ManifestSchemaVersion,
        ID:            "postgresql18",
        Name:          "PostgreSQL 18",
        SupportedOS:   []OSConstraint{{ID: "ubuntu", Version: "24.04"}},
        Versions:      []VersionSpec{{Version: "18", Default: true, Repository: "pgdg"}},
        Repositories: []RepositorySpec{{
            ID:             "pgdg",
            Kind:           "apt",
            Source:         "https://apt.postgresql.org/pub/repos/apt noble-pgdg main",
            KeyFingerprint: "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8",
        }},
        Ports: []PortSpec{{Protocol: "tcp", Port: 5432, MustBeFree: true}},
        Resources: ResourceRequirements{
            MinMemoryBytes: 512 * 1024 * 1024,
            MinDiskBytes:   1024 * 1024 * 1024,
        },
        Preflight: []CheckSpec{
            {ID: "arch-x86-64", Kind: "arch", Params: map[string]string{"value": "x86_64"}},
            {ID: "postgresql18-package-absent", Kind: "package_absent", Params: map[string]string{"name": "postgresql-18"}},
        },
        InstallSteps: []OperationSpec{
            {ID: "ensure-pgdg-repository", Action: "apt.repository.ensure", Params: map[string]string{"id": "pgdg"}},
            {ID: "install-postgresql18", Action: "apt.package.install", Params: map[string]string{"set": "postgresql18-core"}},
            {ID: "enable-postgresql", Action: "service.enable", Params: map[string]string{"name": "postgresql"}},
            {ID: "start-postgresql18", Action: "service.start", Params: map[string]string{"name": "postgresql@18-main"}},
        },
        HealthChecks: []CheckSpec{
            {ID: "postgresql18-service", Kind: "service_active", Params: map[string]string{"name": "postgresql@18-main"}},
            {ID: "postgresql18-ready", Kind: "postgres_ready", Params: map[string]string{"version": "18", "port": "5432"}},
            {ID: "postgresql18-local-only", Kind: "postgres_local_only", Params: map[string]string{"port": "5432"}},
        },
        UninstallSteps: []OperationSpec{
            {ID: "stop-postgresql18", Action: "service.stop", Params: map[string]string{"name": "postgresql@18-main"}},
            {ID: "drop-postgresql18-cluster", Action: "file.remove", Params: map[string]string{"managed": "postgresql18-main-cluster"}},
            {ID: "remove-postgresql18", Action: "apt.package.remove", Params: map[string]string{"set": "postgresql18-core"}},
        },
        RollbackPolicy: "required",
        RollbackSteps: []OperationSpec{
            {ID: "rollback-stop-postgresql18", Action: "service.stop", Params: map[string]string{"name": "postgresql@18-main"}},
            {ID: "rollback-drop-cluster", Action: "file.remove", Params: map[string]string{"managed": "postgresql18-main-cluster"}},
            {ID: "rollback-remove-packages", Action: "apt.package.remove", Params: map[string]string{"set": "postgresql18-core"}},
            {ID: "rollback-remove-pgdg", Action: "file.remove", Params: map[string]string{"managed": "pgdg-repository"}},
        },
    }
}
'''
    marker = "func BuiltinCatalog() (*Catalog, error) {"
    if marker not in builtin:
        raise SystemExit("BuiltinCatalog marker not found")
    builtin = builtin.replace(marker, manifest + "\n" + marker, 1)
    match = re.search(r'return NewCatalog\(\[\]Manifest\{([^}]*)\}\)', builtin)
    if not match:
        raise SystemExit("BuiltinCatalog manifest list not found")
    values = match.group(1).strip()
    if values and not values.endswith(","):
        values += ","
    replacement = "return NewCatalog([]Manifest{" + values + " PostgreSQL18Manifest()})"
    builtin = builtin[:match.start()] + replacement + builtin[match.end():]
    write(builtin_path, builtin)

# Extend typed check vocabulary without removing existing entries.
manifest_path = "internal/installer/manifest.go"
manifest_text = read(manifest_path)
match = re.search(r'var allowedCheckKinds = map\[string\]struct\{\}\{\n(?P<body>.*?)\n\}', manifest_text, re.DOTALL)
if not match:
    raise SystemExit("allowedCheckKinds block not found")
entries = set(re.findall(r'"([a-z_]+)"\s*:', match.group("body")))
entries.update({"postgres_ready", "postgres_local_only"})
new_body = "\n".join(f'\t"{name}": {{}},' for name in sorted(entries))
new_block = "var allowedCheckKinds = map[string]struct{}{\n" + new_body + "\n}"
write(manifest_path, manifest_text[:match.start()] + new_block + manifest_text[match.end():])

manifest_test = r'''package installer

import "testing"

func TestPostgreSQL18ManifestIsValidAndPinned(t *testing.T) {
    manifest := PostgreSQL18Manifest()
    if err := ValidateManifest(manifest); err != nil { t.Fatal(err) }
    if len(manifest.Repositories) != 1 { t.Fatalf("repositories=%#v", manifest.Repositories) }
    repository := manifest.Repositories[0]
    if repository.Source != "https://apt.postgresql.org/pub/repos/apt noble-pgdg main" { t.Fatalf("repository=%#v", repository) }
    if repository.KeyFingerprint != "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8" { t.Fatalf("fingerprint=%q", repository.KeyFingerprint) }
    if len(manifest.Ports) != 1 || manifest.Ports[0].Port != 5432 || !manifest.Ports[0].MustBeFree { t.Fatalf("ports=%#v", manifest.Ports) }
    if manifest.RollbackPolicy != "required" || len(manifest.RollbackSteps) == 0 { t.Fatal("PostgreSQL rollback must be required") }
    catalog, err := BuiltinCatalog(); if err != nil { t.Fatal(err) }
    plan, err := catalog.BuildPlan([]string{"postgresql18"}); if err != nil { t.Fatal(err) }
    if len(plan.Steps) != 1 || plan.Steps[0].ComponentID != "postgresql18" { t.Fatalf("plan=%#v", plan) }
}
'''
write("internal/installer/postgresql18_test.go", manifest_test)

helper = r'''//go:build linux

package helper

import (
    "bufio"
    "context"
    "errors"
    "fmt"
    "os"
    "os/exec"
    "path/filepath"
    "strconv"
    "strings"
)

const pg18RepositoryKeyURL = "https://www.postgresql.org/media/keys/ACCC4CF8.asc"
const pg18RepositoryFingerprint = "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8"
const pg18RepositoryURL = "apt.postgresql.org/pub/repos/apt"
const pg18KeyringPath = "/etc/apt/keyrings/hyzorax-pgdg.asc"
const pg18SourcePath = "/etc/apt/sources.list.d/hyzorax-pgdg.sources"
const pg18ManagedMarker = "/var/lib/hyzorax-control/installer-managed/postgresql18-main"
const pg18ConfigDirectory = "/etc/postgresql/18"
const pg18DataDirectory = "/var/lib/postgresql/18"
const pg18Service = "postgresql@18-main"

var pg18Packages = []string{"postgresql-18", "postgresql-client-18"}

func installerPostgreSQL18Preflight(ctx context.Context) (map[string]any, *Error) {
    if os.Geteuid() != 0 { return nil, &Error{Code:"installer_privilege_required",Message:"PostgreSQL 18 installer must run in the privileged helper"} }
    osID, osVersion, err := pg18OSRelease()
    if err != nil || osID != "ubuntu" || osVersion != "24.04" { return nil, &Error{Code:"unsupported_os",Message:"PostgreSQL 18 installer supports Ubuntu 24.04 only"} }
    archCommand := exec.CommandContext(ctx, "/usr/bin/uname", "-m")
    archOutput, err := archCommand.CombinedOutput()
    if err != nil || strings.TrimSpace(string(archOutput)) != "x86_64" { return nil, &Error{Code:"unsupported_arch",Message:"PostgreSQL 18 installer supports x86-64 only"} }
    if pg18VersionStateExists(ctx) { return nil, &Error{Code:"component_exists",Message:"PostgreSQL 18 is already installed or configured; HYZoraX will not overwrite it"} }
    clusters, err := pg18Clusters(ctx)
    if err != nil { return nil, &Error{Code:"preflight_failed",Message:"Existing PostgreSQL clusters could not be inspected"} }
    if len(clusters) > 0 { return nil, &Error{Code:"cluster_exists",Message:"An existing PostgreSQL cluster is configured; clean-install acceptance will not alter it"} }
    repositoryPresent, err := pg18RepositoryPresent()
    if err != nil { return nil, &Error{Code:"preflight_failed",Message:"PGDG repository state could not be inspected"} }
    if repositoryPresent { return nil, &Error{Code:"repository_exists",Message:"A PostgreSQL PGDG repository is already configured; HYZoraX will not adopt or overwrite it"} }
    portFree, err := pg18PortFree(ctx)
    if err != nil { return nil, &Error{Code:"preflight_failed",Message:"TCP port 5432 availability could not be determined"} }
    if !portFree { return nil, &Error{Code:"port_in_use",Message:"TCP port 5432 is already in use; HYZoraX will not reclaim it"} }
    return map[string]any{"component":"postgresql18","ready":true,"existing_cluster":false,"existing_repository":false,"port_5432_free":true,"listen_policy":"localhost-only"}, nil
}

func installerPostgreSQL18Install(ctx context.Context) (map[string]any, *Error) {
    if _, operationError := installerPostgreSQL18Preflight(ctx); operationError != nil { return nil, operationError }
    if err := pg18InstallPrerequisites(ctx); err != nil { return nil, &Error{Code:"prerequisite_install_failed",Message:"PostgreSQL repository prerequisites could not be installed"} }
    if err := pg18AddRepository(ctx); err != nil { return nil, &Error{Code:"repository_add_failed",Message:"PostgreSQL PGDG repository could not be configured"} }
    if err := pg18AptUpdate(ctx); err != nil { _ = pg18RemoveRepository(); return nil, &Error{Code:"apt_update_failed",Message:"Ubuntu package index update failed after adding PGDG"} }
    if err := os.MkdirAll(filepath.Dir(pg18ManagedMarker),0750); err != nil { _=pg18RemoveRepository(); return nil,&Error{Code:"state_write_failed",Message:"PostgreSQL installer ownership marker could not be prepared"} }
    if err := os.WriteFile(pg18ManagedMarker,[]byte("hyzorax-postgresql18-main\n"),0600); err != nil { _=pg18RemoveRepository(); return nil,&Error{Code:"state_write_failed",Message:"PostgreSQL installer ownership marker could not be written"} }
    if err := pg18AptInstall(ctx); err != nil { _,_=installerPostgreSQL18Rollback(ctx); return nil,&Error{Code:"package_install_failed",Message:"PostgreSQL 18 package installation failed"} }
    if _, err := os.Stat("/etc/postgresql/18/main/postgresql.conf"); err != nil { _,_=installerPostgreSQL18Rollback(ctx); return nil,&Error{Code:"cluster_create_failed",Message:"PostgreSQL 18 main cluster was not created"} }
    if err := pg18Systemctl(ctx,"enable"); err != nil { _,_=installerPostgreSQL18Rollback(ctx); return nil,&Error{Code:"service_enable_failed",Message:"PostgreSQL service could not be enabled"} }
    if err := pg18Systemctl(ctx,"restart"); err != nil { _,_=installerPostgreSQL18Rollback(ctx); return nil,&Error{Code:"service_start_failed",Message:"PostgreSQL 18 main cluster could not be started"} }
    health, operationError := installerPostgreSQL18Health(ctx)
    if operationError != nil { _,_=installerPostgreSQL18Rollback(ctx); return nil,operationError }
    health["installed"] = true
    health["repository_fingerprint"] = pg18RepositoryFingerprint
    return health,nil
}

func installerPostgreSQL18Health(ctx context.Context) (map[string]any, *Error) {
    if err := pg18Systemctl(ctx,"is-active"); err != nil { return nil,&Error{Code:"service_unhealthy",Message:"PostgreSQL 18 main cluster is not active"} }
    ready := exec.CommandContext(ctx,"/usr/lib/postgresql/18/bin/pg_isready","-h","127.0.0.1","-p","5432")
    if output,err:=ready.CombinedOutput(); err!=nil { return nil,&Error{Code:"postgres_not_ready",Message:"PostgreSQL 18 did not pass pg_isready: "+strings.TrimSpace(string(output))} }
    version,err:=pg18SQL(ctx,"SHOW server_version;"); if err!=nil || !strings.HasPrefix(version,"18.") { return nil,&Error{Code:"version_check_failed",Message:"PostgreSQL server version is not 18.x"} }
    port,err:=pg18SQL(ctx,"SHOW port;"); if err!=nil || port!="5432" { return nil,&Error{Code:"port_check_failed",Message:"PostgreSQL 18 main cluster is not using port 5432"} }
    listen,err:=pg18SQL(ctx,"SHOW listen_addresses;"); if err!=nil || !pg18ListenIsLocalOnly(listen) { return nil,&Error{Code:"public_listener_blocked",Message:"PostgreSQL listen_addresses is not localhost-only"} }
    encryption,err:=pg18SQL(ctx,"SHOW password_encryption;"); if err!=nil || strings.ToLower(strings.TrimSpace(encryption))!="scram-sha-256" { return nil,&Error{Code:"password_encryption_check_failed",Message:"PostgreSQL password_encryption must be scram-sha-256"} }
    exposed,err:=pg18WildcardListener(ctx); if err!=nil { return nil,&Error{Code:"listener_check_failed",Message:"PostgreSQL listener exposure could not be verified"} }
    if exposed { return nil,&Error{Code:"public_listener_blocked",Message:"PostgreSQL 5432 has a wildcard/public listener"} }
    return map[string]any{"component":"postgresql18","active":true,"ready":true,"version":version,"port":5432,"listen_addresses":listen,"localhost_only":true,"password_encryption":"scram-sha-256"},nil
}

func installerPostgreSQL18Rollback(ctx context.Context) (map[string]any, *Error) {
    _, markerErr := os.Stat(pg18ManagedMarker)
    stateExists := pg18VersionStateExists(ctx)
    if errors.Is(markerErr,os.ErrNotExist) {
        if !stateExists { _=pg18RemoveRepository(); return map[string]any{"component":"postgresql18","rolled_back":true,"already_absent":true},nil }
        return nil,&Error{Code:"rollback_not_owned",Message:"PostgreSQL 18 state exists without a HYZoraX ownership marker; rollback refused"}
    }
    if markerErr != nil { return nil,&Error{Code:"rollback_verify_failed",Message:"PostgreSQL ownership marker could not be inspected"} }
    _=pg18Systemctl(ctx,"stop")
    if _,err:=os.Stat("/etc/postgresql/18/main"); err==nil {
        command:=exec.CommandContext(ctx,"/usr/bin/pg_dropcluster","--stop","18","main")
        if output,err:=command.CombinedOutput(); err!=nil { return nil,&Error{Code:"rollback_failed",Message:"PostgreSQL managed cluster removal failed: "+strings.TrimSpace(string(output))} }
    }
    if err:=pg18AptPurge(ctx); err!=nil { return nil,&Error{Code:"rollback_failed",Message:"PostgreSQL 18 package rollback failed"} }
    if err:=pg18RemoveRepository(); err!=nil { return nil,&Error{Code:"rollback_failed",Message:"PostgreSQL PGDG repository rollback failed"} }
    _=pg18AptUpdate(ctx)
    _=os.Remove(pg18ManagedMarker)
    if pg18VersionStateExists(ctx) { return nil,&Error{Code:"rollback_verify_failed",Message:"PostgreSQL 18 remains installed or configured after rollback"} }
    return map[string]any{"component":"postgresql18","rolled_back":true,"cluster_removed":true,"repository_removed":true},nil
}

func pg18OSRelease()(string,string,error){ content,err:=os.ReadFile("/etc/os-release");if err!=nil{return "","",err};values:=map[string]string{};scanner:=bufio.NewScanner(strings.NewReader(string(content)));for scanner.Scan(){line:=strings.TrimSpace(scanner.Text());if line==""||strings.HasPrefix(line,"#"){continue};parts:=strings.SplitN(line,"=",2);if len(parts)==2{values[parts[0]]=strings.Trim(parts[1],"\"")}};return values["ID"],values["VERSION_ID"],scanner.Err() }

func pg18VersionStateExists(ctx context.Context) bool { for _,path:=range []string{"/usr/lib/postgresql/18",pg18ConfigDirectory,pg18DataDirectory}{if _,err:=os.Lstat(path);err==nil{return true}};command:=exec.CommandContext(ctx,"/usr/bin/dpkg-query","-W","-f=${Status}","postgresql-18");output,err:=command.CombinedOutput();return err==nil&&strings.TrimSpace(string(output))=="install ok installed" }

func pg18Clusters(ctx context.Context)([]string,error){ if _,err:=os.Stat("/usr/bin/pg_lsclusters");errors.Is(err,os.ErrNotExist){return nil,nil};command:=exec.CommandContext(ctx,"/usr/bin/pg_lsclusters","--no-header");output,err:=command.CombinedOutput();if err!=nil{return nil,err};var clusters []string;scanner:=bufio.NewScanner(strings.NewReader(string(output)));for scanner.Scan(){line:=strings.TrimSpace(scanner.Text());if line!=""{clusters=append(clusters,line)}};return clusters,scanner.Err() }

func pg18RepositoryPresent()(bool,error){ if _,err:=os.Lstat(pg18SourcePath);err==nil{return true,nil};if _,err:=os.Lstat(pg18KeyringPath);err==nil{return true,nil};paths:=[]string{"/etc/apt/sources.list"};matches,err:=filepath.Glob("/etc/apt/sources.list.d/*");if err!=nil{return false,err};paths=append(paths,matches...);for _,path:=range paths{content,err:=os.ReadFile(path);if err!=nil{continue};if strings.Contains(string(content),pg18RepositoryURL){return true,nil}};return false,nil }

func pg18PortFree(ctx context.Context)(bool,error){ command:=exec.CommandContext(ctx,"/usr/bin/ss","-H","-ltn","sport","=",":5432");output,err:=command.CombinedOutput();if err!=nil{return false,err};return strings.TrimSpace(string(output))=="",nil }

func pg18InstallPrerequisites(ctx context.Context) error { command:=exec.CommandContext(ctx,"/usr/bin/apt-get","-o","DPkg::Lock::Timeout=120","-o","Acquire::Retries=3","-y","--no-install-recommends","install","ca-certificates","curl","gnupg");command.Env=append(os.Environ(),"DEBIAN_FRONTEND=noninteractive","NEEDRESTART_MODE=l");_,err:=command.CombinedOutput();return err }

func pg18AddRepository(ctx context.Context) error { if err:=os.MkdirAll("/etc/apt/keyrings",0755);err!=nil{return err};temp,err:=os.CreateTemp("","hyzorax-pgdg-key-*.asc");if err!=nil{return err};tempPath:=temp.Name();if err:=temp.Close();err!=nil{_=os.Remove(tempPath);return err};defer os.Remove(tempPath);curl:=exec.CommandContext(ctx,"/usr/bin/curl","--fail","--silent","--show-error","--location","--retry","3","--connect-timeout","15","--max-time","120","--proto","=https","--tlsv1.2","--output",tempPath,pg18RepositoryKeyURL);if output,err:=curl.CombinedOutput();err!=nil{return fmt.Errorf("download PGDG key: %w: %s",err,strings.TrimSpace(string(output)))};verify:=exec.CommandContext(ctx,"/usr/bin/gpg","--batch","--show-keys","--with-colons",tempPath);output,err:=verify.CombinedOutput();if err!=nil{return err};found:=false;for _,line:=range strings.Split(string(output),"\n"){fields:=strings.Split(line,":");if len(fields)>9&&fields[0]=="fpr"&&strings.EqualFold(fields[9],pg18RepositoryFingerprint){found=true;break}};if !found{return errors.New("PGDG repository key fingerprint mismatch")};content,err:=os.ReadFile(tempPath);if err!=nil{return err};if err:=os.WriteFile(pg18KeyringPath,content,0644);err!=nil{return err};source:="Types: deb\nURIs: https://apt.postgresql.org/pub/repos/apt\nSuites: noble-pgdg\nArchitectures: amd64\nComponents: main\nSigned-By: "+pg18KeyringPath+"\n";tmpSource:=pg18SourcePath+".tmp";if err:=os.WriteFile(tmpSource,[]byte(source),0644);err!=nil{return err};if err:=os.Rename(tmpSource,pg18SourcePath);err!=nil{_=os.Remove(tmpSource);return err};return nil }

func pg18RemoveRepository() error { var first error;for _,path:=range []string{pg18SourcePath,pg18KeyringPath}{if err:=os.Remove(path);err!=nil&&!errors.Is(err,os.ErrNotExist)&&first==nil{first=err}};return first }
func pg18AptUpdate(ctx context.Context) error { command:=exec.CommandContext(ctx,"/usr/bin/apt-get","-o","DPkg::Lock::Timeout=120","-o","Acquire::Retries=3","update");command.Env=append(os.Environ(),"DEBIAN_FRONTEND=noninteractive");_,err:=command.CombinedOutput();return err }
func pg18AptInstall(ctx context.Context) error { args:=[]string{"-o","DPkg::Lock::Timeout=120","-o","Acquire::Retries=3","-y","--no-install-recommends","install"};args=append(args,pg18Packages...);command:=exec.CommandContext(ctx,"/usr/bin/apt-get",args...);command.Env=append(os.Environ(),"DEBIAN_FRONTEND=noninteractive","NEEDRESTART_MODE=l");_,err:=command.CombinedOutput();return err }
func pg18AptPurge(ctx context.Context) error { args:=[]string{"-o","DPkg::Lock::Timeout=120","-y","purge"};args=append(args,pg18Packages...);command:=exec.CommandContext(ctx,"/usr/bin/apt-get",args...);command.Env=append(os.Environ(),"DEBIAN_FRONTEND=noninteractive","NEEDRESTART_MODE=l");_,err:=command.CombinedOutput();return err }

func pg18Systemctl(ctx context.Context,action string) error { var args []string;switch action{case "enable":args=[]string{"enable","postgresql.service"};case "restart":args=[]string{"restart",pg18Service};case "is-active":args=[]string{"is-active","--quiet",pg18Service};case "stop":args=[]string{"stop",pg18Service};default:return errors.New("systemctl action is not allow-listed")};command:=exec.CommandContext(ctx,"/usr/bin/systemctl",args...);_,err:=command.CombinedOutput();return err }

func pg18SQL(ctx context.Context,query string)(string,error){ allowed:=map[string]bool{"SHOW server_version;":true,"SHOW port;":true,"SHOW listen_addresses;":true,"SHOW password_encryption;":true};if !allowed[query]{return "",errors.New("SQL health query is not allow-listed")};command:=exec.CommandContext(ctx,"/usr/sbin/runuser","-u","postgres","--","/usr/lib/postgresql/18/bin/psql","-X","-A","-t","-q","-c",query,"postgres");output,err:=command.CombinedOutput();return strings.TrimSpace(string(output)),err }

func pg18ListenIsLocalOnly(value string) bool { parts:=strings.Split(value,",");if len(parts)==0{return false};for _,part:=range parts{normalized:=strings.TrimSpace(strings.Trim(part,"'\""));switch normalized{case "localhost","127.0.0.1","::1":default:return false}};return true }
func pg18WildcardListener(ctx context.Context)(bool,error){ command:=exec.CommandContext(ctx,"/usr/bin/ss","-H","-ltn","sport","=",":5432");output,err:=command.CombinedOutput();if err!=nil{return false,err};for _,line:=range strings.Split(string(output),"\n"){fields:=strings.Fields(line);for _,field:=range fields{if strings.Contains(field,":5432")&&(strings.Contains(field,"0.0.0.0:5432")||strings.Contains(field,"*:5432")||strings.Contains(field,"[::]:5432")){return true,nil}}};return false,nil }

func pg18PortValue(value string)(int,error){return strconv.Atoi(strings.TrimSpace(value))}
'''
write("internal/helper/installer_postgresql18_linux.go", helper)

acceptance = r'''//go:build integration && linux

package helper

import (
    "context"
    "os"
    "testing"
    "time"
)

func TestPostgreSQL18InstallerAcceptance(t *testing.T) {
    if os.Getenv("HYZORAX_INSTALLER_ACCEPTANCE")!="1"{t.Skip("real installer acceptance is opt-in")}
    if os.Geteuid()!=0{t.Fatal("real installer acceptance must run as root")}
    ctx,cancel:=context.WithTimeout(context.Background(),15*time.Minute);defer cancel();server:=&Server{}
    call:=func(action string)Response{t.Helper();return server.dispatch(ctx,Request{Version:ProtocolVersion,ID:action,CorrelationID:"v163-acceptance",ActorID:"github-actions",Action:action,Target:"postgresql18"})}
    defer func(){_=call("installer.postgresql18.rollback")}()
    preflight:=call("installer.postgresql18.preflight");if !preflight.OK||preflight.Error!=nil{t.Fatalf("preflight failed: %+v",preflight)}
    install:=call("installer.postgresql18.install");if !install.OK||install.Error!=nil{if install.Error!=nil{t.Fatalf("install failed: code=%s message=%s",install.Error.Code,install.Error.Message)};t.Fatalf("install failed: %+v",install)}
    health:=call("installer.postgresql18.health");if !health.OK||health.Error!=nil||health.Data["active"]!=true||health.Data["localhost_only"]!=true{t.Fatalf("health failed: %+v",health)}
    rollback:=call("installer.postgresql18.rollback");if !rollback.OK||rollback.Error!=nil||rollback.Data["rolled_back"]!=true{t.Fatalf("rollback failed: %+v",rollback)}
}

func TestPostgreSQL18InstallerRejectsExistingState(t *testing.T) {
    if os.Getenv("HYZORAX_INSTALLER_ACCEPTANCE")!="1"{t.Skip("real installer acceptance is opt-in")}
    if os.Geteuid()!=0{t.Fatal("real installer acceptance must run as root")}
    ctx,cancel:=context.WithTimeout(context.Background(),30*time.Second);defer cancel();clusters,_:=pg18Clusters(ctx);repo,_:=pg18RepositoryPresent();if !pg18VersionStateExists(ctx)&&len(clusters)==0&&!repo{t.Skip("runner has no existing PostgreSQL state")}
    server:=&Server{};response:=server.dispatch(ctx,Request{Version:ProtocolVersion,ID:"existing-pg",CorrelationID:"v163-existing",ActorID:"github-actions",Action:"installer.postgresql18.preflight",Target:"postgresql18"})
    if response.OK||response.Error==nil{t.Fatalf("existing PostgreSQL state was not refused: %+v",response)}
}
'''
write("internal/helper/installer_postgresql18_acceptance_test.go", acceptance)

replace_once("internal/helper/protocol.go","const ProtocolVersion = 12","const ProtocolVersion = 13","helper protocol")
server_path="internal/helper/server_linux.go";server=read(server_path)
# Extend installer timeout robustly.
server=server.replace('strings.HasPrefix(request.Action, "installer.php84.") {','strings.HasPrefix(request.Action, "installer.php84.") || strings.HasPrefix(request.Action, "installer.postgresql18.") {',1)
marker='''\tdefault:\n\t\tresponse.Error = &Error{Code: "action_denied", Message: "action is not allow-listed"}\n\t\treturn response\n\t}\n}'''
if marker not in server: raise SystemExit("helper dispatch default marker not found")
cases='''\tcase "installer.postgresql18.preflight":\n\t\tif request.Target!="postgresql18"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"PostgreSQL 18 installer request must not contain arbitrary parameters"};return response}\n\t\tdata,operationError:=installerPostgreSQL18Preflight(ctx);if operationError!=nil{response.Error=operationError;return response};response.OK=true;response.Data=data;return response\n\tcase "installer.postgresql18.install":\n\t\tif request.Target!="postgresql18"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"PostgreSQL 18 installer request must not contain arbitrary parameters"};return response}\n\t\tdata,operationError:=installerPostgreSQL18Install(ctx);if operationError!=nil{response.Error=operationError;return response};response.OK=true;response.Data=data;return response\n\tcase "installer.postgresql18.health":\n\t\tif request.Target!="postgresql18"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"PostgreSQL 18 health request must not contain arbitrary parameters"};return response}\n\t\tdata,operationError:=installerPostgreSQL18Health(ctx);if operationError!=nil{response.Error=operationError;return response};response.OK=true;response.Data=data;return response\n\tcase "installer.postgresql18.rollback":\n\t\tif request.Target!="postgresql18"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"PostgreSQL 18 rollback request must not contain arbitrary parameters"};return response}\n\t\tdata,operationError:=installerPostgreSQL18Rollback(ctx);if operationError!=nil{response.Error=operationError;return response};response.OK=true;response.Data=data;return response\n'''
server=server.replace(marker,cases+marker,1);write(server_path,server)

policy_path="internal/helper/policy_test.go";policy=read(policy_path)
if '"context"' not in policy and 'context.Background()' in policy:
    raise SystemExit("existing policy tests use context without import")
policy += r'''

func TestInstallerPostgreSQL18ActionsRejectParametersAndWrongTarget(t *testing.T) {
    server:=&Server{};base:=Request{Version:ProtocolVersion,ID:"id",CorrelationID:"correlation",ActorID:"actor",Action:"installer.postgresql18.preflight"}
    wrong:=base;wrong.Target="postgresql17";response:=server.dispatch(context.Background(),wrong);if response.OK||response.Error==nil||response.Error.Code!="invalid_request"{t.Fatalf("wrong target accepted: %+v",response)}
    params:=base;params.Target="postgresql18";params.Params=[]byte(`{"sql":"DROP DATABASE"}`);response=server.dispatch(context.Background(),params);if response.OK||response.Error==nil||response.Error.Code!="invalid_request"{t.Fatalf("arbitrary params accepted: %+v",response)}
}
''';write(policy_path,policy)

replace_all("internal/web/static/index.html","Version 1.6.2","Version 1.6.3","UI version")
replace_all("internal/web/assets_test.go","1.6.2","1.6.3","asset version")
replace_all("internal/httpapi/app_test.go","Version 1.6.2","Version 1.6.3","HTTP UI version")
print("Applied HYZoraX Control Panel V1.6.3 PostgreSQL 18 installer acceptance")
