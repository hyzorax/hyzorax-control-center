#!/usr/bin/env python3
from pathlib import Path
import sys
if len(sys.argv)!=2: raise SystemExit('usage: harden.py <source-root>')
path=Path(sys.argv[1]).resolve()/'internal/helper/installer_postgresql18_linux.go'
text=path.read_text(encoding='utf-8')
old='''if err:=os.WriteFile(pg18KeyringPath,content,0644);err!=nil{return err};source:="Types: deb\\nURIs: https://apt.postgresql.org/pub/repos/apt\\nSuites: noble-pgdg\\nArchitectures: amd64\\nComponents: main\\nSigned-By: "+pg18KeyringPath+"\\n";tmpSource:=pg18SourcePath+".tmp";if err:=os.WriteFile(tmpSource,[]byte(source),0644);err!=nil{return err};if err:=os.Rename(tmpSource,pg18SourcePath);err!=nil{_=os.Remove(tmpSource);return err};return nil'''
new='''if err:=os.WriteFile(pg18KeyringPath,content,0644);err!=nil{return err};if err:=os.Chmod(pg18KeyringPath,0644);err!=nil{return err};source:="Types: deb\\nURIs: https://apt.postgresql.org/pub/repos/apt\\nSuites: noble-pgdg\\nArchitectures: amd64\\nComponents: main\\nSigned-By: "+pg18KeyringPath+"\\n";tmpSource:=pg18SourcePath+".tmp";if err:=os.WriteFile(tmpSource,[]byte(source),0644);err!=nil{return err};if err:=os.Chmod(tmpSource,0644);err!=nil{_=os.Remove(tmpSource);return err};if err:=os.Rename(tmpSource,pg18SourcePath);err!=nil{_=os.Remove(tmpSource);return err};return nil'''
if old not in text: raise SystemExit('PGDG repository write marker not found')
path.write_text(text.replace(old,new,1),encoding='utf-8')
print('Hardened PGDG key/source file modes')
