#!/usr/bin/env python3
from pathlib import Path
import sys
if len(sys.argv)!=2: raise SystemExit('usage: fix_status.py <source-root>')
p=Path(sys.argv[1]).resolve()/'internal/helper/installer_fail2ban_linux.go'
t=p.read_text(encoding='utf-8')
old='''err!=nil||!strings.Contains(string(out),"Jail: sshd")'''
new='''err!=nil||!strings.Contains(string(out),"Status for the jail: sshd")'''
if old not in t: raise SystemExit('Fail2ban jail status marker not found')
p.write_text(t.replace(old,new,1),encoding='utf-8')
print('Fixed Fail2ban sshd jail status health check')
