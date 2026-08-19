#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: harden.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()
path = root / "internal/helper/installer_nginx_linux.go"
text = path.read_text(encoding="utf-8")
text = text.replace('    "bytes"\n', '')
text = text.replace('configOutput, err := runCommandCombined(ctx, nil, "/usr/sbin/nginx", "-t")', 'configCommand := exec.CommandContext(ctx, "/usr/sbin/nginx", "-t")\n    configOutput, err := configCommand.CombinedOutput()')
text = text.replace('versionOutput, _ := runCommandCombined(ctx, nil, "/usr/sbin/nginx", "-v")', 'versionCommand := exec.CommandContext(ctx, "/usr/sbin/nginx", "-v")\n    versionOutput, _ := versionCommand.CombinedOutput()')
text = text.replace('_, err := runCommandCombined(ctx, environment, "/usr/bin/apt-get", args...)\n    return err', 'command := exec.CommandContext(ctx, "/usr/bin/apt-get", args...)\n    command.Env = environment\n    _, err := command.CombinedOutput()\n    return err')
text = text.replace('_, err := runCommandCombined(ctx, nil, "/usr/bin/systemctl", args...)\n    return err', 'command := exec.CommandContext(ctx, "/usr/bin/systemctl", args...)\n    _, err := command.CombinedOutput()\n    return err')
text = text.replace('output, err := runCommandCombined(ctx, nil, "/usr/bin/dpkg-query", "-W", "-f=${Status}", name)', 'command := exec.CommandContext(ctx, "/usr/bin/dpkg-query", "-W", "-f=${Status}", name)\n    output, err := command.CombinedOutput()')
text = text.replace('output, err := runCommandCombined(ctx, nil, "/usr/bin/ss", "-H", "-ltn", "sport", "=", ":80")', 'command := exec.CommandContext(ctx, "/usr/bin/ss", "-H", "-ltn", "sport", "=", ":80")\n    output, err := command.CombinedOutput()')
text, count = re.subn(r'\nfunc runCommandCombined\(ctx context\.Context, environment \[\]string, executable string, args \.\.\.string\) \(\[\]byte, error\) \{.*?\n\}\n?$', '\n', text, flags=re.DOTALL)
if count != 1:
    raise SystemExit(f"expected to remove one generic command wrapper, removed {count}")
if 'runCommandCombined' in text or 'exec.CommandContext(ctx, executable' in text:
    raise SystemExit("generic executable wrapper remains")
path.write_text(text, encoding="utf-8")

policy_path = root / "internal/helper/policy_test.go"
policy = policy_path.read_text(encoding="utf-8")
if "context.Background()" in policy and '"context"' not in policy:
    if 'import "testing"' in policy:
        policy = policy.replace('import "testing"', 'import (\n    "context"\n    "testing"\n)', 1)
    elif 'import (\n' in policy:
        policy = policy.replace('import (\n', 'import (\n    "context"\n', 1)
    else:
        raise SystemExit("could not add context import to helper policy test")
    policy_path.write_text(policy, encoding="utf-8")
print("Hardened Nginx privileged installer to fixed executable paths")
