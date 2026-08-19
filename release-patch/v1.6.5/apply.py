#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()

def read(rel): return (root/rel).read_text(encoding="utf-8")
def write(rel,text):
    p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text,encoding="utf-8")
def replace_once(rel,old,new,label):
    text=read(rel)
    if old not in text: raise SystemExit(f"{label}: marker not found in {rel}")
    write(rel,text.replace(old,new,1))
def replace_all(rel,old,new,label):
    text=read(rel)
    if old not in text: raise SystemExit(f"{label}: marker not found in {rel}")
    write(rel,text.replace(old,new))

builtin_path="internal/installer/builtin.go"; builtin=read(builtin_path)
if "func Node24Manifest()" not in builtin:
    manifest=r'''

func Node24Manifest() Manifest {
    return Manifest{
        SchemaVersion: ManifestSchemaVersion,
        ID: "node24",
        Name: "Node.js 24 LTS",
        SupportedOS: []OSConstraint{{ID:"ubuntu",Version:"24.04"}},
        Versions: []VersionSpec{{Version:"24.19.0",Default:true}},
        Resources: ResourceRequirements{MinMemoryBytes:256*1024*1024,MinDiskBytes:512*1024*1024},
        Preflight: []CheckSpec{{ID:"arch-x86-64",Kind:"arch",Params:map[string]string{"value":"x86_64"}}},
        InstallSteps: []OperationSpec{
            {ID:"prepare-node-runtime",Action:"directory.ensure",Params:map[string]string{"managed":"node24-runtime"}},
            {ID:"install-node-runtime",Action:"file.template",Params:map[string]string{"managed":"node24-official-binary"}},
            {ID:"link-node-tools",Action:"file.template",Params:map[string]string{"managed":"node24-command-links"}},
        },
        HealthChecks: []CheckSpec{
            {ID:"node-version",Kind:"node_version",Params:map[string]string{"version":"24.19.0"}},
            {ID:"npm-version",Kind:"node_npm",Params:map[string]string{}},
        },
        UninstallSteps: []OperationSpec{{ID:"remove-node-runtime",Action:"file.remove",Params:map[string]string{"managed":"node24-runtime"}}},
        RollbackPolicy:"required",
        RollbackSteps: []OperationSpec{{ID:"rollback-node-runtime",Action:"file.remove",Params:map[string]string{"managed":"node24-runtime"}}},
    }
}
'''
    marker="func BuiltinCatalog() (*Catalog, error) {"
    if marker not in builtin: raise SystemExit("BuiltinCatalog marker not found")
    builtin=builtin.replace(marker,manifest+"\n"+marker,1)
    m=re.search(r'return NewCatalog\(\[\]Manifest\{([^}]*)\}\)',builtin)
    if not m: raise SystemExit("BuiltinCatalog manifest list not found")
    values=m.group(1).strip()
    if values and not values.endswith(","): values+="," 
    builtin=builtin[:m.start()]+"return NewCatalog([]Manifest{"+values+" Node24Manifest()})"+builtin[m.end():]
    write(builtin_path,builtin)

manifest_path="internal/installer/manifest.go"; text=read(manifest_path)
m=re.search(r'var allowedCheckKinds = map\[string\]struct\{\}\{\n(?P<body>.*?)\n\}',text,re.DOTALL)
if not m: raise SystemExit("allowedCheckKinds block not found")
entries=set(re.findall(r'"([a-z_]+)"\s*:',m.group("body"))); entries.update({"node_version","node_npm"})
body="\n".join(f'\t"{x}": {{}},' for x in sorted(entries))
write(manifest_path,text[:m.start()]+"var allowedCheckKinds = map[string]struct{}{\n"+body+"\n}"+text[m.end():])

write("internal/installer/node24_test.go",r'''package installer
import "testing"
func TestNode24ManifestIsValidAndPlannable(t *testing.T){
 m:=Node24Manifest();if err:=ValidateManifest(m);err!=nil{t.Fatal(err)}
 if len(m.Versions)!=1||m.Versions[0].Version!="24.19.0"||!m.Versions[0].Default{t.Fatalf("versions=%#v",m.Versions)}
 if len(m.Ports)!=0{t.Fatalf("Node runtime should expose no ports: %#v",m.Ports)}
 if m.RollbackPolicy!="required"||len(m.RollbackSteps)==0{t.Fatal("Node rollback must be required")}
 c,err:=BuiltinCatalog();if err!=nil{t.Fatal(err)};p,err:=c.BuildPlan([]string{"node24"});if err!=nil{t.Fatal(err)}
 if len(p.Steps)!=1||p.Steps[0].ComponentID!="node24"{t.Fatalf("plan=%#v",p)}
}
''')

write("internal/helper/installer_node24_linux.go",r'''//go:build linux
package helper

import(
 "bufio"
 "context"
 "crypto/sha256"
 "encoding/hex"
 "errors"
 "fmt"
 "io"
 "os"
 "os/exec"
 "path/filepath"
 "strings"
)

const node24Version="24.19.0"
const node24ArchiveURL="https://nodejs.org/dist/v24.19.0/node-v24.19.0-linux-x64.tar.xz"
const node24ArchiveSHA256="14b342e71204f811bde6153be8e04b62aef63c236fef92b55f9c83154b409647"
const node24Root="/opt/hyzorax/node-v24.19.0"
const node24Extracted="/opt/hyzorax/node-v24.19.0-linux-x64"
const node24Marker="/var/lib/hyzorax-control/installer-managed/node24"

var node24Links=map[string]string{
 "/usr/local/bin/node":node24Root+"/bin/node",
 "/usr/local/bin/npm":node24Root+"/bin/npm",
 "/usr/local/bin/npx":node24Root+"/bin/npx",
 "/usr/local/bin/corepack":node24Root+"/bin/corepack",
}

func installerNode24Preflight(ctx context.Context)(map[string]any,*Error){
 if os.Geteuid()!=0{return nil,&Error{Code:"installer_privilege_required",Message:"Node.js installer must run in the privileged helper"}}
 id,version,err:=node24OSRelease();if err!=nil||id!="ubuntu"||version!="24.04"{return nil,&Error{Code:"unsupported_os",Message:"Node.js 24 installer supports Ubuntu 24.04 only"}}
 command:=exec.CommandContext(ctx,"/usr/bin/uname","-m");out,err:=command.CombinedOutput();if err!=nil||strings.TrimSpace(string(out))!="x86_64"{return nil,&Error{Code:"unsupported_arch",Message:"Node.js 24 installer supports x86-64 only"}}
 if node24ManagedStateExists(){return nil,&Error{Code:"component_exists",Message:"A HYZoraX Node.js 24 runtime already exists; it will not be overwritten"}}
 for link:=range node24Links{if _,err:=os.Lstat(link);err==nil{return nil,&Error{Code:"path_conflict",Message:"A command already exists at "+link+"; HYZoraX will not overwrite it"}}else if !errors.Is(err,os.ErrNotExist){return nil,&Error{Code:"preflight_failed",Message:"Node.js command path could not be inspected"}}}
 return map[string]any{"component":"node24","ready":true,"version":node24Version,"install_root":node24Root,"system_node_untouched":true},nil
}

func installerNode24Install(ctx context.Context)(map[string]any,*Error){
 if _,op:=installerNode24Preflight(ctx);op!=nil{return nil,op}
 if err:=node24InstallPrerequisites(ctx);err!=nil{return nil,&Error{Code:"prerequisite_install_failed",Message:"Node.js download prerequisites could not be installed"}}
 if err:=os.MkdirAll("/opt/hyzorax",0755);err!=nil{return nil,&Error{Code:"directory_create_failed",Message:"Node.js install root could not be prepared"}}
 f,err:=os.CreateTemp("","hyzorax-node24-*.tar.xz");if err!=nil{return nil,&Error{Code:"download_prepare_failed",Message:"Node.js temporary archive could not be created"}};archive:=f.Name();_ = f.Close();defer os.Remove(archive)
 curl:=exec.CommandContext(ctx,"/usr/bin/curl","--fail","--silent","--show-error","--location","--retry","3","--connect-timeout","15","--max-time","300","--proto","=https","--tlsv1.2","--output",archive,node24ArchiveURL)
 if output,err:=curl.CombinedOutput();err!=nil{return nil,&Error{Code:"download_failed",Message:"Official Node.js archive download failed: "+strings.TrimSpace(string(output))}}
 if err:=node24VerifyArchive(archive);err!=nil{return nil,&Error{Code:"checksum_failed",Message:err.Error()}}
 _=os.RemoveAll(node24Extracted)
 tar:=exec.CommandContext(ctx,"/usr/bin/tar","-xJf",archive,"-C","/opt/hyzorax")
 if output,err:=tar.CombinedOutput();err!=nil{_ = os.RemoveAll(node24Extracted);return nil,&Error{Code:"extract_failed",Message:"Node.js archive extraction failed: "+strings.TrimSpace(string(output))}}
 if _,err:=os.Stat(node24Extracted+"/bin/node");err!=nil{_ = os.RemoveAll(node24Extracted);return nil,&Error{Code:"archive_invalid",Message:"Extracted Node.js runtime is missing bin/node"}}
 if err:=os.Rename(node24Extracted,node24Root);err!=nil{_ = os.RemoveAll(node24Extracted);return nil,&Error{Code:"install_move_failed",Message:"Node.js runtime could not be placed in HYZoraX install root"}}
 rollback:=func(){for link,target:=range node24Links{if current,err:=os.Readlink(link);err==nil&&current==target{_ = os.Remove(link)}};_ = os.RemoveAll(node24Root);_ = os.Remove(node24Marker)}
 for link,target:=range node24Links{if _,err:=os.Stat(target);err!=nil{rollback();return nil,&Error{Code:"runtime_incomplete",Message:"Node.js runtime tool is missing: "+filepath.Base(target)}};if err:=os.Symlink(target,link);err!=nil{rollback();return nil,&Error{Code:"link_create_failed",Message:"Node.js command link could not be created: "+link}}}
 if err:=os.MkdirAll(filepath.Dir(node24Marker),0750);err!=nil{rollback();return nil,&Error{Code:"state_write_failed",Message:"Node.js ownership marker directory could not be prepared"}}
 if err:=os.WriteFile(node24Marker,[]byte("hyzorax-node24-24.19.0\n"),0600);err!=nil{rollback();return nil,&Error{Code:"state_write_failed",Message:"Node.js ownership marker could not be written"}}
 health,op:=installerNode24Health(ctx);if op!=nil{_,_=installerNode24Rollback(ctx);return nil,op};health["installed"]=true;health["archive_sha256"]=node24ArchiveSHA256;return health,nil
}

func installerNode24Health(ctx context.Context)(map[string]any,*Error){
 versionCmd:=exec.CommandContext(ctx,"/usr/local/bin/node","--version");out,err:=versionCmd.CombinedOutput();if err!=nil||strings.TrimSpace(string(out))!="v"+node24Version{return nil,&Error{Code:"version_check_failed",Message:"HYZoraX Node.js version is not v24.19.0"}}
 npmCmd:=exec.CommandContext(ctx,"/usr/local/bin/npm","--version");npmOut,err:=npmCmd.CombinedOutput();if err!=nil||strings.TrimSpace(string(npmOut))==""{return nil,&Error{Code:"npm_check_failed",Message:"Bundled npm is not healthy"}}
 expr:=exec.CommandContext(ctx,"/usr/local/bin/node","-e","process.stdout.write(process.versions.node)");exprOut,err:=expr.CombinedOutput();if err!=nil||strings.TrimSpace(string(exprOut))!=node24Version{return nil,&Error{Code:"runtime_check_failed",Message:"Node.js runtime execution check failed"}}
 for link,target:=range node24Links{current,err:=os.Readlink(link);if err!=nil||current!=target{return nil,&Error{Code:"link_check_failed",Message:"HYZoraX Node.js command link is missing or changed: "+link}}}
 return map[string]any{"component":"node24","active":true,"version":node24Version,"npm_version":strings.TrimSpace(string(npmOut)),"install_root":node24Root,"daemon":false,"public_listener":false},nil
}

func installerNode24Rollback(ctx context.Context)(map[string]any,*Error){
 if _,err:=os.Stat(node24Marker);err!=nil{if errors.Is(err,os.ErrNotExist)&&!node24ManagedStateExists(){return map[string]any{"component":"node24","rolled_back":true,"already_absent":true},nil};if errors.Is(err,os.ErrNotExist){return nil,&Error{Code:"rollback_not_owned",Message:"Node.js state exists without a HYZoraX ownership marker; rollback was refused"}};return nil,&Error{Code:"rollback_state_failed",Message:"Node.js ownership marker could not be inspected"}}
 for link,target:=range node24Links{if _,err:=os.Lstat(link);errors.Is(err,os.ErrNotExist){continue};if err!=nil{return nil,&Error{Code:"rollback_path_failed",Message:"Node.js command link could not be inspected"}};current,err:=os.Readlink(link);if err!=nil||current!=target{return nil,&Error{Code:"rollback_conflict",Message:"A Node.js command path is no longer HYZoraX-owned; rollback was refused: "+link}}}
 for link,target:=range node24Links{if current,err:=os.Readlink(link);err==nil&&current==target{if err:=os.Remove(link);err!=nil{return nil,&Error{Code:"rollback_link_failed",Message:"Node.js command link could not be removed: "+link}}}}
 if err:=os.RemoveAll(node24Root);err!=nil{return nil,&Error{Code:"rollback_runtime_failed",Message:"Node.js runtime directory could not be removed"}}
 _=os.Remove(node24Marker)
 return map[string]any{"component":"node24","rolled_back":true,"runtime_removed":true},nil
}

func node24VerifyArchive(path string)error{f,err:=os.Open(path);if err!=nil{return err};defer f.Close();h:=sha256.New();if _,err:=io.Copy(h,f);err!=nil{return err};actual:=hex.EncodeToString(h.Sum(nil));if actual!=node24ArchiveSHA256{return fmt.Errorf("official Node.js archive SHA256 mismatch")};return nil}
func node24ManagedStateExists()bool{for _,path:=range []string{node24Root,node24Marker}{if _,err:=os.Lstat(path);err==nil{return true}};return false}
func node24InstallPrerequisites(ctx context.Context)error{args:=[]string{"-o","DPkg::Lock::Timeout=120","-o","Acquire::Retries=3","-y","--no-install-recommends","install","ca-certificates","curl","xz-utils"};c:=exec.CommandContext(ctx,"/usr/bin/apt-get",args...);c.Env=append(os.Environ(),"DEBIAN_FRONTEND=noninteractive","NEEDRESTART_MODE=l");_,err:=c.CombinedOutput();return err}
func node24OSRelease()(string,string,error){f,err:=os.Open("/etc/os-release");if err!=nil{return "","",err};defer f.Close();v:=map[string]string{};s:=bufio.NewScanner(f);for s.Scan(){line:=strings.TrimSpace(s.Text());if line==""||strings.HasPrefix(line,"#"){continue};p:=strings.SplitN(line,"=",2);if len(p)==2{v[p[0]]=strings.Trim(p[1],"\"")}};if err:=s.Err();err!=nil{return "","",err};return v["ID"],v["VERSION_ID"],nil}
''')

write("internal/helper/installer_node24_acceptance_test.go",r'''//go:build integration && linux
package helper
import("context";"os";"testing";"time")
func TestNode24InstallerAcceptance(t *testing.T){if os.Getenv("HYZORAX_INSTALLER_ACCEPTANCE")!="1"{t.Skip("real installer acceptance is opt-in")};if os.Geteuid()!=0{t.Fatal("real installer acceptance must run as root")};ctx,cancel:=context.WithTimeout(context.Background(),12*time.Minute);defer cancel();s:=&Server{};call:=func(a string)Response{return s.dispatch(ctx,Request{Version:ProtocolVersion,ID:a,CorrelationID:"v165",ActorID:"github-actions",Action:a,Target:"node24"})};defer func(){_=call("installer.node24.rollback")}();p:=call("installer.node24.preflight");if !p.OK||p.Error!=nil{t.Fatalf("preflight=%+v",p)};i:=call("installer.node24.install");if !i.OK||i.Error!=nil{t.Fatalf("install=%+v",i)};h:=call("installer.node24.health");if !h.OK||h.Error!=nil||h.Data["version"]!="24.19.0"{t.Fatalf("health=%+v",h)};r:=call("installer.node24.rollback");if !r.OK||r.Error!=nil||r.Data["rolled_back"]!=true{t.Fatalf("rollback=%+v",r)}}
func TestNode24InstallerRejectsExistingManagedPath(t *testing.T){if os.Getenv("HYZORAX_INSTALLER_ACCEPTANCE")!="1"{t.Skip("real installer acceptance is opt-in")};if os.Geteuid()!=0{t.Fatal("root required")};if !node24ManagedStateExists(){t.Skip("no HYZoraX Node state")};ctx,cancel:=context.WithTimeout(context.Background(),30*time.Second);defer cancel();s:=&Server{};r:=s.dispatch(ctx,Request{Version:ProtocolVersion,ID:"existing",CorrelationID:"v165-existing",ActorID:"github-actions",Action:"installer.node24.preflight",Target:"node24"});if r.OK||r.Error==nil{t.Fatalf("existing state accepted: %+v",r)}}
''')

replace_once("internal/helper/protocol.go","const ProtocolVersion = 14","const ProtocolVersion = 15","helper protocol")
server_path="internal/helper/server_linux.go";server=read(server_path)
if 'strings.HasPrefix(request.Action, "installer.redis.") {' in server: server=server.replace('strings.HasPrefix(request.Action, "installer.redis.") {','strings.HasPrefix(request.Action, "installer.redis.") || strings.HasPrefix(request.Action, "installer.node24.") {',1)
elif 'strings.HasPrefix(request.Action, "installer.node24.")' not in server: raise SystemExit("installer timeout marker not found")
marker='''\tdefault:\n\t\tresponse.Error = &Error{Code: "action_denied", Message: "action is not allow-listed"}\n\t\treturn response\n\t}\n}'''
if marker not in server: raise SystemExit("dispatch marker not found")
cases='''\tcase "installer.node24.preflight":\n\t\tif request.Target!="node24"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"Node.js installer request must not contain arbitrary parameters"};return response}\n\t\tdata,e:=installerNode24Preflight(ctx);if e!=nil{response.Error=e;return response};response.OK=true;response.Data=data;return response\n\tcase "installer.node24.install":\n\t\tif request.Target!="node24"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"Node.js installer request must not contain arbitrary parameters"};return response}\n\t\tdata,e:=installerNode24Install(ctx);if e!=nil{response.Error=e;return response};response.OK=true;response.Data=data;return response\n\tcase "installer.node24.health":\n\t\tif request.Target!="node24"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"Node.js health request must not contain arbitrary parameters"};return response}\n\t\tdata,e:=installerNode24Health(ctx);if e!=nil{response.Error=e;return response};response.OK=true;response.Data=data;return response\n\tcase "installer.node24.rollback":\n\t\tif request.Target!="node24"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"Node.js rollback request must not contain arbitrary parameters"};return response}\n\t\tdata,e:=installerNode24Rollback(ctx);if e!=nil{response.Error=e;return response};response.OK=true;response.Data=data;return response\n'''
server=server.replace(marker,cases+marker,1);write(server_path,server)
policy_path="internal/helper/policy_test.go";policy=read(policy_path)+r'''

func TestInstallerNode24RejectsParametersAndWrongTarget(t *testing.T){s:=&Server{};base:=Request{Version:ProtocolVersion,ID:"id",CorrelationID:"c",ActorID:"a",Action:"installer.node24.preflight"};wrong:=base;wrong.Target="node";r:=s.dispatch(context.Background(),wrong);if r.OK||r.Error==nil||r.Error.Code!="invalid_request"{t.Fatalf("wrong target accepted: %+v",r)};params:=base;params.Target="node24";params.Params=[]byte(`{"url":"https://evil.invalid/node"}`);r=s.dispatch(context.Background(),params);if r.OK||r.Error==nil||r.Error.Code!="invalid_request"{t.Fatalf("params accepted: %+v",r)}}
''';write(policy_path,policy)
replace_all("internal/web/static/index.html","Version 1.6.4","Version 1.6.5","UI version")
replace_all("internal/web/assets_test.go","1.6.4","1.6.5","asset version")
replace_all("internal/httpapi/app_test.go","Version 1.6.4","Version 1.6.5","HTTP UI version")
print("Applied HYZoraX Control Panel V1.6.5 Node.js 24 installer acceptance")
