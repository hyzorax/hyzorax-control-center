#!/usr/bin/env python3
from pathlib import Path
import sys
if len(sys.argv)!=2: raise SystemExit('usage: fix_scope.py <source-root>')
path=Path(sys.argv[1]).resolve()/'internal/helper/installer_node24_linux.go'
text=path.read_text(encoding='utf-8')
old='''for link,target:=range node24Links{if _,err:=os.Lstat(link);errors.Is(err,os.ErrNotExist){continue};if err!=nil{return nil,&Error{Code:"rollback_path_failed",Message:"Node.js command link could not be inspected"}};current,err:=os.Readlink(link);if err!=nil||current!=target{return nil,&Error{Code:"rollback_conflict",Message:"A Node.js command path is no longer HYZoraX-owned; rollback was refused: "+link}}}'''
new='''for link,target:=range node24Links{_,err:=os.Lstat(link);if errors.Is(err,os.ErrNotExist){continue};if err!=nil{return nil,&Error{Code:"rollback_path_failed",Message:"Node.js command link could not be inspected"}};current,err:=os.Readlink(link);if err!=nil||current!=target{return nil,&Error{Code:"rollback_conflict",Message:"A Node.js command path is no longer HYZoraX-owned; rollback was refused: "+link}}}'''
if old not in text: raise SystemExit('Node rollback scope marker not found')
path.write_text(text.replace(old,new,1),encoding='utf-8')
print('Fixed Node rollback error variable scope')
