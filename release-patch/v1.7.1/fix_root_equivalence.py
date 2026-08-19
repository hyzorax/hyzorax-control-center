#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: fix_root_equivalence.py <source-root>")
p = Path(sys.argv[1]).resolve() / "internal/helper/security_linux.go"
t = p.read_text(encoding="utf-8")
old = '''    if rootDirective != "" && effective["permitrootlogin"] != rootDirective {
        rollback()
        return nil, &Error{Code: "ssh_override_conflict", Message: "Another SSH configuration overrides the requested root-login policy; HYZoraX restored the previous configuration"}
    }
'''
new = '''    if rootDirective != "" && !securityRootPolicyEquivalent(effective["permitrootlogin"], rootDirective) {
        rollback()
        return nil, &Error{Code: "ssh_override_conflict", Message: "Another SSH configuration overrides the requested root-login policy; HYZoraX restored the previous configuration"}
    }
'''
if old not in t:
    raise SystemExit("root verification marker not found")
t = t.replace(old, new, 1)
insert = '''
func securityRootPolicyEquivalent(actual, desired string) bool {
    normalize := func(value string) string {
        value = strings.ToLower(strings.TrimSpace(value))
        switch value {
        case "prohibit-password", "without-password":
            return "keys_only"
        default:
            return value
        }
    }
    return normalize(actual) == normalize(desired)
}

'''
marker = 'func securitySSHManagedRead() ([]byte, bool, bool, map[string]string, error) {'
if marker not in t:
    raise SystemExit("managed read marker not found")
t = t.replace(marker, insert + marker, 1)
p.write_text(t, encoding="utf-8")
print("Normalized OpenSSH PermitRootLogin aliases for V1.7.1 verification")
