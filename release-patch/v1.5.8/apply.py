#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()

def read(rel):
    return (root / rel).read_text(encoding="utf-8")

def write(rel, text):
    path = root / rel
    path.write_text(text, encoding="utf-8")

def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"{label}: marker not found")
    return text.replace(old, new, 1)

# Release/UI version markers.
html_path = "internal/web/static/index.html"
html = read(html_path).replace("Version 1.5.7", "Version 1.5.8")
write(html_path, html)

for rel in ("internal/web/assets_test.go", "internal/httpapi/app_test.go"):
    p = root / rel
    if p.exists():
        text = p.read_text(encoding="utf-8").replace("1.5.7", "1.5.8")
        p.write_text(text, encoding="utf-8")

# hz 1: read the current configured Owner username live from the control DB.
hz_path = "packaging/hz"
hz = read(hz_path)
hz = replace_once(
    hz,
    '  read_credentials_cache || true\n  local port="$(current_port)"\n',
    '''  read_credentials_cache || true
  local current_username=""
  if [[ -x /usr/local/bin/hyzorax-control ]]; then
    current_username="$(runuser -u hyzorax-control -- /usr/local/bin/hyzorax-control -config /etc/hyzorax-control/config.toml -owner-username 2>/dev/null | tail -n 1 || true)"
  fi
  [[ -n "${current_username}" ]] || current_username="${cached_username:-unavailable}"
  local port="$(current_port)"
''',
    "hz live username lookup",
)
hz = replace_once(
    hz,
    '  printf \'%sUsername:%s      %s%s%s\\n\' "${C_DIM}" "${C_RESET}" "${C_GREEN}" "${cached_username:-unavailable}" "${C_RESET}"\n',
    '  printf \'%sUsername:%s      %s%s%s\\n\' "${C_DIM}" "${C_RESET}" "${C_GREEN}" "${current_username}" "${C_RESET}"\n',
    "hz username display",
)
write(hz_path, hz)

# SSH: suppress only OpenSSH's Last login line using a validated drop-in.
bootstrap_path = "packaging/bootstrap.sh"
bootstrap = read(bootstrap_path)
bootstrap = replace_once(
    bootstrap,
    ': > /etc/motd\nrm -f -- /run/motd.dynamic /run/motd.dynamic.new 2>/dev/null || true\n',
    ''': > /etc/motd
rm -f -- /run/motd.dynamic /run/motd.dynamic.new 2>/dev/null || true

# HYZoraX owns only this small SSH presentation drop-in. Do not rewrite the
# provider/user SSH policy or authentication settings.
install -d -o root -g root -m 0755 /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/60-hyzorax-no-lastlog.conf <<'EOF'
# Managed by HYZoraX Control Center.
# Hide OpenSSH's "Last login" line; the HYZoraX dashboard is the login view.
PrintLastLog no
EOF
chmod 0644 /etc/ssh/sshd_config.d/60-hyzorax-no-lastlog.conf
if ! /usr/sbin/sshd -t; then
  echo "HYZoraX SSH presentation configuration validation failed." >&2
  rm -f /etc/ssh/sshd_config.d/60-hyzorax-no-lastlog.conf
  exit 1
fi
systemctl reload ssh.service 2>/dev/null || systemctl reload sshd.service 2>/dev/null || true
''',
    "sshd PrintLastLog drop-in",
)
write(bootstrap_path, bootstrap)

print("Applied HYZoraX Control Panel V1.5.8 hz username + SSH last-login cleanup")
