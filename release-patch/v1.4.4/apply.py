#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
bootstrap = ROOT / 'packaging/bootstrap.sh'
text = bootstrap.read_text()

# 1) Wait for the fresh Ubuntu package transaction BEFORE starting the
# transient installer worker. This avoids starting a long-lived worker while
# apt/systemd are still being upgraded and prevents mid-install daemon reexecs
# from terminating/restarting the worker.
marker = '''transient_unit_known() {
'''
if marker not in text:
    raise SystemExit('transient_unit_known marker not found')
preflight = r'''package_manager_busy() {
  pgrep -x apt-get >/dev/null 2>&1 && return 0
  pgrep -x apt >/dev/null 2>&1 && return 0
  pgrep -x dpkg >/dev/null 2>&1 && return 0
  pgrep -x dpkg-deb >/dev/null 2>&1 && return 0
  return 1
}

wait_for_host_package_manager() {
  local waited=0
  local timeout=900
  local announced=false

  while package_manager_busy; do
    if [[ "${announced}" == false ]]; then
      echo "Waiting for Ubuntu package initialization to finish..."
      echo "HYZoraX will continue automatically; no action is required."
      announced=true
    fi
    if (( waited >= timeout )); then
      echo "Ubuntu package initialization did not finish within ${timeout}s." >&2
      return 1
    fi
    sleep 5
    waited=$((waited + 5))
  done

  if [[ "${announced}" == true ]]; then
    echo "Ubuntu package manager: ready"
    # Give package-triggered systemd reload/reexec activity a brief moment to
    # settle before creating the transient installer unit.
    sleep 2
  fi
}

'''
text = text.replace(marker, preflight + marker, 1)

old_launch = '''if [[ "${worker_mode}" == false ]] && command -v systemd-run >/dev/null 2>&1 && [[ "$(cat /proc/1/comm 2>/dev/null || true)" == "systemd" ]]; then
  wait_for_systemd_bus
'''
new_launch = '''if [[ "${worker_mode}" == false ]] && command -v systemd-run >/dev/null 2>&1 && [[ "$(cat /proc/1/comm 2>/dev/null || true)" == "systemd" ]]; then
  wait_for_host_package_manager
  wait_for_systemd_bus
'''
if old_launch not in text:
    raise SystemExit('worker launch block not found')
text = text.replace(old_launch, new_launch, 1)

# 2) Parent monitor must tolerate transient D-Bus/control-bus resets without
# printing a scary error or treating an unreadable state as installation
# failure. The status file remains the authoritative completion signal.
old_monitor = '''  while [[ ! -f "${status_file}" ]]; do
    if systemctl is-failed --quiet "${unit_name}.service"; then
      echo "Installation worker failed before returning its status." >&2
      journalctl --no-pager -u "${unit_name}.service" >&2 || true
      exit 1
    fi
    if (( wait_seconds >= 900 )); then
'''
new_monitor = '''  while [[ ! -f "${status_file}" ]]; do
    unit_state="$(systemctl show -p ActiveState --value "${unit_name}.service" 2>/dev/null || true)"
    if [[ "${unit_state}" == "failed" ]]; then
      echo "Installation worker failed before returning its status." >&2
      journalctl --no-pager -u "${unit_name}.service" >&2 || true
      exit 1
    fi
    if (( wait_seconds >= 900 )); then
'''
if old_monitor not in text:
    raise SystemExit('parent monitor block not found')
text = text.replace(old_monitor, new_monitor, 1)

# 3) Never write a success status from an interrupted/restarted worker. The
# previous EXIT trap could record 0 during a TERM/reexec edge case, allowing
# the parent to report success while TLS was still self-signed.
old_finish = '''install -o root -g root -m 0600 /dev/null "${install_log}"
exec > >(/usr/bin/tee "${install_log}") 2>&1

finish_install() {
  status=$?
  trap - EXIT
  if [[ -n "${HYZORAX_INSTALL_STATUS_FILE:-}" ]]; then
    printf '%s\\n' "${status}" > "${HYZORAX_INSTALL_STATUS_FILE}"
    chmod 0600 "${HYZORAX_INSTALL_STATUS_FILE}"
  fi
  exit "${status}"
}
trap finish_install EXIT
'''
new_finish = '''install -o root -g root -m 0600 /dev/null "${install_log}"
exec > >(/usr/bin/tee "${install_log}") 2>&1

install_completed=false
if [[ "${worker_mode}" == true && -n "${HYZORAX_INSTALL_STATUS_FILE:-}" ]]; then
  rm -f -- "${HYZORAX_INSTALL_STATUS_FILE}"
fi

finish_install() {
  status=$?
  trap - EXIT
  if [[ "${install_completed}" != true && "${status}" -eq 0 ]]; then
    status=1
  fi
  if [[ -n "${HYZORAX_INSTALL_STATUS_FILE:-}" ]]; then
    printf '%s\\n' "${status}" > "${HYZORAX_INSTALL_STATUS_FILE}"
    chmod 0600 "${HYZORAX_INSTALL_STATUS_FILE}"
  fi
  exit "${status}"
}
trap finish_install EXIT
'''
if old_finish not in text:
    raise SystemExit('finish_install block not found')
text = text.replace(old_finish, new_finish, 1)

# The final two user-facing lines in V1.4.3 are Username/Password. Mark the
# worker complete only after trusted TLS verification and final summary output.
summary_tail = '''printf 'Username: %s\\n' "${final_username:-hyzorax}"
printf 'Password: %s\\n' "${final_password:-unavailable - run hz 7 to reset}"
'''
if summary_tail not in text:
    raise SystemExit('final summary tail not found')
text = text.replace(summary_tail, summary_tail + '\ninstall_completed=true\n', 1)

bootstrap.write_text(text)

# Update embedded UI release footer/tests for the hotfix release.
index = ROOT / 'internal/web/static/index.html'
html = index.read_text()
html = html.replace('Version 1.4.3', 'Version 1.4.4')
index.write_text(html)

for rel in ['internal/httpapi/app_test.go', 'internal/web/assets_test.go']:
    path = ROOT / rel
    body = path.read_text()
    body = body.replace('1.4.3', '1.4.4')
    path.write_text(body)

print('V1.4.4 installer readiness hotfix applied')
