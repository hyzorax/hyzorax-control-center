#!/usr/bin/env python3
from pathlib import Path
import sys
if len(sys.argv)!=2: raise SystemExit('usage: diagnose.py <source-root>')
p=Path(sys.argv[1]).resolve()/'internal/helper/installer_fail2ban_acceptance_test.go'
t=p.read_text(encoding='utf-8')
old='''i:=call("installer.fail2ban.install");if !i.OK||i.Error!=nil{t.Fatalf("install=%+v",i)}'''
new='''i:=call("installer.fail2ban.install");if !i.OK||i.Error!=nil{if i.Error!=nil{t.Fatalf("install failed: code=%s message=%s data=%+v",i.Error.Code,i.Error.Message,i.Data)};t.Fatalf("install failed: %+v",i)}'''
if old not in t: raise SystemExit('Fail2ban install assertion marker not found')
p.write_text(t.replace(old,new,1),encoding='utf-8')
print('Enabled verbose Fail2ban acceptance diagnostics')
