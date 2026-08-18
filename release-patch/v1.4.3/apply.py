#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()


def read(rel):
    return (ROOT / rel).read_text()


def write(rel, text):
    (ROOT / rel).write_text(text)


def replace(rel, old, new, count=1):
    text = read(rel)
    if old not in text:
        raise SystemExit(f"expected text not found in {rel}: {old[:100]!r}")
    text = text.replace(old, new, count)
    write(rel, text)


def regex_replace(rel, pattern, repl, count=1, flags=0):
    text = read(rel)
    text2, n = re.subn(pattern, repl, text, count=count, flags=flags)
    if n != count:
        raise SystemExit(f"expected {count} regex replacement(s) in {rel}, got {n}: {pattern}")
    write(rel, text2)


# ---------------------------------------------------------------------------
# Bootstrap: preserve user config, accept custom mixed-case entrances, make
# trusted IP TLS part of installation completion, and simplify final output.
# ---------------------------------------------------------------------------
bootstrap = "packaging/bootstrap.sh"
replace(
    bootstrap,
    'install -o root -g hyzorax-control -m 0640 "${bundle_dir}/config.toml" /etc/hyzorax-control/config.toml\n',
    '''if [[ ! -f /etc/hyzorax-control/config.toml ]]; then\n  install -o root -g hyzorax-control -m 0640 "${bundle_dir}/config.toml" /etc/hyzorax-control/config.toml\nelse\n  chown root:hyzorax-control /etc/hyzorax-control/config.toml\n  chmod 0640 /etc/hyzorax-control/config.toml\nfi\n\nread_panel_port() {\n  local port=""\n  port="$(sed -nE 's/^[[:space:]]*listen[[:space:]]*=[[:space:]]*"[^\"]*:([0-9]+)".*/\\1/p' /etc/hyzorax-control/config.toml | head -n 1)"\n  [[ "${port}" =~ ^[0-9]+$ ]] || port=9443\n  printf '%s' "${port}"\n}\npanel_port="$(read_panel_port)"\n'''
)
replace(
    bootstrap,
    '[[ "${code}" =~ ^[a-z0-9]{8}$ && "${code}" =~ [a-z] && "${code}" =~ [0-9] ]]',
    '[[ "${code}" =~ ^[A-Za-z0-9]{8}$ && "${code}" =~ [A-Za-z] && "${code}" =~ [0-9] ]]'
)
replace(
    bootstrap,
    'Existing security entrance code is invalid; expected 8 lowercase letters/numbers with at least one letter and one number.',
    'Existing security entrance code is invalid; expected exactly 8 letters/numbers with at least one letter and one number.'
)
# Both pre/post-TLS health checks must follow the configured panel port.
bootstrap_text = read(bootstrap).replace('https://127.0.0.1:9443/${entrance_code}/api/v1/healthz', 'https://127.0.0.1:${panel_port}/${entrance_code}/api/v1/healthz')
write(bootstrap, bootstrap_text)

regex_replace(
    bootstrap,
    r'''echo "Preparing independent IP-only trusted TLS\.\.\."\ntls_bootstrap_unit=.*?systemctl_retry start hyzorax-control-tls-renew\.timer \|\| true\n''',
    '''echo "Applying independent IP-only trusted TLS..."\n# Installation is not declared complete until the browser-trusted IP\n# certificate has been issued, deployed, and verified. If Ubuntu still owns\n# the apt/dpkg lock on a fresh image, bootstrap-wait waits here instead of\n# exposing the temporary self-signed certificate as a completed install.\n/usr/local/libexec/hyzorax-control-tls bootstrap-wait\nsystemctl_retry start hyzorax-control-tls-renew.timer\n''',
    flags=re.S,
)

# Replace the second insecure health check after TLS with a trust-chain check.
old_post_tls = '''# Re-confirm the panel after a possible certificate deployment/restart.\nhealth_ready=false\nfor _ in {1..30}; do\n  if curl -kfsS --max-time 3 "https://127.0.0.1:${panel_port}/${entrance_code}/api/v1/healthz" >/dev/null 2>&1; then\n    health_ready=true\n    break\n  fi\n  sleep 1\ndone\nif [[ "${health_ready}" != true ]]; then\n  echo "Control service did not become healthy after TLS maintenance." >&2\n  systemctl status --no-pager hyzorax-control.service >&2 || true\n  exit 1\nfi\n'''
new_post_tls = '''# Re-confirm the panel with normal CA verification. --resolve keeps the\n# health check local while validating the public IP SAN and Let's Encrypt\n# trust chain exactly as a browser will.\npanel_ip=""\nif command -v ip >/dev/null 2>&1; then\n  panel_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i == "src") {print $(i+1); exit}}' || true)"\nfi\n[[ -n "${panel_ip}" ]] || { echo "Could not detect panel IPv4 address for trusted TLS verification." >&2; exit 1; }\ntrusted_tls_ready=false\nfor _ in {1..30}; do\n  if curl -fsS --noproxy '*' --max-time 3 --resolve "${panel_ip}:${panel_port}:127.0.0.1" \\\n      "https://${panel_ip}:${panel_port}/${entrance_code}/api/v1/healthz" >/dev/null 2>&1; then\n    trusted_tls_ready=true\n    break\n  fi\n  sleep 1\ndone\nif [[ "${trusted_tls_ready}" != true ]]; then\n  echo "Trusted IP TLS did not pass browser-equivalent verification." >&2\n  /usr/local/libexec/hyzorax-control-tls status >&2 || true\n  exit 1\nfi\n'''
replace(bootstrap, old_post_tls, new_post_tls)

old_summary = '''panel_url="https://${panel_host}:9443/${entrance_code}/"\n\necho\necho "HYZoraX Control Center installation is complete."\necho "Version: $(/usr/local/bin/hyzorax-control -version | awk '{print $2}')"\necho "Panel URL: ${panel_url}"\nif grep -q '^Initial Owner username:' <<<"${owner_credentials}"; then\n  echo "Owner account: created automatically"\nfi\nprintf '%s\\n' "${owner_credentials}"\necho "Root-only installation log: ${install_log}"\n'''
new_summary = '''panel_url="https://${panel_host}:${panel_port}/${entrance_code}/"\n\nfinal_username="${cache_owner_username:-}"\nfinal_password="${cache_owner_password:-}"\nif [[ -r "${credentials_cache}" ]]; then\n  [[ -n "${final_username}" ]] || final_username="$(sed -n 's/^username=//p' "${credentials_cache}" | head -n 1)"\n  [[ -n "${final_password}" ]] || final_password="$(sed -n 's/^password=//p' "${credentials_cache}" | head -n 1)"\nfi\n\necho\necho "HYZoraX Control Panel installation is complete."\necho "Version: $(/usr/local/bin/hyzorax-control -version | awk '{print $2}')"\necho "Panel URL: ${panel_url}"\nprintf 'Username: %s\\n' "${final_username:-hyzorax}"\nprintf 'Password: %s\\n' "${final_password:-unavailable - run hz 7 to reset}"\n'''
replace(bootstrap, old_summary, new_summary)

# ---------------------------------------------------------------------------
# TLS manager: configured port, mixed-case custom entrance support, synchronous
# wording, shorter bounded package lock wait, and Control Panel terminology.
# ---------------------------------------------------------------------------
tls = "packaging/hyzorax-control-tls"
replace(
    tls,
    'panel_port="9443"\n',
    '''panel_config="/etc/hyzorax-control/config.toml"\npanel_port="$(sed -nE 's/^[[:space:]]*listen[[:space:]]*=[[:space:]]*"[^\"]*:([0-9]+)".*/\\1/p' "${panel_config}" 2>/dev/null | head -n 1)"\n[[ "${panel_port}" =~ ^[0-9]+$ ]] || panel_port=9443\n'''
)
replace(
    tls,
    '[[ "${code}" =~ ^[a-z0-9]{8}$ && "${code}" =~ [a-z] && "${code}" =~ [0-9] ]] || return 1',
    '[[ "${code}" =~ ^[A-Za-z0-9]{8}$ && "${code}" =~ [A-Za-z] && "${code}" =~ [0-9] ]] || return 1'
)
replace(tls, 'local timeout=1200', 'local timeout=300')
for old, new in [
    ('trusted IP TLS will be retried automatically in the background.', 'trusted IP TLS will be retried by the automatic maintenance timer.'),
    ('waiting in the background before preparing trusted IP TLS...', 'waiting before preparing trusted IP TLS...'),
    ('Background trusted-IP TLS bootstrap could not detect a public IPv4 address.', 'Trusted-IP TLS bootstrap could not detect a public IPv4 address.'),
    ('Background trusted-IP TLS bootstrap found TCP port 80 occupied.', 'Trusted-IP TLS bootstrap found TCP port 80 occupied.'),
    ("Existing TLS remains active; 'hz ssl' can retry later.", 'Existing TLS remains active.'),
    ('Background trusted-IP TLS bootstrap could not prepare Certbot.', 'Trusted-IP TLS bootstrap could not prepare Certbot.'),
    ('HYZoraX Control Center IP TLS', 'HYZoraX Control Panel IP TLS'),
    ('Control Center health check passed.', 'Control Panel health check passed.'),
    ('Control Center failed after TLS deployment', 'Control Panel failed after TLS deployment'),
]:
    text = read(tls)
    if old in text:
        write(tls, text.replace(old, new))

# ---------------------------------------------------------------------------
# Entrance gate: user-chosen entrances may use upper/lowercase letters, while
# generated defaults remain the compact lowercase format.
# ---------------------------------------------------------------------------
entrance = "internal/httpapi/entrance.go"
replace(
    entrance,
    'security entrance code must contain exactly %d lowercase letters/numbers with at least one letter and one number',
    'security entrance code must contain exactly %d letters/numbers with at least one letter and one number'
)
replace(
    entrance,
    "case character >= 'a' && character <= 'z':\n\t\t\thasLetter = true",
    "case (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z'):\n\t\t\thasLetter = true"
)

# Account role is user-facing through the session payload; use neutral admin
# terminology rather than Owner.
handlers = "internal/httpapi/handlers.go"
replace(handlers, '"role": "Owner"', '"role": "Administrator"')

# ---------------------------------------------------------------------------
# Web UI: clean login, Control Panel wording, profile dropdown, no privileged
# helper architecture card, 1-second live metrics retained.
# ---------------------------------------------------------------------------
index = "internal/web/static/index.html"
html = read(index)
html = html.replace('<title>HYZoraX Control Center</title>', '<title>HYZoraX Control Panel</title>')
new_gate = '''    <main id="gate" class="gate gate-login shell" hidden>\n      <section class="auth-panel auth-panel-only">\n        <div class="auth-card login-card">\n          <div class="login-brand">\n            <span class="brand-mark"><img src="assets/hyzorax-logo.png" alt=""></span>\n            <div><strong>HYZoraX</strong><small>CONTROL PANEL</small></div>\n          </div>\n          <form id="login-form" class="stack" hidden>\n            <h2>Sign in</h2>\n            <label>Username<input name="username" autocomplete="username" minlength="3" maxlength="32" required></label>\n            <label>Password\n              <span class="password-input">\n                <input name="password" type="password" autocomplete="current-password" minlength="8" maxlength="16" required>\n                <button class="password-toggle" type="button" data-password-toggle aria-label="Show password" title="Show password">\n                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path><circle cx="12" cy="12" r="2.8"></circle></svg>\n                </button>\n              </span>\n            </label>\n            <button class="primary" type="submit">Sign in</button>\n          </form>\n          <div id="gate-error" class="alert" role="alert" hidden></div>\n        </div>\n      </section>\n    </main>'''
html, n = re.subn(r'    <main id="gate" class="gate shell" hidden>.*?    </main>', new_gate, html, count=1, flags=re.S)
if n != 1:
    raise SystemExit("could not replace login gate")
html = html.replace('aria-label="HYZoraX Control Center"', 'aria-label="HYZoraX Control Panel"')
html = html.replace('<span><strong>HYZoraX</strong><small>CONTROL CENTER</small></span>', '<span><strong>HYZoraX</strong><small>CONTROL PANEL</small></span>')
html = html.replace('<p id="workspace-eyebrow" class="eyebrow">Control plane</p>', '<p id="workspace-eyebrow" class="eyebrow">Control Panel</p>')
html = html.replace('title="Check for Control Center updates"', 'title="Check for Control Panel updates"')
old_user = '''<div class="user-chip"><span id="user-initial">H</span><div><strong id="user-name">Owner</strong><small>Owner</small></div></div>\n            <button id="logout-button" class="ghost compact">Sign out</button>'''
new_user = '''<div class="user-menu">\n              <button id="user-menu-button" class="user-chip" type="button" aria-haspopup="menu" aria-expanded="false">\n                <span id="user-initial">H</span><div><strong id="user-name">hyzorax</strong><small>Account</small></div><span class="user-chevron">⌄</span>\n              </button>\n              <div id="user-menu" class="user-dropdown" role="menu" hidden>\n                <div class="user-dropdown-head"><small>Signed in as</small><strong id="user-menu-name">hyzorax</strong></div>\n                <button id="logout-button" type="button" role="menuitem">Sign out</button>\n              </div>\n            </div>'''
if old_user not in html:
    raise SystemExit("user chip block not found")
html = html.replace(old_user, new_user, 1)
# Remove the internal privileged-helper architecture card entirely.
html, n = re.subn(r'\n            <article class="panel">\n              <div class="panel-heading"><div><p class="eyebrow">Trusted boundary</p>.*?</article>', '', html, count=1, flags=re.S)
if n != 1:
    raise SystemExit("privileged helper card not found")
html = html.replace('<strong>Version 1.4.2</strong>', '<strong>Version 1.4.3</strong>')
write(index, html)

appjs = "internal/web/static/app.js"
js = read(appjs)
js = js.replace('$("#user-name").textContent = state.user.username;\n', '$("#user-name").textContent = state.user.username;\n$("#user-menu-name").textContent = state.user.username;\n')
js = js.replace('$("#workspace-eyebrow").textContent = selected === "files" ? "Server filesystem" : "Control plane";', '$("#workspace-eyebrow").textContent = selected === "files" ? "Server filesystem" : "Control Panel";')
js = js.replace('''if (!live) {\nconst helper = await request("api/v1/helper/health").catch((error) => ({ connected: false, message: error.message }));\nrenderHelper(helper);\n}\n''', '')
js, n = re.subn(r'function renderHelper\(data\) \{.*?\n\}\nasync function checkUpdateStatus', 'async function checkUpdateStatus', js, count=1, flags=re.S)
if n != 1:
    raise SystemExit("renderHelper function not found")
js = js.replace('HYZoraX Control Center', 'HYZoraX Control Panel')
old_logout = '''$("#logout-button").addEventListener("click", async () => {\ntry { await request("api/v1/auth/logout", { method: "POST" }); } catch (_) { /* local logout still proceeds */ }\nstate.user = null;\nstopDashboardLive();\nshowLogin();\n});'''
new_logout = '''const userMenuButton = $("#user-menu-button");\nconst userMenu = $("#user-menu");\nfunction setUserMenu(open) {\nuserMenu.hidden = !open;\nuserMenuButton.setAttribute("aria-expanded", open ? "true" : "false");\n}\nuserMenuButton.addEventListener("click", (event) => {\nevent.stopPropagation();\nsetUserMenu(userMenu.hidden);\n});\ndocument.addEventListener("click", (event) => {\nif (!event.target.closest(".user-menu")) setUserMenu(false);\n});\ndocument.addEventListener("keydown", (event) => {\nif (event.key === "Escape") setUserMenu(false);\n});\n$("#logout-button").addEventListener("click", async () => {\nsetUserMenu(false);\ntry { await request("api/v1/auth/logout", { method: "POST" }); } catch (_) { /* local logout still proceeds */ }\nstate.user = null;\nstopDashboardLive();\nshowLogin();\n});'''
if old_logout not in js:
    raise SystemExit("logout handler not found")
js = js.replace(old_logout, new_logout, 1)
write(appjs, js)

css = "internal/web/static/app.css"
css_text = read(css)
css_text += '''\n\n/* V1.4.3 consolidated panel polish */\n.gate-login { display: block; min-height: 100vh; }\n.auth-panel-only { min-height: 100vh; border-left: 0; padding: 1.5rem; }\n.login-card { width: min(100%, 440px); }\n.login-brand { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.6rem; }\n.login-brand .brand-mark { width: 62px; height: 62px; border-radius: 19px; }\n.login-brand > div { display: flex; flex-direction: column; gap: .18rem; }\n.login-brand strong { font-size: 1.05rem; letter-spacing: .03em; }\n.login-brand small { color: var(--muted); font-size: .58rem; font-weight: 800; letter-spacing: .16em; }\n.login-card .stack h2 { margin: 0 0 .35rem; }\n.user-menu { position: relative; }\n.user-chip { border: 0; cursor: pointer; text-align: left; }\n.user-chevron { color: var(--muted); font-size: .9rem; margin-left: .15rem; }\n.user-dropdown { position: absolute; top: calc(100% + .55rem); right: 0; min-width: 190px; z-index: 30; padding: .45rem; border: 1px solid var(--line-strong); border-radius: 12px; background: rgba(255,255,255,.98); box-shadow: 0 18px 48px rgba(40,86,145,.18); }\n.user-dropdown-head { display: grid; gap: .18rem; padding: .65rem .7rem .7rem; border-bottom: 1px solid var(--line); }\n.user-dropdown-head small { color: var(--muted); font-size: .62rem; }\n.user-dropdown-head strong { font-size: .78rem; }\n.user-dropdown button { width: 100%; margin-top: .35rem; padding: .65rem .7rem; border-radius: 8px; text-align: left; color: #496889; background: transparent; font-weight: 700; }\n.user-dropdown button:hover { color: var(--blue-deep); background: rgba(99,204,248,.12); }\n.panel-grid > .panel:only-child { grid-column: 1 / -1; }\n'''
write(css, css_text)

# ---------------------------------------------------------------------------
# hz CLI: full user-facing polish, direct numeric actions, custom mixed-case
# entrance, dynamic port, transactional firewall-aware port changes, no usage
# dump, and no Owner terminology.
# ---------------------------------------------------------------------------
hz = "packaging/hz"
hz_text = read(hz)
hz_text = hz_text.replace('tls_manager="/usr/local/libexec/hyzorax-control-tls"\nupdater=', 'tls_manager="/usr/local/libexec/hyzorax-control-tls"\nconfig_file="/etc/hyzorax-control/config.toml"\nfirewall_state_file="/etc/hyzorax-control/firewall.port"\nupdater=')
hz_text = hz_text.replace('[[ "${code}" =~ ^[a-z0-9]{8}$ && "${code}" =~ [a-z] && "${code}" =~ [0-9] ]]', '[[ "${code}" =~ ^[A-Za-z0-9]{8}$ && "${code}" =~ [A-Za-z] && "${code}" =~ [0-9] ]]')

# Insert terminal colors and configured-port helper after root check.
needle = '''if [[ "${EUID}" -ne 0 ]]; then\n  echo "Run hz as root." >&2\n  exit 1\nfi\n'''
insert = needle + '''\nif [[ -t 1 && -z "${NO_COLOR:-}" ]]; then\n  C_BLUE=$'\\033[1;36m'; C_GREEN=$'\\033[1;32m'; C_YELLOW=$'\\033[1;33m'; C_RED=$'\\033[1;31m'; C_DIM=$'\\033[2m'; C_RESET=$'\\033[0m'\nelse\n  C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_DIM=""; C_RESET=""\nfi\n\ncurrent_port() {\n  local port=""\n  port="$(sed -nE 's/^[[:space:]]*listen[[:space:]]*=[[:space:]]*"[^\"]*:([0-9]+)".*/\\1/p' "${config_file}" 2>/dev/null | head -n 1)"\n  [[ "${port}" =~ ^[0-9]+$ ]] || port=9443\n  printf '%s' "${port}"\n}\n'''
if needle not in hz_text:
    raise SystemExit("hz root-check insertion point not found")
hz_text = hz_text.replace(needle, insert, 1)

# Dynamic URL.
hz_text = hz_text.replace("printf 'Panel URL: https://%s:9443/%s/\\n' \"$(panel_host)\" \"${entrance_code}\"", "printf 'Panel URL: https://%s:%s/%s/\\n' \"$(panel_host)\" \"$(current_port)\" \"${entrance_code}\"")

old_details = '''  echo "HYZoraX Control Center Details"\n  printf 'Panel URL: https://%s:9443/%s/\\n' "${host}" "${code}"\n  printf 'Panel IP: %s\\n' "${host}"\n  printf 'Owner username: %s\\n' "${cached_username:-unavailable}"\n  printf 'Owner password: %s\\n' "${cached_password:-unavailable - use option 7 to reset}"\n  printf 'Security entrance: %s\\n' "${code}"\n  printf 'Version: %s\\n' "${version}"\n'''
new_details = '''  local port="$(current_port)"\n  printf '%sHYZoraX Control Panel%s\\n\\n' "${C_BLUE}" "${C_RESET}"\n  printf '%sPanel IP:%s      %s%s%s\\n' "${C_DIM}" "${C_RESET}" "${C_GREEN}" "${host}" "${C_RESET}"\n  printf '%sPanel Port:%s    %s%s%s\\n' "${C_DIM}" "${C_RESET}" "${C_GREEN}" "${port}" "${C_RESET}"\n  printf '%sPanel URL:%s     %shttps://%s:%s/%s/%s\\n' "${C_DIM}" "${C_RESET}" "${C_BLUE}" "${host}" "${port}" "${code}" "${C_RESET}"\n  printf '%sUsername:%s      %s%s%s\\n' "${C_DIM}" "${C_RESET}" "${C_GREEN}" "${cached_username:-unavailable}" "${C_RESET}"\n  printf '%sPassword:%s      %s%s%s\\n' "${C_DIM}" "${C_RESET}" "${C_GREEN}" "${cached_password:-unavailable - use hz 7 to reset}" "${C_RESET}"\n  printf '%sVersion:%s       %s%s%s\\n' "${C_DIM}" "${C_RESET}" "${C_GREEN}" "${version}" "${C_RESET}"\n'''
if old_details not in hz_text:
    raise SystemExit("hz show_details block not found")
hz_text = hz_text.replace(old_details, new_details, 1)

hz_text = hz_text.replace('curl -kfsS --max-time 2 "https://127.0.0.1:9443/${code}/api/v1/healthz"', 'curl -kfsS --max-time 2 "https://127.0.0.1:$(current_port)/${code}/api/v1/healthz"')
hz_text = hz_text.replace('Security entrance must be exactly 8 lowercase letters/numbers and include at least one letter and one number.', 'Security entrance must be exactly 8 letters/numbers and include at least one letter and one number.')
hz_text = hz_text.replace('New 8-character security entrance (lowercase letters/numbers): ', 'New 8-character security entrance (letters/numbers): ')
hz_text = hz_text.replace('2) Set my own 8-character entrance', '2) Change entrance')
hz_text = hz_text.replace('echo "Owner Login Credentials"', 'echo "Login Credentials"')

# Suppress backend Owner-labelled text in credential actions and print simple labels.
old_apply = '''  output="$(printf '%s\\0%s\\0' "${username}" "${password}" | runuser -u hyzorax-control -- /usr/local/bin/hyzorax-control -config /etc/hyzorax-control/config.toml -update-owner-credentials)"\n  printf '%s\\n' "${output}"\n  result_username="$(sed -n 's/^Owner username:[[:space:]]*//p' <<<"${output}" | tail -n 1)"\n'''
new_apply = '''  output="$(printf '%s\\0%s\\0' "${username}" "${password}" | runuser -u hyzorax-control -- /usr/local/bin/hyzorax-control -config /etc/hyzorax-control/config.toml -update-owner-credentials)"\n  result_username="$(sed -n 's/^Owner username:[[:space:]]*//p' <<<"${output}" | tail -n 1)"\n'''
if old_apply not in hz_text:
    raise SystemExit("hz credential output block not found")
hz_text = hz_text.replace(old_apply, new_apply, 1)
hz_text = hz_text.replace('''  [[ -n "${cached_username:-}" && -n "${cached_password:-}" ]] && write_credentials_cache "${cached_username}" "${cached_password}" || true\n}\n\nprompt_new_password()''', '''  [[ -n "${cached_username:-}" && -n "${cached_password:-}" ]] && write_credentials_cache "${cached_username}" "${cached_password}" || true\n  [[ -n "${username}" ]] && printf 'Username: %s\\n' "${cached_username:-${result_username}}"\n  [[ -n "${password}" ]] && echo "Password updated."\n}\n\nprompt_new_password()''', 1)
old_recovery = '''  output="$(runuser -u hyzorax-control -- /usr/local/bin/hyzorax-control -config /etc/hyzorax-control/config.toml -generate-owner-password)"\n  printf '%s\\n' "${output}"\n  username="$(sed -n 's/^Owner username:[[:space:]]*//p' <<<"${output}" | tail -n 1)"\n  password="$(sed -n 's/^New Owner password:[[:space:]]*//p' <<<"${output}" | tail -n 1)"\n  [[ -n "${username}" && -n "${password}" ]] && write_credentials_cache "${username}" "${password}" || true\n'''
new_recovery = '''  output="$(runuser -u hyzorax-control -- /usr/local/bin/hyzorax-control -config /etc/hyzorax-control/config.toml -generate-owner-password)"\n  username="$(sed -n 's/^Owner username:[[:space:]]*//p' <<<"${output}" | tail -n 1)"\n  password="$(sed -n 's/^New Owner password:[[:space:]]*//p' <<<"${output}" | tail -n 1)"\n  [[ -n "${username}" && -n "${password}" ]] && write_credentials_cache "${username}" "${password}" || true\n  printf 'Username: %s\\n' "${username}"\n  printf 'Password: %s\\n' "${password}"\n'''
if old_recovery not in hz_text:
    raise SystemExit("hz recovery block not found")
hz_text = hz_text.replace(old_recovery, new_recovery, 1)

# Port management helpers inserted before run_update.
port_block = r'''
valid_panel_port() {
  local port="${1:-}"
  [[ "${port}" =~ ^[0-9]+$ ]] || return 1
  (( port >= 1024 && port <= 65535 ))
}

port_in_use() {
  local port="${1:?port required}"
  command -v ss >/dev/null 2>&1 || return 1
  [[ -n "$(ss -H -ltn "sport = :${port}" 2>/dev/null || true)" ]]
}

FIREWALL_BACKEND="none"
FIREWALL_RULE_ADDED=false

prepare_firewall_port() {
  local port="${1:?port required}"
  FIREWALL_BACKEND="none"
  FIREWALL_RULE_ADDED=false
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
    FIREWALL_BACKEND="ufw"
    if ufw status 2>/dev/null | grep -Eq "(^|[[:space:]])${port}/tcp([[:space:]]|$).*ALLOW"; then
      return 0
    fi
    ufw allow "${port}/tcp" comment 'HYZoraX Control Panel' >/dev/null
    FIREWALL_RULE_ADDED=true
    return 0
  fi
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    FIREWALL_BACKEND="firewalld"
    if firewall-cmd --quiet --query-port="${port}/tcp"; then
      return 0
    fi
    firewall-cmd --permanent --add-port="${port}/tcp" >/dev/null
    firewall-cmd --reload >/dev/null
    FIREWALL_RULE_ADDED=true
  fi
}

rollback_new_firewall_port() {
  local port="${1:?port required}"
  [[ "${FIREWALL_RULE_ADDED}" == true ]] || return 0
  case "${FIREWALL_BACKEND}" in
    ufw) ufw delete allow "${port}/tcp" >/dev/null 2>&1 || true ;;
    firewalld) firewall-cmd --permanent --remove-port="${port}/tcp" >/dev/null 2>&1 || true; firewall-cmd --reload >/dev/null 2>&1 || true ;;
  esac
}

read_managed_firewall_state() {
  managed_firewall_backend=""
  managed_firewall_port=""
  [[ -r "${firewall_state_file}" ]] || return 1
  managed_firewall_backend="$(sed -n 's/^backend=//p' "${firewall_state_file}" | head -n1)"
  managed_firewall_port="$(sed -n 's/^port=//p' "${firewall_state_file}" | head -n1)"
  [[ -n "${managed_firewall_backend}" && -n "${managed_firewall_port}" ]]
}

remove_old_managed_firewall_port() {
  local old_port="${1:?old port required}"
  read_managed_firewall_state || return 0
  [[ "${managed_firewall_port}" == "${old_port}" ]] || return 0
  case "${managed_firewall_backend}" in
    ufw) command -v ufw >/dev/null 2>&1 && ufw delete allow "${old_port}/tcp" >/dev/null 2>&1 || true ;;
    firewalld) command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --permanent --remove-port="${old_port}/tcp" >/dev/null 2>&1 || true; command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --reload >/dev/null 2>&1 || true ;;
  esac
  rm -f -- "${firewall_state_file}"
}

save_managed_firewall_state() {
  local backend="${1:?backend required}" port="${2:?port required}" tmp=""
  tmp="$(mktemp /etc/hyzorax-control/.firewall-port.XXXXXX)"
  printf 'backend=%s\nport=%s\n' "${backend}" "${port}" > "${tmp}"
  chown root:root "${tmp}"
  chmod 0600 "${tmp}"
  mv -f "${tmp}" "${firewall_state_file}"
}

write_panel_port() {
  local new_port="${1:?new port required}" tmp=""
  tmp="$(mktemp /etc/hyzorax-control/.config.toml.XXXXXX)"
  python3 - "${config_file}" "${tmp}" "${new_port}" <<'PYPORT'
from pathlib import Path
import re, sys
src, dst, port = map(Path, sys.argv[1:3]) + [None] if False else (Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
text = src.read_text()
new, n = re.subn(r'(?m)^(\s*listen\s*=\s*"[^\"]*:)(\d+)("\s*)$', rf'\g<1>{port}\g<3>', text, count=1)
if n != 1:
    raise SystemExit('server listen setting was not found')
dst.write_text(new)
PYPORT
  chown root:hyzorax-control "${tmp}"
  chmod 0640 "${tmp}"
  mv -f "${tmp}" "${config_file}"
}

wait_for_port_health() {
  local port="${1:?port required}" code="${2:?entrance required}"
  for _ in {1..25}; do
    curl -kfsS --max-time 2 "https://127.0.0.1:${port}/${code}/api/v1/healthz" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

change_panel_port() {
  local old_port new_port code backup
  old_port="$(current_port)"
  code="$(current_entrance_code)" || return 1
  read -r -p "New panel port (1024-65535): " new_port
  valid_panel_port "${new_port}" || { echo "Panel port must be a number from 1024 to 65535." >&2; return 1; }
  if [[ "${new_port}" == "${old_port}" ]]; then
    echo "Panel port is already ${new_port}."
    return 0
  fi
  if port_in_use "${new_port}"; then
    echo "Port ${new_port} is already in use. Choose another port." >&2
    return 1
  fi

  prepare_firewall_port "${new_port}" || { echo "Could not prepare firewall access for port ${new_port}." >&2; return 1; }
  backup="$(mktemp /etc/hyzorax-control/.config-backup.XXXXXX)"
  cp -a "${config_file}" "${backup}"
  if ! write_panel_port "${new_port}" || ! systemctl restart hyzorax-control.service || ! wait_for_port_health "${new_port}" "${code}"; then
    cp -a "${backup}" "${config_file}"
    systemctl restart hyzorax-control.service || true
    rollback_new_firewall_port "${new_port}"
    rm -f -- "${backup}"
    echo "Panel port change failed; the previous port ${old_port} was restored." >&2
    return 1
  fi
  rm -f -- "${backup}"
  remove_old_managed_firewall_port "${old_port}"
  if [[ "${FIREWALL_RULE_ADDED}" == true ]]; then
    save_managed_firewall_state "${FIREWALL_BACKEND}" "${new_port}"
  fi
  echo "Panel port updated successfully."
  show_url
}
'''
# Fix a deliberately simple Python assignment in the embedded helper.
port_block = port_block.replace("src, dst, port = map(Path, sys.argv[1:3]) + [None] if False else (Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])", "src, dst, port = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]")
marker = '\nrun_update() {\n'
if marker not in hz_text:
    raise SystemExit("run_update marker not found")
hz_text = hz_text.replace(marker, '\n' + port_block + '\nrun_update() {\n', 1)

# Direct numeric commands and quiet invalid-command behavior.
regex = r'''run_action\(\) \{\n  case "\$\{1:-menu\}" in\n.*?\n  esac\n  return 0\n\}'''
new_run_action = '''run_action() {\n  case "${1:-menu}" in\n    1|details|detail) show_details ;;\n    2|status) show_status ;;\n    3|start) start_services ;;\n    4|stop) stop_services ;;\n    5|restart) restart_services ;;\n    6|logs) show_logs ;;\n    7|credentials) credentials_menu ;;\n    8|entrance) entrance_menu ;;\n    9|port) change_panel_port ;;\n    10|update) run_update ;;\n    url) show_url ;;\n    reset-password) generate_recovery_password ;;\n    ssl-status|ssl) ssl_status ;;\n    menu) return 1 ;;\n    *) echo "Invalid option. Run: hz" >&2; exit 2 ;;\n  esac\n  return 0\n}'''
hz_text, n = re.subn(regex, new_run_action, hz_text, count=1, flags=re.S)
if n != 1:
    raise SystemExit("run_action block not replaced")

old_menu = '''echo\necho "HYZoraX Control Center"\necho "1) Show panel Detail"\necho "2) Show service status"\necho "3) Start services"\necho "4) Stop services"\necho "5) Restart services"\necho "6) Show recent logs"\necho "7) Change/reset login credentials"\necho "8) Manage security entrance code"\necho "0) Exit"'''
new_menu = '''echo\nprintf '%sHYZoraX Control Panel%s\\n' "${C_BLUE}" "${C_RESET}"\necho "1) Show panel Detail"\necho "2) Show service status"\necho "3) Start services"\necho "4) Stop services"\necho "5) Restart services"\necho "6) Show recent logs"\necho "7) Change/reset login credentials"\necho "8) Manage security entrance code"\necho "9) Change panel port"\necho "10) Update Control Panel"\necho "0) Exit"'''
if old_menu not in hz_text:
    raise SystemExit("main hz menu not found")
hz_text = hz_text.replace(old_menu, new_menu, 1)
hz_text = hz_text.replace('''  8) entrance_menu ;;\n  0) exit 0 ;;''', '''  8) entrance_menu ;;\n  9) change_panel_port ;;\n  10) run_update ;;\n  0) exit 0 ;;''', 1)
hz_text = hz_text.replace('HYZoraX Control Center', 'HYZoraX Control Panel')
write(hz, hz_text)

# ---------------------------------------------------------------------------
# User-facing terminology across packaging/service descriptions.
# ---------------------------------------------------------------------------
for path in list((ROOT / "packaging").glob("*.service")) + list((ROOT / "packaging").glob("*.timer")):
    text = path.read_text()
    text = text.replace("HYZoraX Control Center", "HYZoraX Control Panel")
    path.write_text(text)

for rel in ["packaging/bootstrap.sh", "packaging/hyzorax-control-tls", "packaging/hyzorax-control-updater"]:
    text = read(rel).replace("HYZoraX Control Center", "HYZoraX Control Panel")
    write(rel, text)

print("V1.4.3 consolidated polish patch applied")
