#!/usr/bin/env python3
import base64
import gzip
import hashlib
from pathlib import Path
import subprocess
import sys


root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
protocol = root / "internal/helper/protocol.go"
index = root / "internal/web/static/index.html"
javascript = root / "internal/web/static/app.js"
if not protocol.is_file() or not index.is_file() or not javascript.is_file():
    raise SystemExit("V1.7.7 source root was not found")
if "const ProtocolVersion = 21" not in protocol.read_text():
    raise SystemExit("V1.7.8 requires helper protocol V21 as its exact base")
if "Version 1.7.7" not in index.read_text():
    raise SystemExit("V1.7.8 requires the V1.7.7 web source as its exact base")
if 'if (options.body && !headers.has("Content-Type"))' not in javascript.read_text():
    raise SystemExit("V1.7.8 expected the V1.7.7 body-dependent JSON request contract")

payload = """\
H4sIAAAAAAACA+1W727bNhD/XD/FlWsLebKkJkMXL3WMpFmzbkCbIvaGAW1R0xJls6FIlaSdeqm/Dthj7Dn2NnuSHSn5b9JgRVvs
y4LAFu+Od+ff3f1OURQBTbi0TEsqkgs2TIyllqcJLcv4jWmEYQjDmwwODyH6Zqf1HYT4uXMfDg8bkCppLNyBAwgMEyy1SjfhoAuZ
SicFkzZ+O2F61qtVK5uHDaBmJlPIJzK1XEnQDE2NDUpqxy1QpRMa9Hs5b8LlItCY0YxpJ5bsAp5Up6A2jhfa9+/drYeNsLpUMDtW
Gd7pWc3laGley9Ga/PC4T5qxVT+XJdPH1LDAZVj7iw2zATlKU1Za0gKCcAieUuckeWOUJGgb8RyWjocqm8G9e3B74WBMTUCOFUIr
bdSflYw0m5veN5T/JkadvIvywqePl548PvqevIq5TMUkY2bLtulwDJ2PrRv4ffq8/+Pps9765frSF/gdH53DWgOkRudYSY0xj5U6
5ywg49lvStN3r53KuQfn3h22Uvs1Ou6dnUR9dc4kxvMWaD1vRB+cDC4z9i4e20LcMB1rRm5CHtxv7UHoP92ArP46FMaa5QfkqyFN
zyelId2OKans/v37X53EPz2qFNBhRbenlOwk+NBJaPd6P3SScbv08seftZcjJ77JRyeRdNptRMtzxqeQCmrMATE8Y0Oqo1ypheul
Cn/vxESZV1Sh3E00slrJUfcXhNpN8k68F++hQSXtmIIK0X1KJR0xRwlQCioZKCm4ZGjm1Z3Ee/KfjfALJtb+lMSW+FGXDZ6XkoLy
ZToXSp9jEikj3et6C22YNa8tkl08Utc11paF590HrTby7oPWbtu31S1scqY13EYm5MLNx61bNj6hlooA5U08Y2M7q9vGs56J3Whi
liaoBIHr2CbO3UbZiJu1aOWLsGLIsoxlUOMPDn+mkeCZAaksmLG6wHkUDFkTppu+GuFHZ9D2GYSfJYO2z2DeCPG/EbpNA33E9Kza
ND3E+Kfe6bOashxjnSj9CLlbMGOeTqxnLRNY+NpVAhOO+1Vub+iUmlTz0j6aoarlK7F/AEe+bvEZss4JF0hNG/tzAcdG2cKtsvl0
1wI4tzVaW1Gdba40vG5BrunINzAaaypHDF68qi75AINPWoODlvfx3++NKhGyeE8Y0JIn051kzdIkdy5TVZRKoqs5zhTiL8SgdVnl
tP+SPD/t9V+SeZM4X/MK/2s7dAX2Ct66MRcFywMyrJsFirpbwDWUW1VW09QCRw03Bl3D3bdkzZPzM6+LjfFvDD/46FeLwfYI1Zgh
5AILi+G4ECB4wa0BO2arrF0TWXQCVkGK2Bm44HYMFFxcUrEKbkzY5rWxtaWrBxbjQ8R2nYljtp29Xbcwqy9PbesIa1aoKc5+zrWx
kZ5IyIWfdke4BpB0y8kQ6w8+To6kuw93DUJdX3Qpu5w9G9bj4tDgGp1eHZdBhnGjEgkYSTyLrBqNBBtgDQouBZMjOz4gbeIF9N1C
sPOtl/T4SGIa7vEM9wmylsaZc0ee4Y5idlLi8tKFN/ZxppxdOE060dzOyMq0Enj9VWlOudgdUhllnAo1umpgsCOxWSJfsyta/9Kw
0q0lkiNnmeUFd4rcy/gq6Y1NMajG539MPx+mbY8pVJQ0dCS/YgS3K1sIqhMHC7SrN+ONgcHs3VDUaFdUpMQGE1XjUXuo5uMfS+mr
oh0OAAA=
"""
patch_bytes = gzip.decompress(base64.b64decode(payload))
expected = "88f3ce0d1219abf10d605f4697a1d6d90a8567ccd5dcf31cd099ce5ef54abaf1"
if hashlib.sha256(patch_bytes).hexdigest() != expected:
    raise SystemExit("V1.7.8 patch payload checksum mismatch")

subprocess.run(
    ["patch", "--batch", "--forward", "-p1", "-d", str(root)],
    input=patch_bytes,
    check=True,
)

javascript_source = javascript.read_text()
if "Version 1.7.8" not in index.read_text():
    raise SystemExit("V1.7.8 web version update was not applied")
if 'const method = String(options.method || "GET").toUpperCase();' not in javascript_source:
    raise SystemExit("V1.7.8 request method normalization was not applied")
if 'headers.set("Content-Type", "application/json")' not in javascript_source:
    raise SystemExit("V1.7.8 mutation JSON content type was not applied")
if 'if (options.body && !headers.has("Content-Type"))' in javascript_source:
    raise SystemExit("V1.7.8 retained the broken body-dependent JSON contract")
if "const ProtocolVersion = 21" not in protocol.read_text():
    raise SystemExit("V1.7.8 must preserve helper protocol V21")
print("Applied V1.7.8 bodyless mutation JSON hotfix")
