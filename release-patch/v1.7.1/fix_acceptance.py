#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: fix_acceptance.py <source-root>")
p = Path(sys.argv[1]).resolve() / "internal/helper/security_ssh_acceptance_test.go"
t = p.read_text(encoding="utf-8")
old = '''    hardened, operationError := securitySSHApply(ctx, []byte(`{\"root_login\":\"keys_only\",\"password_auth\":\"disabled\"}`))
    if operationError != nil {
        t.Fatalf("hardening failed: code=%s message=%s", operationError.Code, operationError.Message)
    }
    if changed, _ := hardened[\"changed\"].(bool); !changed {
        t.Fatalf("hardening unexpectedly reported no change: %#v", hardened)
    }
'''
new = '''    // Establish a permissive known baseline first so the hardening step is
    // deterministic across Ubuntu runner images with different SSH defaults.
    _, operationError := securitySSHApply(ctx, []byte(`{\"root_login\":\"password_and_keys\",\"password_auth\":\"enabled\"}`))
    if operationError != nil {
        t.Fatalf("baseline policy failed: code=%s message=%s", operationError.Code, operationError.Message)
    }
    hardened, operationError := securitySSHApply(ctx, []byte(`{\"root_login\":\"keys_only\",\"password_auth\":\"disabled\"}`))
    if operationError != nil {
        t.Fatalf("hardening failed: code=%s message=%s", operationError.Code, operationError.Message)
    }
    if changed, _ := hardened[\"changed\"].(bool); !changed {
        t.Fatalf("hardening unexpectedly reported no change after permissive baseline: %#v", hardened)
    }
'''
if old not in t:
    raise SystemExit("acceptance hardening marker not found")
t = t.replace(old, new, 1)
old2 = '''    if ssh["permit_root_login"] != "prohibit-password" || ssh["password_auth"] != "no" {
        t.Fatalf("hardening not effective: %#v", ssh)
    }
'''
new2 = '''    rootPolicy, _ := ssh["permit_root_login"].(string)
    if !securityRootPolicyEquivalent(rootPolicy, "prohibit-password") || ssh["password_auth"] != "no" {
        t.Fatalf("hardening not effective: %#v", ssh)
    }
'''
if old2 not in t:
    raise SystemExit("semantic hardening assertion marker not found")
t = t.replace(old2, new2, 1)
p.write_text(t, encoding="utf-8")
print("Stabilized V1.7.1 SSH acceptance with semantic root-policy assertion")
