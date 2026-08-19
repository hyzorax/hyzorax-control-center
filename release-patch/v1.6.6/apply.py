#!/usr/bin/env python3
from pathlib import Path
import re,sys
if len(sys.argv)!=2: raise SystemExit('usage: apply.py <source-root>')
root=Path(sys.argv[1]).resolve()
def read(r):return (root/r).read_text(encoding='utf-8')
def write(r,t):p=root/r;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(t,encoding='utf-8')
def rep(r,a,b,l,all=False):
 t=read(r)
 if a not in t:raise SystemExit(f'{l}: marker not found in {r}')
 write(r,t.replace(a,b) if all else t.replace(a,b,1))

bp='internal/installer/builtin.go';b=read(bp)
if 'func ComposerManifest()' not in b:
 m=r'''

func ComposerManifest() Manifest {
 return Manifest{
  SchemaVersion:ManifestSchemaVersion, ID:"composer", Name:"Composer",
  SupportedOS:[]OSConstraint{{ID:"ubuntu",Version:"24.04"}},
  Versions:[]VersionSpec{{Version:"2.10.2",Default:true}},
  Dependencies:[]string{"php84"},
  Resources:ResourceRequirements{MinMemoryBytes:128*1024*1024,MinDiskBytes:128*1024*1024},
  Preflight:[]CheckSpec{{ID:"php84-runtime",Kind:"composer_php84",Params:map[string]string{"version":"8.4"}}},
  InstallSteps:[]OperationSpec{{ID:"install-composer-phar",Action:"file.template",Params:map[string]string{"managed":"composer-phar"}},{ID:"install-composer-command",Action:"file.template",Params:map[string]string{"managed":"composer-wrapper"}}},
  HealthChecks:[]CheckSpec{{ID:"composer-version",Kind:"composer_version",Params:map[string]string{"version":"2.10.2"}}},
  UninstallSteps:[]OperationSpec{{ID:"remove-composer",Action:"file.remove",Params:map[string]string{"managed":"composer"}}},
  RollbackPolicy:"required",RollbackSteps:[]OperationSpec{{ID:"rollback-composer",Action:"file.remove",Params:map[string]string{"managed":"composer"}}},
 }
}
'''
 marker='func BuiltinCatalog() (*Catalog, error) {'
 if marker not in b:raise SystemExit('BuiltinCatalog marker not found')
 b=b.replace(marker,m+'\n'+marker,1)
 x=re.search(r'return NewCatalog\(\[\]Manifest\{([^}]*)\}\)',b)
 if not x:raise SystemExit('catalog list not found')
 vals=x.group(1).strip(); vals+=("," if vals and not vals.endswith(',') else '')
 b=b[:x.start()]+'return NewCatalog([]Manifest{'+vals+' ComposerManifest()})'+b[x.end():];write(bp,b)

mp='internal/installer/manifest.go';t=read(mp);x=re.search(r'var allowedCheckKinds = map\[string\]struct\{\}\{\n(?P<body>.*?)\n\}',t,re.DOTALL)
if not x:raise SystemExit('allowedCheckKinds not found')
e=set(re.findall(r'"([a-z0-9_]+)"\s*:',x.group('body')));e.update({'composer_php84','composer_version'});body='\n'.join(f'\t"{n}": {{}},' for n in sorted(e));write(mp,t[:x.start()]+'var allowedCheckKinds = map[string]struct{}{\n'+body+'\n}'+t[x.end():])
write('internal/installer/composer_test.go',r'''package installer
import "testing"
func TestComposerManifestIsValidAndDependsOnPHP84(t *testing.T){m:=ComposerManifest();if err:=ValidateManifest(m);err!=nil{t.Fatal(err)};if len(m.Dependencies)!=1||m.Dependencies[0]!="php84"{t.Fatalf("deps=%#v",m.Dependencies)};if m.Versions[0].Version!="2.10.2"{t.Fatalf("versions=%#v",m.Versions)};c,err:=BuiltinCatalog();if err!=nil{t.Fatal(err)};p,err:=c.BuildPlan([]string{"composer"});if err!=nil{t.Fatal(err)};if len(p.Steps)!=2||p.Steps[0].ComponentID!="php84"||p.Steps[1].ComponentID!="composer"{t.Fatalf("plan=%#v",p)}}
''')
write('internal/helper/installer_composer_linux.go',r'''//go:build linux
package helper
import("bufio";"context";"crypto/sha256";"encoding/hex";"errors";"fmt";"io";"os";"os/exec";"path/filepath";"strings")
const composerVersion="2.10.2"
const composerURL="https://getcomposer.org/download/2.10.2/composer.phar"
const composerSHA256="5ee7125f8a30a34d246cefdc0bc85b8a783b28f2aec968994118512350d28027"
const composerRoot="/opt/hyzorax/composer-2.10.2"
const composerPhar=composerRoot+"/composer.phar"
const composerCommand="/usr/local/bin/composer"
const composerMarker="/var/lib/hyzorax-control/installer-managed/composer"
const composerWrapper="#!/bin/sh\nexec /usr/bin/php8.4 /opt/hyzorax/composer-2.10.2/composer.phar \"$@\"\n"
func installerComposerPreflight(ctx context.Context)(map[string]any,*Error){if os.Geteuid()!=0{return nil,&Error{Code:"installer_privilege_required",Message:"Composer installer must run in the privileged helper"}};id,v,err:=composerOSRelease();if err!=nil||id!="ubuntu"||v!="24.04"{return nil,&Error{Code:"unsupported_os",Message:"Composer installer supports Ubuntu 24.04 only"}};if composerStateExists(){return nil,&Error{Code:"component_exists",Message:"A HYZoraX Composer installation already exists; it will not be overwritten"}};if _,err:=os.Lstat(composerCommand);err==nil{return nil,&Error{Code:"path_conflict",Message:"/usr/local/bin/composer already exists; HYZoraX will not overwrite it"}}else if !errors.Is(err,os.ErrNotExist){return nil,&Error{Code:"preflight_failed",Message:"Composer command path could not be inspected"}};php:=exec.CommandContext(ctx,"/usr/bin/php8.4","-r","echo PHP_MAJOR_VERSION.'.'.PHP_MINOR_VERSION;");out,err:=php.CombinedOutput();if err!=nil||strings.TrimSpace(string(out))!="8.4"{return nil,&Error{Code:"dependency_missing",Message:"HYZoraX PHP 8.4 is required before Composer can be installed"}};return map[string]any{"component":"composer","ready":true,"version":composerVersion,"php":"8.4","install_root":composerRoot},nil}
func installerComposerInstall(ctx context.Context)(map[string]any,*Error){if _,e:=installerComposerPreflight(ctx);e!=nil{return nil,e};if err:=composerPrereq(ctx);err!=nil{return nil,&Error{Code:"prerequisite_install_failed",Message:"Composer download prerequisites could not be installed"}};if err:=os.MkdirAll(composerRoot,0755);err!=nil{return nil,&Error{Code:"directory_create_failed",Message:"Composer install root could not be created"}};cleanup:=func(){_ = os.Remove(composerCommand);_ = os.RemoveAll(composerRoot);_ = os.Remove(composerMarker)};f,err:=os.CreateTemp("","hyzorax-composer-*.phar");if err!=nil{cleanup();return nil,&Error{Code:"download_prepare_failed",Message:"Composer temporary file could not be created"}};tmp:=f.Name();_ = f.Close();defer os.Remove(tmp);c:=exec.CommandContext(ctx,"/usr/bin/curl","--fail","--silent","--show-error","--location","--retry","3","--connect-timeout","15","--max-time","180","--proto","=https","--tlsv1.2","--output",tmp,composerURL);if out,err:=c.CombinedOutput();err!=nil{cleanup();return nil,&Error{Code:"download_failed",Message:"Official Composer PHAR download failed: "+strings.TrimSpace(string(out))}};if err:=composerVerify(tmp);err!=nil{cleanup();return nil,&Error{Code:"checksum_failed",Message:err.Error()}};verify:=exec.CommandContext(ctx,"/usr/bin/php8.4",tmp,"--version","--no-ansi");out,err:=verify.CombinedOutput();if err!=nil||!strings.Contains(string(out),"Composer version "+composerVersion){cleanup();return nil,&Error{Code:"phar_validation_failed",Message:"Downloaded Composer PHAR did not execute as version 2.10.2"}};if err:=os.Rename(tmp,composerPhar);err!=nil{cleanup();return nil,&Error{Code:"install_move_failed",Message:"Composer PHAR could not be placed in the HYZoraX install root"}};if err:=os.Chmod(composerPhar,0644);err!=nil{cleanup();return nil,&Error{Code:"permission_failed",Message:"Composer PHAR permissions could not be set"}};if err:=os.WriteFile(composerCommand,[]byte(composerWrapper),0755);err!=nil{cleanup();return nil,&Error{Code:"command_create_failed",Message:"Global Composer command could not be created"}};if err:=os.MkdirAll(filepath.Dir(composerMarker),0750);err!=nil{cleanup();return nil,&Error{Code:"state_write_failed",Message:"Composer ownership marker directory could not be prepared"}};if err:=os.WriteFile(composerMarker,[]byte("hyzorax-composer-2.10.2\n"),0600);err!=nil{cleanup();return nil,&Error{Code:"state_write_failed",Message:"Composer ownership marker could not be written"}};h,e:=installerComposerHealth(ctx);if e!=nil{_,_=installerComposerRollback(ctx);return nil,e};h["installed"]=true;h["phar_sha256"]=composerSHA256;return h,nil}
func installerComposerHealth(ctx context.Context)(map[string]any,*Error){content,err:=os.ReadFile(composerCommand);if err!=nil||string(content)!=composerWrapper{return nil,&Error{Code:"command_check_failed",Message:"Global Composer command is missing or changed"}};if err:=composerVerify(composerPhar);err!=nil{return nil,&Error{Code:"integrity_check_failed",Message:"Installed Composer PHAR checksum does not match the pinned release"}};c:=exec.CommandContext(ctx,composerCommand,"--version","--no-ansi");out,err:=c.CombinedOutput();if err!=nil||!strings.Contains(string(out),"Composer version "+composerVersion){return nil,&Error{Code:"version_check_failed",Message:"Composer global command is not version 2.10.2"}};return map[string]any{"component":"composer","active":true,"version":composerVersion,"php":"8.4","global_command":composerCommand,"integrity":true},nil}
func installerComposerRollback(ctx context.Context)(map[string]any,*Error){_ = ctx;if _,err:=os.Stat(composerMarker);err!=nil{if errors.Is(err,os.ErrNotExist)&&!composerStateExists(){return map[string]any{"component":"composer","rolled_back":true,"already_absent":true},nil};if errors.Is(err,os.ErrNotExist){return nil,&Error{Code:"rollback_not_owned",Message:"Composer state exists without a HYZoraX ownership marker; rollback was refused"}};return nil,&Error{Code:"rollback_state_failed",Message:"Composer ownership marker could not be inspected"}};if content,err:=os.ReadFile(composerCommand);err!=nil||string(content)!=composerWrapper{return nil,&Error{Code:"rollback_conflict",Message:"/usr/local/bin/composer is no longer the HYZoraX-managed wrapper; rollback was refused"}};if err:=os.Remove(composerCommand);err!=nil{return nil,&Error{Code:"rollback_command_failed",Message:"Composer command could not be removed"}};if err:=os.RemoveAll(composerRoot);err!=nil{return nil,&Error{Code:"rollback_runtime_failed",Message:"Composer install root could not be removed"}};_ = os.Remove(composerMarker);return map[string]any{"component":"composer","rolled_back":true},nil}
func composerVerify(path string)error{f,err:=os.Open(path);if err!=nil{return err};defer f.Close();h:=sha256.New();if _,err:=io.Copy(h,f);err!=nil{return err};if hex.EncodeToString(h.Sum(nil))!=composerSHA256{return fmt.Errorf("official Composer PHAR SHA256 mismatch")};return nil}
func composerStateExists()bool{for _,p:=range []string{composerRoot,composerMarker}{if _,err:=os.Lstat(p);err==nil{return true}};return false}
func composerPrereq(ctx context.Context)error{c:=exec.CommandContext(ctx,"/usr/bin/apt-get","-o","DPkg::Lock::Timeout=120","-o","Acquire::Retries=3","-y","--no-install-recommends","install","ca-certificates","curl");c.Env=append(os.Environ(),"DEBIAN_FRONTEND=noninteractive","NEEDRESTART_MODE=l");_,err:=c.CombinedOutput();return err}
func composerOSRelease()(string,string,error){f,err:=os.Open("/etc/os-release");if err!=nil{return "","",err};defer f.Close();v:=map[string]string{};s:=bufio.NewScanner(f);for s.Scan(){line:=strings.TrimSpace(s.Text());if line==""||strings.HasPrefix(line,"#"){continue};p:=strings.SplitN(line,"=",2);if len(p)==2{v[p[0]]=strings.Trim(p[1],"\"")}};if err:=s.Err();err!=nil{return "","",err};return v["ID"],v["VERSION_ID"],nil}
''')
write('internal/helper/installer_composer_acceptance_test.go',r'''//go:build integration && linux
package helper
import("context";"os";"testing";"time")
func TestComposerInstallerAcceptance(t *testing.T){if os.Getenv("HYZORAX_INSTALLER_ACCEPTANCE")!="1"{t.Skip("opt-in")};if os.Geteuid()!=0{t.Fatal("root required")};ctx,cancel:=context.WithTimeout(context.Background(),12*time.Minute);defer cancel();s:=&Server{};call:=func(a,target string)Response{return s.dispatch(ctx,Request{Version:ProtocolVersion,ID:a,CorrelationID:"v166",ActorID:"github-actions",Action:a,Target:target})};defer func(){_=call("installer.composer.rollback","composer");_=call("installer.php84.rollback","php84")}();p:=call("installer.php84.preflight","php84");if p.OK{r:=call("installer.php84.install","php84");if !r.OK||r.Error!=nil{t.Fatalf("php install=%+v",r)}};cp:=call("installer.composer.preflight","composer");if !cp.OK||cp.Error!=nil{t.Fatalf("composer preflight=%+v",cp)};i:=call("installer.composer.install","composer");if !i.OK||i.Error!=nil{t.Fatalf("composer install=%+v",i)};h:=call("installer.composer.health","composer");if !h.OK||h.Error!=nil||h.Data["version"]!="2.10.2"{t.Fatalf("composer health=%+v",h)};r:=call("installer.composer.rollback","composer");if !r.OK||r.Error!=nil{t.Fatalf("composer rollback=%+v",r)}}
''')
rep('internal/helper/protocol.go','const ProtocolVersion = 15','const ProtocolVersion = 16','protocol')
sp='internal/helper/server_linux.go';s=read(sp)
if 'strings.HasPrefix(request.Action, "installer.node24.") {' in s:s=s.replace('strings.HasPrefix(request.Action, "installer.node24.") {','strings.HasPrefix(request.Action, "installer.node24.") || strings.HasPrefix(request.Action, "installer.composer.") {',1)
elif 'strings.HasPrefix(request.Action, "installer.composer.")' not in s:raise SystemExit('timeout marker not found')
marker='''\tdefault:\n\t\tresponse.Error = &Error{Code: "action_denied", Message: "action is not allow-listed"}\n\t\treturn response\n\t}\n}'''
if marker not in s:raise SystemExit('dispatch marker not found')
cases='''\tcase "installer.composer.preflight":\n\t\tif request.Target!="composer"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"Composer installer request must not contain arbitrary parameters"};return response}\n\t\tdata,e:=installerComposerPreflight(ctx);if e!=nil{response.Error=e;return response};response.OK=true;response.Data=data;return response\n\tcase "installer.composer.install":\n\t\tif request.Target!="composer"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"Composer installer request must not contain arbitrary parameters"};return response}\n\t\tdata,e:=installerComposerInstall(ctx);if e!=nil{response.Error=e;return response};response.OK=true;response.Data=data;return response\n\tcase "installer.composer.health":\n\t\tif request.Target!="composer"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"Composer health request must not contain arbitrary parameters"};return response}\n\t\tdata,e:=installerComposerHealth(ctx);if e!=nil{response.Error=e;return response};response.OK=true;response.Data=data;return response\n\tcase "installer.composer.rollback":\n\t\tif request.Target!="composer"||len(request.Params)!=0{response.Error=&Error{Code:"invalid_request",Message:"Composer rollback request must not contain arbitrary parameters"};return response}\n\t\tdata,e:=installerComposerRollback(ctx);if e!=nil{response.Error=e;return response};response.OK=true;response.Data=data;return response\n'''
s=s.replace(marker,cases+marker,1);write(sp,s)
pp='internal/helper/policy_test.go';write(pp,read(pp)+r'''
func TestInstallerComposerRejectsParametersAndWrongTarget(t *testing.T){s:=&Server{};b:=Request{Version:ProtocolVersion,ID:"id",CorrelationID:"c",ActorID:"a",Action:"installer.composer.preflight"};w:=b;w.Target="other";r:=s.dispatch(context.Background(),w);if r.OK||r.Error==nil||r.Error.Code!="invalid_request"{t.Fatalf("wrong target=%+v",r)};p:=b;p.Target="composer";p.Params=[]byte(`{"url":"https://evil.invalid"}`);r=s.dispatch(context.Background(),p);if r.OK||r.Error==nil||r.Error.Code!="invalid_request"{t.Fatalf("params=%+v",r)}}
''')
rep('internal/web/static/index.html','Version 1.6.5','Version 1.6.6','UI',True);rep('internal/web/assets_test.go','1.6.5','1.6.6','assets',True);rep('internal/httpapi/app_test.go','Version 1.6.5','Version 1.6.6','HTTP',True)
print('Applied HYZoraX Control Panel V1.6.6 Composer installer acceptance')
