#!/usr/bin/env python3
from pathlib import Path
import sys
root=Path(sys.argv[1] if len(sys.argv)>1 else '.')

def repl(rel, old, new):
 p=root/rel; s=p.read_text()
 if s.count(old)!=1: raise SystemExit(f'{rel}: marker count {s.count(old)}')
 p.write_text(s.replace(old,new,1))

# UFW uses the kernel netlink interface. The privileged helper is intentionally
# sandboxed, but AF_NETLINK must remain available for guarded firewall writes.
for rel in ['build/hyzorax-control-helper.service','packaging/hyzorax-control-helper.service']:
 repl(rel,'RestrictAddressFamilies=AF_UNIX','RestrictAddressFamilies=AF_UNIX AF_NETLINK')

old='''echo "Applying independent IP-only trusted TLS..."
# Installation is not declared complete until the browser-trusted IP
# certificate has been issued, deployed, and verified. If Ubuntu still owns
# the apt/dpkg lock on a fresh image, bootstrap-wait waits here instead of
# exposing the temporary self-signed certificate as a completed install.
/usr/local/libexec/hyzorax-control-tls bootstrap-wait
systemctl_retry start hyzorax-control-tls-renew.timer

# Re-confirm the panel with normal CA verification. --resolve keeps the
# health check local while validating the public IP SAN and Let's Encrypt
# trust chain exactly as a browser will.
panel_ip=""
if command -v ip >/dev/null 2>&1; then
  panel_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i == "src") {print $(i+1); exit}}' || true)"
fi
[[ -n "${panel_ip}" ]] || { echo "Could not detect panel IPv4 address for trusted TLS verification." >&2; exit 1; }
trusted_tls_ready=false
for _ in {1..30}; do
  if curl -fsS --noproxy '*' --max-time 3 --resolve "${panel_ip}:${panel_port}:127.0.0.1" \\
      "https://${panel_ip}:${panel_port}/${entrance_code}/api/v1/healthz" >/dev/null 2>&1; then
    trusted_tls_ready=true
    break
  fi
  sleep 1
done
if [[ "${trusted_tls_ready}" != true ]]; then
  echo "Trusted IP TLS did not pass browser-equivalent verification." >&2
  /usr/local/libexec/hyzorax-control-tls status >&2 || true
  exit 1
fi
'''
new='''echo "Applying independent IP-only trusted TLS..."
panel_ip=""
if command -v ip >/dev/null 2>&1; then
  panel_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i == "src") {print $(i+1); exit}}' || true)"
fi
panel_ip_is_global=false
if [[ -n "${panel_ip}" ]] && python3 - "${panel_ip}" <<'PYIP'
import ipaddress, sys
try:
    ip = ipaddress.ip_address(sys.argv[1])
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if ip.version == 4 and ip.is_global else 1)
PYIP
then
  panel_ip_is_global=true
fi

if [[ "${panel_ip_is_global}" == true ]]; then
  # Real public VPS behavior stays strict.
  /usr/local/libexec/hyzorax-control-tls bootstrap-wait
  systemctl_retry start hyzorax-control-tls-renew.timer
  trusted_tls_ready=false
  for _ in {1..30}; do
    if curl -fsS --noproxy '*' --max-time 3 --resolve "${panel_ip}:${panel_port}:127.0.0.1" \\
        "https://${panel_ip}:${panel_port}/${entrance_code}/api/v1/healthz" >/dev/null 2>&1; then
      trusted_tls_ready=true
      break
    fi
    sleep 1
  done
  if [[ "${trusted_tls_ready}" != true ]]; then
    echo "Trusted IP TLS did not pass browser-equivalent verification." >&2
    /usr/local/libexec/hyzorax-control-tls status >&2 || true
    exit 1
  fi
else
  # VirtualBox/private-address environments cannot receive a public IP SAN.
  echo "[HYZoraX IP TLS] NOTICE: ${panel_ip:-No IPv4 address} is not a globally routable IPv4 address; trusted IP TLS is not applicable in this local/private environment."
  echo "[HYZoraX IP TLS] NOTICE: Existing local/self-signed TLS remains active; public-IP TLS will stay strict on a real VPS."
  systemctl_retry start hyzorax-control-tls-renew.timer || true
fi
'''
for rel in ['build/bootstrap.sh','packaging/bootstrap.sh']:
 repl(rel,old,new)

for rel in ['internal/web/static/index.html','internal/web/assets_test.go','internal/httpapi/app_test.go']:
 p=root/rel; s=p.read_text(); p.write_text(s.replace('Version 1.7.3','Version 1.7.4'))
print('V1.7.4 runtime hotfix patch applied')
