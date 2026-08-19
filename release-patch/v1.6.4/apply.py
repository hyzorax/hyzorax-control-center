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
if "func RedisManifest()" not in builtin:
    manifest = r'''

func RedisManifest() Manifest {
    return Manifest{
        SchemaVersion: ManifestSchemaVersion,
        ID:            "redis",
        Name:          "Redis",
        SupportedOS:   []OSConstraint{{ID: "ubuntu", Version: "24.04"}},
        Versions:      []VersionSpec{{Version: "ubuntu-24.04", Default: true, Repository: "ubuntu"}},
        Ports:         []PortSpec{{Protocol: "tcp", Port: 6379, MustBeFree: true}},
        Resources: ResourceRequirements{
            MinMemoryBytes: 128 * 1024 * 1024,
            MinDiskBytes:   512 * 1024 * 1024,
        },
        Preflight: []CheckSpec{
            {ID: "arch-x86-64", Kind: "arch", Params: map[string]string{"value": "x86_64"}},
            {ID: "redis-package-absent", Kind: "package_absent", Params: map[string]string{"name": "redis-server"}},
        },
        InstallSteps: []OperationSpec{
            {ID: "install-redis", Action: "apt.package.install", Params: map[string]string{"set": "redis-core"}},
            {ID: "secure-redis", Action: "config.write", Params: map[string]string{"managed": "redis-secure-defaults"}},
            {ID: "enable-redis", Action: "service.enable", Params: map[string]string{"name": "redis-server"}},
            {ID: "start-redis", Action: "service.start", Params: map[string]string{"name": "redis-server"}},
        },
        HealthChecks: []CheckSpec{
            {ID: "redis-service", Kind: "service_active", Params: map[string]string{"name": "redis-server"}},
            {ID: "redis-ping", Kind: "redis_ping", Params: map[string]string{"host": "127.0.0.1", "port": "6379"}},
            {ID: "redis-local-only", Kind: "redis_local_only", Params: map[string]string{"port": "6379"}},
            {ID: "redis-persistence", Kind: "redis_persistence", Params: map[string]string{"appendonly": "yes"}},
        },
        UninstallSteps: []OperationSpec{
            {ID: "stop-redis", Action: "service.stop", Params: map[string]string{"name": "redis-server"}},
            {ID: "remove-redis", Action: "apt.package.remove", Params: map[string]string{"set": "redis-core"}},
        },
        RollbackPolicy: "required",
        RollbackSteps: []OperationSpec{
            {ID: "rollback-stop-redis", Action: "service.stop", Params: map[string]string{"name": "redis-server"}},
            {ID: "rollback-remove-redis", Action: "apt.package.remove", Params: map[string]string{"set": "redis-core"}},
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
    replacement = "return NewCatalog([]Manifest{" + values + " RedisManifest()})"
    builtin = builtin[:match.start()] + replacement + builtin[match.end():]
    write(builtin_path, builtin)

manifest_path = "internal/installer/manifest.go"
manifest_text = read(manifest_path)
match = re.search(r'var allowedCheckKinds = map\[string\]struct\{\}\{\n(?P<body>.*?)\n\}', manifest_text, re.DOTALL)
if not match:
    raise SystemExit("allowedCheckKinds block not found")
entries = set(re.findall(r'"([a-z_]+)"\s*:', match.group("body")))
entries.update({"redis_ping", "redis_local_only", "redis_persistence"})
new_body = "\n".join(f'\t"{name}": {{}},' for name in sorted(entries))
new_block = "var allowedCheckKinds = map[string]struct{}{\n" + new_body + "\n}"
write(manifest_path, manifest_text[:match.start()] + new_block + manifest_text[match.end():])

write("internal/installer/redis_test.go", r'''package installer

import "testing"

func TestRedisManifestIsValidAndSafe(t *testing.T) {
    manifest := RedisManifest()
    if err := ValidateManifest(manifest); err != nil { t.Fatal(err) }
    if len(manifest.Ports) != 1 || manifest.Ports[0].Port != 6379 || !manifest.Ports[0].MustBeFree { t.Fatalf("ports=%#v", manifest.Ports) }
    if manifest.RollbackPolicy != "required" || len(manifest.RollbackSteps) == 0 { t.Fatal("Redis rollback must be required") }
    catalog, err := BuiltinCatalog(); if err != nil { t.Fatal(err) }
    plan, err := catalog.BuildPlan([]string{"redis"}); if err != nil { t.Fatal(err) }
    if len(plan.Steps) != 1 || plan.Steps[0].ComponentID != "redis" { t.Fatalf("plan=%#v", plan) }
}
''')

write("internal/helper/installer_redis_linux.go", r'''//go:build linux

package helper

import (
    "bufio"
    "context"
    "errors"
    "fmt"
    "os"
    "os/exec"
    "path/filepath"
    "strings"
)

const redisConfigPath = "/etc/redis/redis.conf"
const redisConfigDirectory = "/etc/redis"
const redisDataDirectory = "/var/lib/redis"
const redisManagedMarker = "/var/lib/hyzorax-control/installer-managed/redis"
const redisService = "redis-server"

var redisPackages = []string{"redis-server", "redis-tools"}

func installerRedisPreflight(ctx context.Context) (map[string]any, *Error) {
    if os.Geteuid() != 0 { return nil, &Error{Code:"installer_privilege_required",Message:"Redis installer must run in the privileged helper"} }
    osID, osVersion, err := redisOSRelease()
    if err != nil || osID != "ubuntu" || osVersion != "24.04" { return nil, &Error{Code:"unsupported_os",Message:"Redis installer supports Ubuntu 24.04 only"} }
    arch := exec.CommandContext(ctx, "/usr/bin/uname", "-m")
    archOutput, err := arch.CombinedOutput()
    if err != nil || strings.TrimSpace(string(archOutput)) != "x86_64" { return nil, &Error{Code:"unsupported_arch",Message:"Redis installer supports x86-64 only"} }
    if redisStateExists(ctx) { return nil, &Error{Code:"component_exists",Message:"Redis is already installed or configured; HYZoraX will not overwrite or adopt it"} }
    free, err := redisPortFree(ctx)
    if err != nil { return nil, &Error{Code:"preflight_failed",Message:"TCP port 6379 availability could not be determined"} }
    if !free { return nil, &Error{Code:"port_in_use",Message:"TCP port 6379 is already in use; HYZoraX will not reclaim it"} }
    return map[string]any{"component":"redis","ready":true,"port_6379_free":true,"listen_policy":"localhost-only","protected_mode":true,"persistence":"appendonly"}, nil
}

func installerRedisInstall(ctx context.Context) (map[string]any, *Error) {
    if _, operationError := installerRedisPreflight(ctx); operationError != nil { return nil, operationError }
    if err := redisAptUpdate(ctx); err != nil { return nil, &Error{Code:"apt_update_failed",Message:"Ubuntu package index update failed before Redis installation"} }
    if err := os.MkdirAll(filepath.Dir(redisManagedMarker),0750); err != nil { return nil,&Error{Code:"state_write_failed",Message:"Redis installer ownership marker could not be prepared"} }
    if err := os.WriteFile(redisManagedMarker,[]byte("hyzorax-redis\n"),0600); err != nil { return nil,&Error{Code:"state_write_failed",Message:"Redis installer ownership marker could not be written"} }
    if err := redisAptInstall(ctx); err != nil { _,_=installerRedisRollback(ctx); return nil,&Error{Code:"package_install_failed",Message:"Redis package installation failed"} }
    if err := redisConfigure(); err != nil { _,_=installerRedisRollback(ctx); return nil,&Error{Code:"secure_config_failed",Message:"Redis secure defaults could not be applied"} }
    if err := redisSystemctl(ctx,"enable"); err != nil { _,_=installerRedisRollback(ctx); return nil,&Error{Code:"service_enable_failed",Message:"Redis service could not be enabled"} }
    if err := redisSystemctl(ctx,"restart"); err != nil { _,_=installerRedisRollback(ctx); return nil,&Error{Code:"service_start_failed",Message:"Redis service could not be restarted after secure configuration"} }
    health, operationError := installerRedisHealth(ctx)
    if operationError != nil { _,_=installerRedisRollback(ctx); return nil,operationError }
    health["installed"] = true
    return health,nil
}

func installerRedisHealth(ctx context.Context) (map[string]any, *Error) {
    if err := redisSystemctl(ctx,"is-active"); err != nil { return nil,&Error{Code:"service_unhealthy",Message:"Redis service is not active"} }
    ping := exec.CommandContext(ctx,"/usr/bin/redis-cli","--raw","-h","127.0.0.1","-p","6379","PING")
    output,err:=ping.CombinedOutput(); if err!=nil || strings.TrimSpace(string(output))!="PONG" { return nil,&Error{Code:"redis_not_ready",Message:"Redis did not return PONG on localhost"} }
    protected,err:=redisConfigValue(ctx,"protected-mode"); if err!=nil || strings.ToLower(protected)!="yes" { return nil,&Error{Code:"protected_mode_check_failed",Message:"Redis protected-mode must be enabled"} }
    appendonly,err:=redisConfigValue(ctx,"appendonly"); if err!=nil || strings.ToLower(appendonly)!="yes" { return nil,&Error{Code:"persistence_check_failed",Message:"Redis append-only persistence must be enabled"} }
    bind,err:=redisConfigValue(ctx,"bind"); if err!=nil || !redisBindIsLocalOnly(bind) { return nil,&Error{Code:"public_listener_blocked",Message:"Redis bind configuration is not localhost-only"} }
    exposed,err:=redisWildcardListener(ctx); if err!=nil { return nil,&Error{Code:"listener_check_failed",Message:"Redis listener exposure could not be verified"} }
    if exposed { return nil,&Error{Code:"public_listener_blocked",Message:"Redis 6379 has a wildcard/public listener"} }
    return map[string]any{"component":"redis","active":true,"ready":true,"port":6379,"localhost_only":true,"protected_mode":true,"appendonly":true,"bind":bind},nil
}

func installerRedisRollback(ctx context.Context) (map[string]any, *Error) {
    _, markerErr := os.Stat(redisManagedMarker)
    stateExists := redisStateExists(ctx)
    if errors.Is(markerErr,os.ErrNotExist) {
        if !stateExists { return map[string]any{"component":"redis","rolled_back":true,"already_absent":true},nil }
        return nil,&Error{Code:"rollback_not_owned",Message:"Redis state exists without a HYZoraX ownership marker; destructive rollback was refused"}
    }
    if markerErr != nil { return nil,&Error{Code:"rollback_state_failed",Message:"Redis ownership marker could not be inspected"} }
    _=redisSystemctl(ctx,"stop")
    _=redisSystemctl(ctx,"disable")
    if err:=redisAptPurge(ctx); err!=nil { return nil,&Error{Code:"rollback_package_failed",Message:"Redis packages could not be removed during rollback"} }
    _=os.Remove(redisManagedMarker)
    return map[string]any{"component":"redis","rolled_back":true,"packages_removed":true},nil
}

func redisConfigure() error {
    content,err:=os.ReadFile(redisConfigPath); if err!=nil{return err}
    text:=string(content)
    text=redisSetDirective(text,"bind","127.0.0.1 ::1")
    text=redisSetDirective(text,"protected-mode","yes")
    text=redisSetDirective(text,"port","6379")
    text=redisSetDirective(text,"supervised","systemd")
    text=redisSetDirective(text,"daemonize","no")
    text=redisSetDirective(text,"appendonly","yes")
    text=redisSetDirective(text,"appendfsync","everysec")
    temporary:=redisConfigPath+".hyzorax.tmp"
    info,err:=os.Stat(redisConfigPath); if err!=nil{return err}
    if err:=os.WriteFile(temporary,[]byte(text),info.Mode().Perm());err!=nil{return err}
    if err:=os.Chown(temporary,int(info.Sys().(*syscall.Stat_t).Uid),int(info.Sys().(*syscall.Stat_t).Gid));err!=nil{_ = os.Remove(temporary);return err}
    return os.Rename(temporary,redisConfigPath)
}

func redisSetDirective(content,key,value string) string {
    lines:=strings.Split(content,"\n");found:=false
    for i,line:=range lines{trimmed:=strings.TrimSpace(line);if trimmed==""||strings.HasPrefix(trimmed,"#"){continue};fields:=strings.Fields(trimmed);if len(fields)>0&&fields[0]==key{lines[i]=key+" "+value;found=true;break}}
    if !found{lines=append(lines,key+" "+value)}
    return strings.Join(lines,"\n")
}

func redisConfigValue(ctx context.Context,key string)(string,error){command:=exec.CommandContext(ctx,"/usr/bin/redis-cli","--raw","-h","127.0.0.1","-p","6379","CONFIG","GET",key);output,err:=command.CombinedOutput();if err!=nil{return "",err};lines:=strings.Split(strings.TrimSpace(string(output)),"\n");if len(lines)<2{return "",errors.New("Redis CONFIG GET returned no value")};return strings.TrimSpace(lines[len(lines)-1]),nil}
func redisBindIsLocalOnly(value string)bool{fields:=strings.Fields(value);if len(fields)==0{return false};for _,field:=range fields{field=strings.TrimPrefix(field,"-");if field!="127.0.0.1"&&field!="::1"{return false}};return true}
func redisWildcardListener(ctx context.Context)(bool,error){command:=exec.CommandContext(ctx,"/usr/bin/ss","-H","-ltn","sport = :6379");output,err:=command.CombinedOutput();if err!=nil{return false,err};text:=string(output);return strings.Contains(text,"0.0.0.0:6379")||strings.Contains(text,"[::]:6379")||strings.Contains(text,"*:6379")||strings.Contains(text,":::6379"),nil}
func redisPortFree(ctx context.Context)(bool,error){command:=exec.CommandContext(ctx,"/usr/bin/ss","-H","-ltn","sport = :6379");output,err:=command.CombinedOutput();if err!=nil{return false,err};return strings.TrimSpace(string(output))=="",nil}
func redisStateExists(ctx context.Context)bool{if _,err:=os.Stat(redisConfigDirectory);err==nil{return true};for _,path:=range []string{"/usr/bin/redis-server","/usr/bin/redis-cli"}{if _,err:=os.Stat(path);err==nil{return true}};for _,pkg:=range redisPackages{if redisPackageInstalled(ctx,pkg){return true}};return false}
func redisPackageInstalled(ctx context.Context,pkg string)bool{command:=exec.CommandContext(ctx,"/usr/bin/dpkg-query","-W","-f=${Status}",pkg);output,err:=command.CombinedOutput();return err==nil&&strings.TrimSpace(string(output))=="install ok installed"}
func redisAptUpdate(ctx context.Context)error{command:=exec.CommandContext(ctx,"/usr/bin/apt-get","-o","DPkg::Lock::Timeout=120","-o","Acquire::Retries=3","update");_,err:=command.CombinedOutput();return err}
func redisAptInstall(ctx context.Context)error{args:=[]string{"-o","DPkg::Lock::Timeout=120","-y","--no-install-recommends","install"};args=append(args,redisPackages...);command:=exec.CommandContext(ctx,"/usr/bin/apt-get",args...);command.Env=append(os.Environ(),"DEBIAN_FRONTEND=noninteractive","NEEDRESTART_MODE=l");_,err:=command.CombinedOutput();return err}
func redisAptPurge(ctx context.Context)error{args:=[]string{"-o","DPkg::Lock::Timeout=120","-y","purge"};args=append(args,redisPackages...);command:=exec.CommandContext(ctx,"/usr/bin/apt-get",args...);command.Env=append(os.Environ(),"DEBIAN_FRONTEND=noninteractive","NEEDRESTART_MODE=l");_,err:=command.CombinedOutput();return err}
func redisSystemctl(ctx context.Context,action string)error{var args []string;switch action{case"enable":args=[]string{"enable",redisService};case"restart":args=[]string{"restart",redisService};case"is-active":args=[]string{"is-active","--quiet",redisService};case"stop":args=[]string{"stop",redisService};case"disable":args=[]string{"disable",redisService};default:return fmt.Errorf("unsupported Redis systemctl action %q",action)};command:=exec.CommandContext(ctx,"/usr/bin/systemctl",args...);_,err:=command.CombinedOutput();return err}
func redisOSRelease()(string,string,error){file,err:=os.Open("/etc/os-release");if err!=nil{return "","",err};defer file.Close();values:=map[string]string{};scanner:=bufio.NewScanner(file);for scanner.Scan(){line:=strings.TrimSpace(scanner.Text());if line==""||strings.HasPrefix(line,"#"){continue};parts:=strings.SplitN(line,"=",2);if len(parts)==2{values[parts[0]]=strings.Trim(parts[1],"\"")}};if err:=scanner.Err();err!=nil{return "","",err};return values["ID"],values["VERSION_ID"],nil}
'''.replace('"strings"\n)', '"strings"\n    "syscall"\n)'))

write("internal/helper/installer_redis_acceptance_test.go", r'''//go:build integration && linux

package helper

import (
    "context"
    "os"
    "testing"
    "time"
)

func TestRedisInstallerAcceptance(t *testing.T) {
    if os.Getenv("HYZORAX_INSTALLER_ACCEPTANCE")!="1"{t.Skip("real installer acceptance is opt-in")}
    if os.Geteuid()!=0{t.Fatal("real installer acceptance must run as root")}
    ctx,cancel:=context.WithTimeout(context.Background(),12*time.Minute);defer cancel();server:=&Server{}
    call:=func(action string)Response{t.Helper();return server.dispatch(ctx,Request{Version:ProtocolVersion,ID:action,CorrelationID:"v164-acceptance",ActorID:"github-actions",Action:action,Target:"redis"})}
    defer func(){_=call("installer.redis.rollback")}()
    preflight:=call("installer.redis.preflight");if !preflight.OK||preflight.Error!=nil{t.Fatalf("preflight failed: %+v",preflight)}
    install:=call("installer.redis.install");if !install.OK||install.Error!=nil{if install.Error!=nil{t.Fatalf("install failed: code=%s message=%s",install.Error.Code,install.Error.Message)};t.Fatalf("install failed: %+v",install)}
    health:=call("installer.redis.health");if !health.OK||health.Error!=nil||health.Data["active"]!=true||health.Data["localhost_only"]!=true||health.Data["protected_mode"]!=true||health.Data["appendonly"]!=true{t.Fatalf("health failed: %+v",health)}
    rollback:=call("installer.redis.rollback");if !rollback.OK||rollback.Error!=nil||rollback.Data["rolled_back"]!=true{t.Fatalf("rollback failed: %+v",rollback)}
}

func TestRedisInstallerRejectsExistingState(t *testing.T) {
    if os.Getenv("HYZORAX_INSTALLER_ACCEPTANCE")!="1"{t.Skip("real installer acceptance is opt-in")}
    if os.Geteuid()!=0{t.Fatal("real installer acceptance must run as root")}
    ctx,cancel:=context.WithTimeout(context.Background(),30*time.Second);defer cancel();if !redisStateExists(ctx){t.Skip("runner has no existing Redis state")}
    server:=&Server{};response:=server.dispatch(ctx,Request{Version:ProtocolVersion,ID:"existing-redis",CorrelationID:"v164-existing",ActorID:"github-actions",Action:"installer.redis.preflight",Target:"redis"})
    if response.OK||response.Error==nil{t.Fatalf("existing Redis state was not refused: %+v",response)}
}
''')

replace_once("internal/helper/protocol.go","const ProtocolVersion = 13","const ProtocolVersion = 14","helper protocol")
server_path="internal/helper/server_linux.go";server=read(server_path)
if 'strings.HasPrefix(request.Action, "installer.postgresql18.") {' in server:
    server=server.replace('strings.HasPrefix(request.Action, "installer.postgresql18.") {','strings.HasPrefix(request.Action, "installer.postgresql18.") || strings.HasPrefix(request.Action, "installer.redis.") {',1)
elif 'strings.HasPrefix(request.Action, "installer.redis.")' not in server:
    raise SystemExit("installer timeout marker not found")
marker='''\tdefault:\n\t\tresponse.Error = &Error{Code: "action_denied", Message: "action is not allow-listed"}\n\t\treturn response\n\t}\n}'''
if marker not in server: raise SystemExit("helper dispatch default marker not found")
cases='''\tcase "installer.redis.preflight":\n\t\tif request.Target!="redis"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"Redis installer request must not contain arbitrary parameters"};return response}\n\t\tdata,operationError:=installerRedisPreflight(ctx);if operationError!=nil{response.Error=operationError;return response};response.OK=true;response.Data=data;return response\n\tcase "installer.redis.install":\n\t\tif request.Target!="redis"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"Redis installer request must not contain arbitrary parameters"};return response}\n\t\tdata,operationError:=installerRedisInstall(ctx);if operationError!=nil{response.Error=operationError;return response};response.OK=true;response.Data=data;return response\n\tcase "installer.redis.health":\n\t\tif request.Target!="redis"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"Redis health request must not contain arbitrary parameters"};return response}\n\t\tdata,operationError:=installerRedisHealth(ctx);if operationError!=nil{response.Error=operationError;return response};response.OK=true;response.Data=data;return response\n\tcase "installer.redis.rollback":\n\t\tif request.Target!="redis"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"Redis rollback request must not contain arbitrary parameters"};return response}\n\t\tdata,operationError:=installerRedisRollback(ctx);if operationError!=nil{response.Error=operationError;return response};response.OK=true;response.Data=data;return response\n'''
server=server.replace(marker,cases+marker,1);write(server_path,server)

policy_path="internal/helper/policy_test.go";policy=read(policy_path)
policy += r'''

func TestInstallerRedisActionsRejectParametersAndWrongTarget(t *testing.T) {
    server:=&Server{};base:=Request{Version:ProtocolVersion,ID:"id",CorrelationID:"correlation",ActorID:"actor",Action:"installer.redis.preflight"}
    wrong:=base;wrong.Target="redis-other";response:=server.dispatch(context.Background(),wrong);if response.OK||response.Error==nil||response.Error.Code!="invalid_request"{t.Fatalf("wrong target accepted: %+v",response)}
    params:=base;params.Target="redis";params.Params=[]byte(`{"command":"FLUSHALL"}`);response=server.dispatch(context.Background(),params);if response.OK||response.Error==nil||response.Error.Code!="invalid_request"{t.Fatalf("arbitrary params accepted: %+v",response)}
}
''';write(policy_path,policy)

replace_all("internal/web/static/index.html","Version 1.6.3","Version 1.6.4","UI version")
replace_all("internal/web/assets_test.go","1.6.3","1.6.4","asset version")
replace_all("internal/httpapi/app_test.go","Version 1.6.3","Version 1.6.4","HTTP UI version")
print("Applied HYZoraX Control Panel V1.6.4 Redis installer acceptance")
