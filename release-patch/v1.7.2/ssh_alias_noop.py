#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: ssh_alias_noop.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()

security_path = root / "internal/helper/security_linux.go"
text = security_path.read_text(encoding="utf-8")
old = 'rootRequested := input.RootLogin != "keep" && desiredRoot != currentRoot'
new = 'rootRequested := input.RootLogin != "keep" && !securityRootPolicyEquivalent(currentRoot, desiredRoot)'
if old not in text:
    raise SystemExit("V1.7.1 root delta marker not found")
if 'func securityRootPolicyEquivalent(' not in text:
    raise SystemExit("V1.7.1 root policy equivalence helper not found")
security_path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Add a regression unit test for the OpenSSH alias pair that caused the
# unchanged Keys-only policy to be misclassified as a restrictive change.
test_path = root / "internal/helper/security_linux_test.go"
tests = test_path.read_text(encoding="utf-8")
regression = r'''

func TestSecurityRootPolicyEquivalentAliases(t *testing.T) {
    if !securityRootPolicyEquivalent("without-password", "prohibit-password") {
        t.Fatal("OpenSSH keys-only aliases must be equivalent")
    }
    if !securityRootPolicyEquivalent("prohibit-password", "without-password") {
        t.Fatal("OpenSSH keys-only aliases must be symmetric")
    }
    if securityRootPolicyEquivalent("yes", "prohibit-password") {
        t.Fatal("permissive and keys-only root policies must not be equivalent")
    }
}
'''
if 'func TestSecurityRootPolicyEquivalentAliases(' not in tests:
    tests += regression
    test_path.write_text(tests, encoding="utf-8")

# Extend the real Ubuntu acceptance test to reproduce the screenshot case:
# effective root policy is keys-only, PasswordAuthentication is enabled, no
# root key exists, and the user submits the same visible policy unchanged.
acceptance_path = root / "internal/helper/security_ssh_acceptance_test.go"
acceptance = acceptance_path.read_text(encoding="utf-8")
regression_acceptance = r'''

func TestSecuritySSHApplyAliasNoKeyNoopAcceptance(t *testing.T) {
    if os.Getenv("HYZORAX_SECURITY_SSH_ACCEPTANCE") != "1" {
        t.Skip("opt-in integration test")
    }
    if os.Geteuid() != 0 {
        t.Fatal("root required")
    }

    oldManaged, readErr := os.ReadFile(securitySSHManagedPath)
    managedExisted := readErr == nil
    if readErr != nil && !errors.Is(readErr, os.ErrNotExist) {
        t.Fatal(readErr)
    }
    defer func() {
        if managedExisted {
            _ = securitySSHManagedWrite(oldManaged)
        } else {
            _ = os.Remove(securitySSHManagedPath)
        }
        ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
        defer cancel()
        _ = securitySSHReload(ctx)
    }()

    keyPath := "/root/.ssh/authorized_keys"
    oldKeys, keyErr := os.ReadFile(keyPath)
    if keyErr != nil {
        t.Fatalf("acceptance requires the temporary root key prepared by CI: %v", keyErr)
    }
    defer func() {
        _ = os.MkdirAll("/root/.ssh", 0700)
        _ = os.WriteFile(keyPath, oldKeys, 0600)
    }()

    ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
    defer cancel()

    // Deterministic permissive baseline, then switch to the exact screenshot
    // state: Root login = Keys only, Password authentication = Enabled.
    if _, operationError := securitySSHApply(ctx, []byte(`{"root_login":"password_and_keys","password_auth":"enabled"}`)); operationError != nil {
        t.Fatalf("baseline failed: code=%s message=%s", operationError.Code, operationError.Message)
    }
    if _, operationError := securitySSHApply(ctx, []byte(`{"root_login":"keys_only","password_auth":"enabled"}`)); operationError != nil {
        t.Fatalf("keys-only setup failed: code=%s message=%s", operationError.Code, operationError.Message)
    }

    ssh := securitySSH(ctx)
    rootPolicy, _ := ssh["permit_root_login"].(string)
    if !securityRootPolicyEquivalent(rootPolicy, "prohibit-password") || ssh["password_auth"] != "yes" {
        t.Fatalf("screenshot state was not established: %#v", ssh)
    }

    if err := os.Remove(keyPath); err != nil {
        t.Fatalf("could not remove temporary root key: %v", err)
    }
    ssh = securitySSH(ctx)
    if detected, _ := ssh["root_key_detected"].(bool); detected {
        t.Fatalf("root key should be absent for no-op regression: %#v", ssh)
    }

    result, operationError := securitySSHApply(ctx, []byte(`{"root_login":"keys_only","password_auth":"enabled"}`))
    if operationError != nil {
        t.Fatalf("unchanged alias-equivalent policy must not trigger lockout guard: code=%s message=%s", operationError.Code, operationError.Message)
    }
    if changed, _ := result["changed"].(bool); changed {
        t.Fatalf("unchanged alias-equivalent policy must be a no-op: %#v", result)
    }
}
'''
if 'func TestSecuritySSHApplyAliasNoKeyNoopAcceptance(' not in acceptance:
    acceptance += regression_acceptance
    acceptance_path.write_text(acceptance, encoding="utf-8")

# Panel-visible version only; helper protocol remains V19 because the wire
# schema did not change.
index_path = root / "internal/web/static/index.html"
html = index_path.read_text(encoding="utf-8")
if "Version 1.7.1" not in html:
    raise SystemExit("V1.7.1 panel version marker not found")
index_path.write_text(html.replace("Version 1.7.1", "Version 1.7.2", 1), encoding="utf-8")

# Existing release-version assertions intentionally pin the embedded UI text.
# Keep them in sync with this hotfix release without weakening the tests.
for rel in ("internal/httpapi/app_test.go", "internal/web/assets_test.go"):
    path = root / rel
    body = path.read_text(encoding="utf-8")
    if "Version 1.7.1" not in body:
        raise SystemExit(f"V1.7.1 version assertion marker not found in {rel}")
    path.write_text(body.replace("Version 1.7.1", "Version 1.7.2"), encoding="utf-8")

print("Applied HYZoraX V1.7.2 SSH alias/no-op lockout hotfix")
