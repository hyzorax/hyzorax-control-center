#!/usr/bin/env python3
"""HYZoraX V1.7.3 Firewall Controls release-patch launcher.

The release patch payload is gzip-compressed and base64-split so it can be
stored reliably through the repository publishing API. The decoded base
payload and the final effective payload are both SHA-256 verified.
"""
from pathlib import Path
import base64
import gzip
import hashlib

BASE_SHA256 = "708f4f50aa337fc636eda42a927c2d053a8145aef8c1bd2a2fdd33fbe13c99c4"
EFFECTIVE_SHA256 = "fe4ffc6aaef57cc0bb896244a674948e7cdb54fc3b33d51558e22d7bd530b7aa"
base = Path(__file__).resolve().parent
parts = sorted(base.glob("firewall_controls.py.gz.b64.part*"))
if not parts:
    raise SystemExit("V1.7.3 firewall payload parts are missing")
encoded = "".join(part.read_text(encoding="ascii").strip() for part in parts)
try:
    payload = gzip.decompress(base64.b64decode(encoded, validate=True))
except Exception as exc:
    raise SystemExit(f"V1.7.3 firewall payload decode failed: {exc}") from exc
actual = hashlib.sha256(payload).hexdigest()
if actual != BASE_SHA256:
    raise SystemExit(f"V1.7.3 firewall base payload checksum mismatch: {actual}")

text = payload.decode("utf-8")
old_stage = '''        args := []string{"insert", "1", "allow", fmt.Sprintf("%d/tcp", port), "comment", securityFirewallCommentPrefix + ruleID}
        if out, err := securityUFWCommand(ctx, args...).CombinedOutput(); err != nil {
'''
new_stage = '''        baseArgs := []string{"allow", fmt.Sprintf("%d/tcp", port), "comment", securityFirewallCommentPrefix + ruleID}
        hasRules, inspectErr := securityUFWHasAddedRules(ctx)
        if inspectErr != nil {
            rollbackStaged()
            return nil, &Error{Code: "firewall_protection_failed", Message: "HYZoraX could not inspect existing UFW rules before staging protected SSH/panel access"}
        }
        args := baseArgs
        if hasRules {
            args = append([]string{"insert", "1"}, baseArgs...)
        }
        if out, err := securityUFWCommand(ctx, args...).CombinedOutput(); err != nil {
'''
helper_marker = '''func securityUFWAddedContainsComment(ctx context.Context, comment string) bool {
'''
helper_code = '''func securityUFWHasAddedRules(ctx context.Context) (bool, error) {
    out, err := securityUFWCommand(ctx, "show", "added").CombinedOutput()
    if err != nil {
        return false, err
    }
    lower := strings.ToLower(string(out))
    return strings.Contains(lower, "ufw allow") || strings.Contains(lower, "ufw deny") || strings.Contains(lower, "ufw reject") || strings.Contains(lower, "ufw limit"), nil
}

'''
if text.count(old_stage) != 1:
    raise SystemExit("V1.7.3 firewall stage-protection transform marker mismatch")
if text.count(helper_marker) != 1:
    raise SystemExit("V1.7.3 firewall helper transform marker mismatch")
text = text.replace(old_stage, new_stage, 1)
text = text.replace(helper_marker, helper_code + helper_marker, 1)
payload = text.encode("utf-8")
effective = hashlib.sha256(payload).hexdigest()
if effective != EFFECTIVE_SHA256:
    raise SystemExit(f"V1.7.3 firewall effective payload checksum mismatch: {effective}")
exec(compile(payload, "firewall_controls_v1.7.3_payload.py", "exec"), {"__name__": "__main__"})
