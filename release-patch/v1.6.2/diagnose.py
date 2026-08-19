#!/usr/bin/env python3
from pathlib import Path
import re
import subprocess
import sys
if len(sys.argv)!=2: raise SystemExit('usage: diagnose.py <source-root>')
source_root=Path(sys.argv[1]).resolve()
helper_path=source_root/'internal/helper/installer_php84_linux.go'
helper_text=helper_path.read_text(encoding='utf-8')
helper_text,count=re.subn(r'\s*\|\|\s*strings\.Contains\(string\(content\),\s*php84PPA\)', '', helper_text, count=1)
if count!=1: raise SystemExit('legacy PPA repository-presence clause not found')
helper_path.write_text(helper_text,encoding='utf-8')
secure_script=Path(__file__).with_name('secure_repo.py')
subprocess.run([sys.executable,str(secure_script),str(source_root)],check=True)
path=source_root/'internal/helper/installer_php84_acceptance_test.go'
text=path.read_text(encoding='utf-8')
old='''\tinstall := call("installer.php84.install")\n\tif !install.OK || install.Error != nil {\n\t\tt.Fatalf("install failed: %+v", install)\n\t}'''
if old not in text:
    old='''    install:=call("installer.php84.install"); if !install.OK||install.Error!=nil{t.Fatalf("install failed: %+v",install)}'''
new='''\tinstall := call("installer.php84.install")\n\tif !install.OK || install.Error != nil {\n\t\tif install.Error != nil { t.Fatalf("install failed: code=%s message=%s data=%+v", install.Error.Code, install.Error.Message, install.Data) }\n\t\tt.Fatalf("install failed without structured error: %+v", install)\n\t}'''
if old not in text: raise SystemExit('install failure assertion marker not found')
path.write_text(text.replace(old,new,1),encoding='utf-8')
print('Enabled verbose PHP 8.4 acceptance failure diagnostics')
