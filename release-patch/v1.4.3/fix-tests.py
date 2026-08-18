#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()

app_test = root / 'internal/httpapi/app_test.go'
text = app_test.read_text()
old = 'Sign in as hyzorax'
if old not in text:
    raise SystemExit('expected login copy assertion not found in app_test.go')
app_test.write_text(text.replace(old, 'Sign in', 1))

assets_test = root / 'internal/web/assets_test.go'
text = assets_test.read_text()
old = '1.4.2'
if old not in text:
    raise SystemExit('expected V1.4.2 assertion not found in assets_test.go')
assets_test.write_text(text.replace(old, '1.4.3', 1))

print('V1.4.3 tests updated')
