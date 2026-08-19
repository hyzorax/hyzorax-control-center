#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()

def read(rel):
    return (root / rel).read_text(encoding="utf-8")

def write(rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"{label}: marker not found")
    return text.replace(old, new, 1)

def sub_once(text, pattern, repl, label, flags=re.S):
    out, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    return out

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
html_path = "internal/web/static/index.html"
html = read(html_path)
html = replace_once(html, "Version 1.5.6", "Version 1.5.7", "version")

# ---------------------------------------------------------------------------
# Store: pending first-run password sentinel + atomic completion.
# No schema change is required; upgrades with real hashes remain configured.
# ---------------------------------------------------------------------------
store_path = "internal/store/store.go"
store = read(store_path)
store = replace_once(
    store,
    'var (\n\tErrNotFound = errors.New("not found")\n)\n',
    'var (\n\tErrNotFound = errors.New("not found")\n)\n\nconst PendingOwnerPasswordHash = "!hyzorax-owner-password-pending!"\n',
    "pending owner sentinel",
)
owner_methods = r'''
func (s *Store) Owner(ctx context.Context) (User, error) {
	var owner User
	err := s.db.QueryRowContext(ctx, `SELECT u.id, u.username, u.password_hash, u.totp_secret_cipher, u.status, u.mfa_enabled
		FROM panel_users u
		JOIN user_roles ur ON ur.user_id = u.id
		WHERE ur.role_id = 'role-owner' AND u.status IN ('active', 'disabled')
		ORDER BY u.created_at ASC LIMIT 1`).Scan(
		&owner.ID, &owner.Username, &owner.PasswordHash, &owner.TOTPSecretCipher, &owner.Status, &owner.MFAEnabled,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return User{}, ErrNotFound
	}
	return owner, err
}

func (s *Store) OwnerSetupPending(ctx context.Context) (User, bool, error) {
	owner, err := s.Owner(ctx)
	if err != nil {
		return User{}, false, err
	}
	return owner, owner.Status == "active" && owner.PasswordHash == PendingOwnerPasswordHash, nil
}

func (s *Store) CompleteOwnerSetup(ctx context.Context, passwordHash string, now time.Time) (User, bool, error) {
	if passwordHash == "" || passwordHash == PendingOwnerPasswordHash {
		return User{}, false, errors.New("configured password hash is required")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return User{}, false, err
	}
	defer tx.Rollback()

	var owner User
	err = tx.QueryRowContext(ctx, `SELECT u.id, u.username, u.password_hash, u.totp_secret_cipher, u.status, u.mfa_enabled
		FROM panel_users u
		JOIN user_roles ur ON ur.user_id = u.id
		WHERE ur.role_id = 'role-owner' AND u.status = 'active'
		ORDER BY u.created_at ASC LIMIT 1`).Scan(
		&owner.ID, &owner.Username, &owner.PasswordHash, &owner.TOTPSecretCipher, &owner.Status, &owner.MFAEnabled,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return User{}, false, ErrNotFound
	}
	if err != nil {
		return User{}, false, err
	}
	if owner.PasswordHash != PendingOwnerPasswordHash {
		return owner, false, nil
	}

	result, err := tx.ExecContext(ctx, `UPDATE panel_users SET password_hash = ?, updated_at = ?
		WHERE id = ? AND status = 'active' AND password_hash = ?`,
		passwordHash, now.UTC().Format(time.RFC3339Nano), owner.ID, PendingOwnerPasswordHash)
	if err != nil {
		return User{}, false, fmt.Errorf("complete Owner password setup: %w", err)
	}
	changed, err := result.RowsAffected()
	if err != nil {
		return User{}, false, err
	}
	if changed != 1 {
		return owner, false, nil
	}
	if _, err := tx.ExecContext(ctx, "DELETE FROM sessions WHERE user_id = ?", owner.ID); err != nil {
		return User{}, false, fmt.Errorf("invalidate Owner sessions after setup: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return User{}, false, fmt.Errorf("commit Owner password setup: %w", err)
	}
	owner.PasswordHash = passwordHash
	return owner, true, nil
}

'''
store = replace_once(store, "func (s *Store) UpdateOwnerCredentials", owner_methods + "func (s *Store) UpdateOwnerCredentials", "Owner setup methods")
write(store_path, store)

# ---------------------------------------------------------------------------
# CLI owner initialization: fresh installs create username only with an
# unusable sentinel. Existing installations are preserved exactly.
# Add a private read-only username flag for the SSH dashboard; hz is untouched.
# ---------------------------------------------------------------------------
main_path = "cmd/hyzorax-control/main.go"
main = read(main_path)
main = replace_once(
    main,
    '\tgenerateOwnerPassword := flag.Bool("generate-owner-password", false, "generate and install a new eight-character Owner password")\n',
    '\tgenerateOwnerPassword := flag.Bool("generate-owner-password", false, "generate and install a new eight-character Owner password")\n\tprintOwnerUsername := flag.Bool("owner-username", false, "print the configured Owner username and exit")\n',
    "owner username flag",
)
main = replace_once(
    main,
    '\tif *initializeOwnerAccount {\n\t\tcreated, username, password, err := initializeOwner(*configPath)',
    '\tif *printOwnerUsername {\n\t\tusername, err := configuredOwnerUsername(*configPath)\n\t\tif err != nil {\n\t\t\tfmt.Fprintf(os.Stderr, "read Owner username: %v\\n", err)\n\t\t\tos.Exit(1)\n\t\t}\n\t\tfmt.Println(username)\n\t\treturn\n\t}\n\tif *initializeOwnerAccount {\n\t\tcreated, username, password, err := initializeOwner(*configPath)',
    "owner username flag flow",
)
main = replace_once(
    main,
    '\t\tif created {\n\t\t\tfmt.Printf("Initial Owner username: %s\\nInitial Owner password: %s\\n", username, password)\n',
    '\t\tif created {\n\t\t\tfmt.Printf("Initial Owner username: %s\\nInitial Owner password setup: required\\n", username)\n',
    "installer credential output",
)
configured_owner = r'''
func configuredOwnerUsername(configPath string) (string, error) {
	cfg, err := config.Load(configPath)
	if err != nil {
		return "", err
	}
	data, err := store.Open(cfg.Storage.Database)
	if err != nil {
		return "", err
	}
	defer data.Close()
	owner, err := data.Owner(context.Background())
	if err != nil {
		return "", err
	}
	return owner.Username, nil
}

'''
main = replace_once(main, "func initializeOwner(configPath string) (bool, string, string, error) {", configured_owner + "func initializeOwner(configPath string) (bool, string, string, error) {", "configured owner helper")
main = sub_once(
    main,
    r'func initializeOwner\(configPath string\) \(bool, string, string, error\) \{.*?\n\}\n\nfunc run\(',
    r'''func initializeOwner(configPath string) (bool, string, string, error) {
	cfg, err := config.Load(configPath)
	if err != nil {
		return false, "", "", err
	}
	data, err := store.Open(cfg.Storage.Database)
	if err != nil {
		return false, "", "", err
	}
	defer data.Close()
	const username = "hyzorax"
	if err := cryptoutil.ValidateUsername(username); err != nil {
		return false, "", "", err
	}
	userID, err := cryptoutil.RandomID()
	if err != nil {
		return false, "", "", err
	}
	created, err := data.InitializeOwner(context.Background(), store.User{
		ID: userID, Username: username, PasswordHash: store.PendingOwnerPasswordHash,
	}, time.Now())
	if err != nil {
		return false, "", "", err
	}
	if !created {
		return false, "", "", nil
	}
	return true, username, "", nil
}

func run(''',
    "initialize owner pending setup",
)
write(main_path, main)

# Main CLI test expectations.
main_test_path = "cmd/hyzorax-control/main_test.go"
main_test = read(main_test_path)
main_test = sub_once(
    main_test,
    r'if username != "hyzorax" \|\| len\(password\) != 8 \{.*?\n\t\}\n\tif err := cryptoutil\.ValidatePassword\(password\); err != nil \{.*?\n\t\}',
    'if username != "hyzorax" || password != "" {\n\t\tt.Fatalf("unexpected pending credentials: username=%q password=%q", username, password)\n\t}',
    "initialize owner test expectation",
)
# cryptoutil import is no longer needed if this was its only use.
main_test = main_test.replace('\n\t"github.com/hyzorax/hyzorax-control/internal/cryptoutil"\n', '\n')
write(main_test_path, main_test)

# ---------------------------------------------------------------------------
# HTTP first-run setup + Remember me.
# ---------------------------------------------------------------------------
handlers_path = "internal/httpapi/handlers.go"
handlers = read(handlers_path)
handlers = replace_once(
    handlers,
    'type loginRequest struct {\n\tUsername string `json:"username"`\n\tPassword string `json:"password"`\n}\n',
    'type loginRequest struct {\n\tUsername string `json:"username"`\n\tPassword string `json:"password"`\n\tRemember bool   `json:"remember"`\n}\n\ntype ownerSetupRequest struct {\n\tPassword        string `json:"password"`\n\tConfirmPassword string `json:"confirm_password"`\n}\n',
    "login remember request",
)
handlers = replace_once(
    handlers,
    'const (\n\tmaxUploadRequestBytes = 12 * 1024 * 1024',
    'const (\n\trememberSessionTTL    = 30 * 24 * time.Hour\n\tmaxUploadRequestBytes = 12 * 1024 * 1024',
    "remember ttl",
)
setup_handlers = r'''
func (a *App) handleOwnerSetupStatus(writer http.ResponseWriter, request *http.Request) {
	owner, pending, err := a.store.OwnerSetupPending(request.Context())
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeError(writer, http.StatusServiceUnavailable, "owner_unavailable", "The administrator account is not initialized yet.")
			return
		}
		a.logger.Printf("owner setup status request_id=%s error=%v", requestID(request.Context()), err)
		writeError(writer, http.StatusInternalServerError, "setup_status_failed", "Administrator setup status could not be read.")
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{"required": pending, "username": owner.Username})
}

func (a *App) handleOwnerSetup(writer http.ResponseWriter, request *http.Request) {
	var input ownerSetupRequest
	if !decodeJSON(writer, request, &input) {
		return
	}
	key := remoteIP(request) + "\x00owner-setup"
	if !a.limiter.allow(key, a.now()) {
		writeError(writer, http.StatusTooManyRequests, "setup_rate_limited", "Too many setup attempts. Try again later.")
		return
	}
	if input.Password != input.ConfirmPassword {
		writeError(writer, http.StatusBadRequest, "password_mismatch", "Password confirmation does not match.")
		return
	}
	passwordHash, err := cryptoutil.HashPassword(input.Password)
	if err != nil {
		writeError(writer, http.StatusBadRequest, "password_policy", err.Error())
		return
	}
	owner, completed, err := a.store.CompleteOwnerSetup(request.Context(), passwordHash, a.now())
	if err != nil {
		a.logger.Printf("owner setup request_id=%s error=%v", requestID(request.Context()), err)
		writeError(writer, http.StatusInternalServerError, "setup_failed", "Administrator password could not be configured.")
		return
	}
	if !completed {
		writeError(writer, http.StatusConflict, "setup_completed", "Administrator password has already been configured. Sign in instead.")
		return
	}
	a.limiter.reset(key)
	a.auditActor(request, owner.ID, "", "auth.owner_password_setup", owner.ID, "success", map[string]any{"source": "first_run_web"})
	writeJSON(writer, http.StatusOK, map[string]any{"status": "ready", "username": owner.Username})
}

'''
# handlers.go needs errors import for setup status.
handlers = replace_once(handlers, '\t"encoding/json"\n', '\t"encoding/json"\n\t"errors"\n', "handlers errors import")
handlers = replace_once(handlers, "func (a *App) handleLogin", setup_handlers + "func (a *App) handleLogin", "setup handlers")
handlers = replace_once(handlers, 'if !a.issueSession(writer, request, user) {', 'if !a.issueSession(writer, request, user, input.Remember) {', "remember session issuance")
handlers = replace_once(handlers, 'func (a *App) issueSession(writer http.ResponseWriter, request *http.Request, user store.User) bool {', 'func (a *App) issueSession(writer http.ResponseWriter, request *http.Request, user store.User, remember bool) bool {', "issue session signature")
handlers = replace_once(
    handlers,
    '\tnow := a.now()\n\texpires := now.Add(a.config.Security.SessionTTL)\n',
    '\tnow := a.now()\n\tttl := a.config.Security.SessionTTL\n\tif remember {\n\t\tttl = rememberSessionTTL\n\t}\n\texpires := now.Add(ttl)\n',
    "remember expiry",
)
handlers = replace_once(
    handlers,
    '\tsetAuthCookies(writer, sessionToken, csrfToken, a.config.Security.SessionTTL, a.config.Security.SecureCookies, a.cookiePath)\n',
    '\tsetAuthCookies(writer, sessionToken, csrfToken, ttl, a.config.Security.SecureCookies, a.cookiePath, remember)\n',
    "remember cookie issuance",
)
write(handlers_path, handlers)

app_path = "internal/httpapi/app.go"
app = read(app_path)
app = replace_once(
    app,
    '\tmux.HandleFunc("POST /api/v1/auth/login", a.handleLogin)\n',
    '\tmux.HandleFunc("GET /api/v1/auth/setup/status", a.handleOwnerSetupStatus)\n\tmux.HandleFunc("POST /api/v1/auth/setup", a.handleOwnerSetup)\n\tmux.HandleFunc("POST /api/v1/auth/login", a.handleLogin)\n',
    "setup routes",
)
write(app_path, app)

middleware_path = "internal/httpapi/middleware.go"
middleware = read(middleware_path)
middleware = replace_once(
    middleware,
    '\t\tif now.Sub(session.LastSeenAt) > time.Minute {\n\t\t\tif err := a.store.RefreshSession(request.Context(), session.ID, now, now.Add(a.config.Security.SessionTTL)); err != nil {',
    '\t\tif now.Sub(session.LastSeenAt) > time.Minute {\n\t\t\tpersistent := session.ExpiresAt.Sub(session.LastSeenAt) > 24*time.Hour\n\t\t\tttl := a.config.Security.SessionTTL\n\t\t\tif persistent {\n\t\t\t\tttl = rememberSessionTTL\n\t\t\t}\n\t\t\tif err := a.store.RefreshSession(request.Context(), session.ID, now, now.Add(ttl)); err != nil {',
    "remember session refresh",
)
middleware = replace_once(
    middleware,
    '\t\t\t\tsetAuthCookies(writer, cookie.Value, csrfCookie.Value, a.config.Security.SessionTTL, a.config.Security.SecureCookies, a.cookiePath)\n',
    '\t\t\t\tsetAuthCookies(writer, cookie.Value, csrfCookie.Value, ttl, a.config.Security.SecureCookies, a.cookiePath, persistent)\n',
    "remember cookie refresh",
)
middleware = replace_once(
    middleware,
    'func setAuthCookies(writer http.ResponseWriter, sessionToken, csrfToken string, ttl time.Duration, secure bool, path string) {\n\tmaxAge := int(ttl.Seconds())\n\thttp.SetCookie(writer, &http.Cookie{Name: sessionCookieName, Value: sessionToken, Path: path, MaxAge: maxAge, HttpOnly: true, Secure: secure, SameSite: http.SameSiteStrictMode})\n\thttp.SetCookie(writer, &http.Cookie{Name: csrfCookieName, Value: csrfToken, Path: path, MaxAge: maxAge, HttpOnly: false, Secure: secure, SameSite: http.SameSiteStrictMode})\n}',
    'func setAuthCookies(writer http.ResponseWriter, sessionToken, csrfToken string, ttl time.Duration, secure bool, path string, persistent bool) {\n\tmaxAge := 0\n\tif persistent {\n\t\tmaxAge = int(ttl.Seconds())\n\t}\n\thttp.SetCookie(writer, &http.Cookie{Name: sessionCookieName, Value: sessionToken, Path: path, MaxAge: maxAge, HttpOnly: true, Secure: secure, SameSite: http.SameSiteStrictMode})\n\thttp.SetCookie(writer, &http.Cookie{Name: csrfCookieName, Value: csrfToken, Path: path, MaxAge: maxAge, HttpOnly: false, Secure: secure, SameSite: http.SameSiteStrictMode})\n}',
    "persistent cookie helper",
)
write(middleware_path, middleware)

# ---------------------------------------------------------------------------
# Auth UI: first-run password setup and Remember me.
# ---------------------------------------------------------------------------
login_forms = r'''<form id="setup-form" class="stack" hidden>
            <h2>Set administrator password</h2>
            <p class="muted setup-copy">Create the password you will use to sign in to HYZoraX Control Panel.</p>
            <div class="setup-username-row"><span>Username</span><strong id="setup-username">hyzorax</strong></div>
            <label>Password
              <span class="password-input">
                <input name="password" type="password" autocomplete="new-password" minlength="8" maxlength="16" required>
                <button class="password-toggle" type="button" data-password-toggle aria-label="Show password" title="Show password"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path><circle cx="12" cy="12" r="2.8"></circle></svg></button>
              </span>
            </label>
            <label>Confirm password
              <span class="password-input">
                <input name="confirm_password" type="password" autocomplete="new-password" minlength="8" maxlength="16" required>
                <button class="password-toggle" type="button" data-password-toggle aria-label="Show password" title="Show password"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path><circle cx="12" cy="12" r="2.8"></circle></svg></button>
              </span>
            </label>
            <p class="password-policy">8–16 characters · upper-case · lower-case · number · special character</p>
            <button class="primary" type="submit">Set password</button>
          </form>
          <form id="login-form" class="stack" hidden>
            <h2>Sign in</h2>
            <label>Username<input name="username" autocomplete="username" minlength="3" maxlength="32" required></label>
            <label>Password
              <span class="password-input">
                <input name="password" type="password" autocomplete="current-password" minlength="8" maxlength="16" required>
                <button class="password-toggle" type="button" data-password-toggle aria-label="Show password" title="Show password">
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"></path><circle cx="12" cy="12" r="2.8"></circle></svg>
                </button>
              </span>
            </label>
            <label class="remember-row"><input name="remember" type="checkbox"><span>Remember me</span></label>
            <button class="primary" type="submit">Sign in</button>
          </form>'''
html = sub_once(html, r'<form id="login-form" class="stack" hidden>.*?</form>', login_forms, "auth forms")

# ---------------------------------------------------------------------------
# Editor HTML: two-row header, tabs, left tree, side Find/Replace panel.
# ---------------------------------------------------------------------------
editor_dialog = r'''<dialog id="editor-dialog" class="modal editor-modal">
      <form id="editor-form" class="modal-card editor-card">
        <div class="editor-header editor-header-primary">
          <div class="editor-title-group"><span class="editor-file-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M7 3.75h7l3 3V20.25H7z"></path><path d="M14 3.75v3h3"></path><path d="M9.5 11h5M9.5 14h5M9.5 17h3.5"></path></svg></span><div><h3 id="editor-name">Text editor</h3><p class="editor-path"><code id="editor-path"></code></p></div></div>
          <div class="editor-header-tools"><button id="editor-maximize-button" type="button" class="editor-tool-button" aria-label="Maximize editor" title="Maximize"><svg class="maximize-icon" viewBox="0 0 24 24"><path d="M8 4H4v4M16 4h4v4M8 20H4v-4M16 20h4v-4"></path></svg><svg class="restore-icon" viewBox="0 0 24 24"><path d="M8 7h9v9H8z"></path><path d="M6 17H4V5h12v2"></path></svg></button><span class="editor-encoding">UTF-8</span><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        </div>
        <div class="editor-header editor-header-secondary">
          <div id="editor-tabs" class="editor-tabs" role="tablist" aria-label="Open files"></div>
          <div class="editor-secondary-tools"><button id="editor-find-button" type="button" class="editor-tool-button editor-find-trigger" aria-label="Find in file" title="Find (Ctrl+F)"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="5.8"></circle><path d="m15.2 15.2 4.2 4.2"></path></svg><span>Find</span></button></div>
        </div>
        <div class="editor-layout">
          <aside class="editor-tree" aria-label="Server files"><div class="editor-tree-head"><strong>Files</strong><span>/</span></div><div id="editor-tree-content" class="editor-tree-content"><div class="editor-tree-loading">Loading files…</div></div></aside>
          <section class="editor-main">
            <aside id="editor-find-panel" class="editor-find-panel" hidden>
              <div class="editor-find-row"><input id="editor-find-input" type="search" autocomplete="off" spellcheck="false" placeholder="Find" aria-label="Find in file"><button id="editor-find-expand" type="button" class="editor-find-expand" aria-expanded="false" aria-label="Show replace" title="Replace">⌄</button><span id="editor-find-count" class="editor-find-count">0 / 0</span><button id="editor-find-previous" type="button" class="editor-find-nav" aria-label="Previous match">↑</button><button id="editor-find-next" type="button" class="editor-find-nav" aria-label="Next match">↓</button><button id="editor-find-close" type="button" class="editor-find-close" aria-label="Close find">×</button></div>
              <div id="editor-replace-row" class="editor-replace-row" hidden><input id="editor-replace-input" type="text" autocomplete="off" spellcheck="false" placeholder="Replace" aria-label="Replace with"><button id="editor-replace-one" type="button">Replace</button><button id="editor-replace-all" type="button">Replace all</button></div>
            </aside>
            <div class="editor-workspace"><pre id="editor-line-numbers" class="editor-line-numbers" aria-hidden="true">1</pre><textarea id="editor-content" name="content" spellcheck="false" aria-label="File contents"></textarea></div>
          </section>
        </div>
        <div id="editor-error" class="alert" role="alert" hidden></div>
        <div class="editor-footer"><span id="editor-status" class="editor-status">Ready · Ln 1, Col 1</span><div class="editor-shortcuts"><span>Ctrl+F Find</span><span>Ctrl+S Save</span><span>F3 Next</span></div><div class="modal-actions"><button type="button" class="ghost compact" data-close-dialog>Cancel</button><button type="submit" class="primary compact-primary">Save</button></div></div>
      </form>
    </dialog>'''
html = sub_once(html, r'<dialog id="editor-dialog" class="modal editor-modal">.*?</dialog>', editor_dialog, "editor workspace dialog")
write(html_path, html)

# ---------------------------------------------------------------------------
# Frontend auth + editor workspace JS.
# ---------------------------------------------------------------------------
js_path = "internal/web/static/app.js"
js = read(js_path)
js = replace_once(js, 'editorHash: "",\n', 'editorHash: "",\neditorTabs: [],\nactiveEditorPath: "",\neditorTreeLoaded: false,\n', "editor tab state")

show_login_old = r'''function showLogin() {
stopDashboardLive();
$("#login-form").hidden = false;
$("#gate").hidden = false;
$("#app").hidden = true;
clearError("#gate-error");
}'''
show_login_new = r'''function showLogin(username = "") {
stopDashboardLive();
$("#setup-form").hidden = true;
$("#login-form").hidden = false;
$("#gate").hidden = false;
$("#app").hidden = true;
clearError("#gate-error");
if (username) $("#login-form").elements.username.value = username;
}
function showSetup(setup) {
stopDashboardLive();
$("#login-form").hidden = true;
$("#setup-form").hidden = false;
$("#setup-username").textContent = setup.username || "hyzorax";
$("#gate").hidden = false;
$("#app").hidden = true;
clearError("#gate-error");
$("#setup-form").elements.password.focus();
}'''
js = replace_once(js, show_login_old, show_login_new, "show setup/login")
js = sub_once(
    js,
    r'async function start\(\) \{.*?\n\}\n\$\("#login-form"\)\.addEventListener\("submit", async \(event\) => \{.*?\n\}\);',
    r'''async function start() {
try {
const setup = await request("api/v1/auth/setup/status");
if (setup.required) { showSetup(setup); return; }
try {
state.user = await request("api/v1/auth/session");
await showDashboard();
} catch (_) { showLogin(setup.username || ""); }
} catch (_) { showLogin(); }
}
$("#setup-form").addEventListener("submit", async (event) => {
event.preventDefault(); clearError("#gate-error"); const form=event.currentTarget;
const password=form.elements.password.value, confirmPassword=form.elements.confirm_password.value;
if(password!==confirmPassword){showError("#gate-error","Password confirmation does not match.");return;}
setBusy(form,true);
try { const data=await request("api/v1/auth/setup",{method:"POST",body:JSON.stringify({password,confirm_password:confirmPassword})}); form.reset(); resetPasswordToggles(); showLogin(data.username||""); }
catch(error){showError("#gate-error",error.message);} finally{setBusy(form,false);}
});
$("#login-form").addEventListener("submit", async (event) => {
event.preventDefault();
clearError("#gate-error");
const form = event.currentTarget;
const fields = { username: form.elements.username.value, password: form.elements.password.value, remember: form.elements.remember.checked };
setBusy(form, true);
try {
state.user = await request("api/v1/auth/login", { method: "POST", body: JSON.stringify(fields) });
form.reset();
resetPasswordToggles();
await showDashboard();
} catch (error) {
showError("#gate-error", error.message);
} finally {
setBusy(form, false);
}
});''',
    "auth startup",
)

new_editor_functions = r'''const editorFindState={query:"",matches:[],index:-1};
function activeEditorTab(){return state.editorTabs.find((tab)=>tab.path===state.activeEditorPath)||null;}
function snapshotActiveEditor(){const tab=activeEditorTab();if(!tab)return;tab.content=$("#editor-content").value;}
function updateEditorCursorStatus(){const editor=$("#editor-content");if(!editor)return;const pos=editor.selectionStart||0,before=editor.value.slice(0,pos),lines=before.split("\n");const modified=activeEditorTab()&&activeEditorTab().content!==activeEditorTab().savedContent?"Modified":"Ready";$("#editor-status").textContent=`${modified} · Ln ${lines.length}, Col ${lines[lines.length-1].length+1}`;}
function updateEditorLineNumbers(){const textarea=$("#editor-content"),gutter=$("#editor-line-numbers");if(!textarea||!gutter)return;const lines=Math.max(1,textarea.value.split("\n").length);gutter.textContent=Array.from({length:lines},(_,index)=>index+1).join("\n");gutter.scrollTop=textarea.scrollTop;}
function insertEditorTab(event){if(event.key!=="Tab")return;event.preventDefault();const textarea=event.currentTarget,start=textarea.selectionStart,end=textarea.selectionEnd;textarea.setRangeText("  ",start,end,"end");textarea.dispatchEvent(new Event("input",{bubbles:true}));}
function renderEditorTabs(){const host=$("#editor-tabs");host.replaceChildren();state.editorTabs.forEach((tab)=>{const button=document.createElement("button");button.type="button";button.className="editor-tab"+(tab.path===state.activeEditorPath?" active":"");button.setAttribute("role","tab");button.setAttribute("aria-selected",tab.path===state.activeEditorPath?"true":"false");const name=document.createElement("span");name.textContent=tab.name;const close=document.createElement("span");close.className="editor-tab-close";close.textContent="×";close.title="Close tab";close.addEventListener("click",async(event)=>{event.stopPropagation();await closeEditorTab(tab.path);});button.addEventListener("click",()=>activateEditorTab(tab.path));button.append(name,close);host.append(button);});}
function resetEditorFind(){editorFindState.query="";editorFindState.matches=[];editorFindState.index=-1;const input=$("#editor-find-input");if(input)input.value="";const count=$("#editor-find-count");if(count)count.textContent="0 / 0";const panel=$("#editor-find-panel");if(panel)panel.hidden=true;const replace=$("#editor-replace-row");if(replace)replace.hidden=true;const expand=$("#editor-find-expand");if(expand)expand.setAttribute("aria-expanded","false");}
function collectEditorFindMatches(selectFirst=false){const editor=$("#editor-content"),input=$("#editor-find-input"),query=input.value;editorFindState.query=query;editorFindState.matches=[];editorFindState.index=-1;if(!query){$("#editor-find-count").textContent="0 / 0";return;}const haystack=editor.value.toLocaleLowerCase(),needle=query.toLocaleLowerCase();let cursor=0;while(cursor<=haystack.length-needle.length){const index=haystack.indexOf(needle,cursor);if(index<0)break;editorFindState.matches.push(index);cursor=index+Math.max(needle.length,1);if(editorFindState.matches.length>=10000)break;}$("#editor-find-count").textContent=editorFindState.matches.length?`0 / ${editorFindState.matches.length}`:"0 / 0";if(selectFirst&&editorFindState.matches.length)selectEditorFindMatch(1);}
function selectEditorFindMatch(direction=1){if($("#editor-find-input").value!==editorFindState.query)collectEditorFindMatches(false);const matches=editorFindState.matches;if(!matches.length)return;if(editorFindState.index<0)editorFindState.index=direction<0?matches.length-1:0;else editorFindState.index=(editorFindState.index+direction+matches.length)%matches.length;const start=matches[editorFindState.index],end=start+editorFindState.query.length,editor=$("#editor-content");editor.focus({preventScroll:true});editor.setSelectionRange(start,end);const line=editor.value.slice(0,start).split("\n").length,lineHeight=parseFloat(getComputedStyle(editor).lineHeight)||20;editor.scrollTop=Math.max(0,(line-4)*lineHeight);$("#editor-line-numbers").scrollTop=editor.scrollTop;$("#editor-find-count").textContent=`${editorFindState.index+1} / ${matches.length}`;updateEditorCursorStatus();}
function openEditorFind(){const panel=$("#editor-find-panel"),input=$("#editor-find-input"),editor=$("#editor-content");panel.hidden=false;if(!input.value&&editor.selectionStart!==editor.selectionEnd)input.value=editor.value.slice(editor.selectionStart,editor.selectionEnd).replace(/\n/g," ");collectEditorFindMatches(Boolean(input.value));input.focus();input.select();}
function closeEditorFind(){$("#editor-find-panel").hidden=true;$("#editor-content").focus({preventScroll:true});}
function toggleEditorReplace(){const row=$("#editor-replace-row"),expand=$("#editor-find-expand"),open=row.hidden;row.hidden=!open;expand.setAttribute("aria-expanded",open?"true":"false");expand.textContent=open?"⌃":"⌄";if(open)$("#editor-replace-input").focus();}
function replaceEditorCurrent(){const query=$("#editor-find-input").value;if(!query||!editorFindState.matches.length)return;if(editorFindState.index<0)selectEditorFindMatch(1);const editor=$("#editor-content"),start=editorFindState.matches[editorFindState.index],end=start+query.length,replacement=$("#editor-replace-input").value;editor.setRangeText(replacement,start,end,"end");editor.dispatchEvent(new Event("input",{bubbles:true}));collectEditorFindMatches(true);}
function replaceEditorAll(){const query=$("#editor-find-input").value;if(!query)return;collectEditorFindMatches(false);if(!editorFindState.matches.length)return;const replacement=$("#editor-replace-input").value,editor=$("#editor-content");let value=editor.value;for(let index=editorFindState.matches.length-1;index>=0;index--){const start=editorFindState.matches[index];value=value.slice(0,start)+replacement+value.slice(start+query.length);}editor.value=value;editor.dispatchEvent(new Event("input",{bubbles:true}));collectEditorFindMatches(true);}
function toggleEditorMaximize(){const dialog=$("#editor-dialog"),maximized=dialog.classList.toggle("editor-maximized"),button=$("#editor-maximize-button");button.setAttribute("aria-label",maximized?"Restore editor":"Maximize editor");button.title=maximized?"Restore":"Maximize";requestAnimationFrame(()=>{$("#editor-content").focus({preventScroll:true});});}
async function closeEditorTab(path){snapshotActiveEditor();const tab=state.editorTabs.find((item)=>item.path===path);if(!tab)return;if(tab.content!==tab.savedContent){const ok=await showPanelConfirmation({title:"Close unsaved file",message:`Close ${tab.name} without saving your changes?`,confirmLabel:"Close",danger:true});if(!ok)return;}const index=state.editorTabs.indexOf(tab),wasActive=state.activeEditorPath===path;state.editorTabs.splice(index,1);if(!state.editorTabs.length){state.activeEditorPath="";state.editorPath="";state.editorHash="";closeDialog($("#editor-dialog"));renderEditorTabs();return;}if(wasActive){const next=state.editorTabs[Math.min(index,state.editorTabs.length-1)];activateEditorTab(next.path);}else renderEditorTabs();}
function activateEditorTab(path){snapshotActiveEditor();const tab=state.editorTabs.find((item)=>item.path===path);if(!tab)return;state.activeEditorPath=tab.path;state.editorPath=tab.path;state.editorHash=tab.hash;$("#editor-path").textContent=tab.path;$("#editor-name").textContent=tab.name;$("#editor-content").value=tab.content;resetEditorFind();renderEditorTabs();updateEditorLineNumbers();updateEditorCursorStatus();clearError("#editor-error");$("#editor-content").focus({preventScroll:true});}
async function openEditor(path){clearError("#file-error");try{let tab=state.editorTabs.find((item)=>item.path===path);if(!tab){const data=await request(`api/v1/files/text?path=${encodeURIComponent(path)}`);tab={path:data.path,name:data.name||data.path.split("/").filter(Boolean).pop()||"Text file",hash:data.sha256,content:data.content,savedContent:data.content};state.editorTabs.push(tab);}if(!$("#editor-dialog").open){openDialog("#editor-dialog");if(!state.editorTreeLoaded)loadEditorTreeRoot();}activateEditorTab(tab.path);}catch(error){showError("#file-error",error.message);}}
function editorTreeLabel(entry){const icon=entry.kind==="directory"?"▸":(entry.editable?"▤":"·");return `${icon} ${entry.name}`;}
async function loadEditorTreeRoot(){const host=$("#editor-tree-content");host.innerHTML='<div class="editor-tree-loading">Loading files…</div>';try{const data=await request("api/v1/files?path=%2F");host.replaceChildren();renderEditorTreeEntries(host,data.entries||[],0);state.editorTreeLoaded=true;}catch(error){host.textContent=error.message;}}
function renderEditorTreeEntries(host,entries,depth){entries.forEach((entry)=>{const wrap=document.createElement("div");wrap.className="editor-tree-node";const button=document.createElement("button");button.type="button";button.className="editor-tree-row";button.style.paddingLeft=`${.55+depth*.8}rem`;button.textContent=editorTreeLabel(entry);button.title=entry.path;const children=document.createElement("div");children.className="editor-tree-children";children.hidden=true;if(entry.kind==="directory"){button.addEventListener("click",async()=>{if(children.dataset.loaded!=="true"){button.disabled=true;try{const data=await request(`api/v1/files?path=${encodeURIComponent(entry.path)}`);renderEditorTreeEntries(children,data.entries||[],depth+1);children.dataset.loaded="true";}finally{button.disabled=false;}}children.hidden=!children.hidden;button.textContent=`${children.hidden?"▸":"▾"} ${entry.name}`;});}else if(entry.editable){button.classList.add("editable");button.addEventListener("click",()=>openEditor(entry.path));}else{button.classList.add("readonly");button.disabled=true;}wrap.append(button,children);host.append(wrap);});}
'''
js = sub_once(js, r'const editorFindState=.*?\nfunction openRename\(entry\)', new_editor_functions + '\nfunction openRename(entry)', "editor function workspace")

# Replace old editor input/save wiring.
js = sub_once(
    js,
    r'\$\("#editor-content"\)\.addEventListener\("input".*?\n\$\("#editor-form"\)\.addEventListener\("submit", async \(event\) => \{.*?\n\}\);',
    r'''$("#editor-content").addEventListener("input",()=>{const tab=activeEditorTab();if(tab)tab.content=$("#editor-content").value;updateEditorLineNumbers();updateEditorCursorStatus();if(!$("#editor-find-panel").hidden)collectEditorFindMatches(false);});
$("#editor-content").addEventListener("scroll",updateEditorLineNumbers);
$("#editor-content").addEventListener("click",updateEditorCursorStatus);
$("#editor-content").addEventListener("keyup",updateEditorCursorStatus);
$("#editor-content").addEventListener("keydown",(event)=>{if(event.key==="Tab"){insertEditorTab(event);return;}if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="s"){event.preventDefault();event.stopPropagation();$("#editor-form").requestSubmit();}});
$("#editor-form").addEventListener("submit", async (event) => {
event.preventDefault(); const form=event.currentTarget,tab=activeEditorTab(); if(!tab)return; snapshotActiveEditor(); clearError("#editor-error"); setBusy(form,true);
try { const data=await request("api/v1/files/text",{method:"PUT",body:JSON.stringify({path:tab.path,content:tab.content,expected_sha256:tab.hash})}); tab.hash=data.sha256;tab.savedContent=tab.content;state.editorHash=data.sha256;updateEditorCursorStatus();showToast("File saved successfully.");await loadFiles(state.currentPath); }
catch(error){showError("#editor-error",error.message);} finally{setBusy(form,false);}
});''',
    "editor save wiring",
)

# Replace V1.5.6 tail wiring with V1.5.7 capture + Find/Replace controls.
new_tail = r'''/* V1.5.7 editor workspace keyboard + Find/Replace wiring */
$("#editor-find-button").addEventListener("click",openEditorFind);
$("#editor-maximize-button").addEventListener("click",toggleEditorMaximize);
$("#editor-find-close").addEventListener("click",closeEditorFind);
$("#editor-find-expand").addEventListener("click",toggleEditorReplace);
$("#editor-find-next").addEventListener("click",()=>selectEditorFindMatch(1));
$("#editor-find-previous").addEventListener("click",()=>selectEditorFindMatch(-1));
$("#editor-replace-one").addEventListener("click",replaceEditorCurrent);
$("#editor-replace-all").addEventListener("click",replaceEditorAll);
$("#editor-find-input").addEventListener("input",()=>collectEditorFindMatches(true));
$("#editor-find-input").addEventListener("keydown",(event)=>{if(event.key==="Enter"){event.preventDefault();selectEditorFindMatch(event.shiftKey?-1:1);}else if(event.key==="Escape"){event.preventDefault();closeEditorFind();}});
function captureEditorShortcut(event){const dialog=$("#editor-dialog");if(!dialog||!dialog.open)return;if((event.ctrlKey||event.metaKey)&&(event.code==="KeyF"||event.key.toLowerCase()==="f")){event.preventDefault();event.stopImmediatePropagation();openEditorFind();return;}if(event.key==="F3"){event.preventDefault();event.stopImmediatePropagation();selectEditorFindMatch(event.shiftKey?-1:1);}}
window.addEventListener("keydown",captureEditorShortcut,true);
document.addEventListener("keydown",captureEditorShortcut,true);
'''
js = sub_once(js, r'/\* V1\.5\.6 editor keyboard \+ toolbar wiring \*/.*\Z', new_tail, "editor tail wiring")
write(js_path, js)

# ---------------------------------------------------------------------------
# CSS for setup, Remember me, editor tree/tabs/side Find panel.
# ---------------------------------------------------------------------------
css_path = "internal/web/static/app.css"
css = read(css_path)
css += r'''

/* V1.5.7 first-run account and aaPanel-inspired editor workspace */
.setup-copy { margin: -.1rem 0 .35rem; line-height: 1.55; }
.setup-username-row { display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:.72rem .82rem; border:1px solid var(--line); border-radius:10px; background:#f7faff; color:var(--muted); font-size:.68rem; }
.setup-username-row strong { color:var(--ink); font-size:.75rem; }
.password-policy { margin:-.15rem 0 .15rem; color:var(--muted); font-size:.6rem; line-height:1.5; }
.remember-row { display:flex !important; flex-direction:row !important; align-items:center; gap:.5rem !important; width:max-content; color:#55779c; font-size:.68rem; font-weight:750; cursor:pointer; }
.remember-row input { width:16px; height:16px; margin:0; accent-color:#2479ee; }
.editor-card { height:min(90vh,900px); }
.editor-header-primary { flex:0 0 auto; }
.editor-header-secondary { min-height:50px; padding:.4rem .7rem; border-top:0; background:#f7fbff; }
.editor-tabs { min-width:0; flex:1 1 auto; display:flex; align-items:center; gap:.28rem; overflow-x:auto; scrollbar-width:thin; }
.editor-tab { flex:0 0 auto; max-width:230px; display:flex; align-items:center; gap:.5rem; min-height:34px; padding:.4rem .5rem .4rem .7rem; border:1px solid transparent; border-radius:8px; color:#5b7696; background:transparent; font-size:.63rem; font-weight:780; }
.editor-tab > span:first-child { max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.editor-tab:hover { background:#fff; border-color:var(--line); }
.editor-tab.active { color:var(--blue-deep); background:#fff; border-color:var(--line-strong); box-shadow:0 4px 12px rgba(48,116,238,.08); }
.editor-tab-close { display:grid; place-items:center; width:18px; height:18px; border-radius:5px; color:#87a0bb; font-size:.85rem; }
.editor-tab-close:hover { color:#d63548; background:#fff0f2; }
.editor-secondary-tools { flex:0 0 auto; display:flex; align-items:center; }
.editor-find-trigger { width:auto; min-width:78px; padding:0 .65rem; display:flex; grid-template-columns:none; gap:.4rem; }
.editor-find-trigger span { font-size:.61rem; font-weight:800; }
.editor-layout { flex:1 1 auto; min-height:0; display:grid; grid-template-columns:220px minmax(0,1fr); background:#fff; }
.editor-tree { min-width:0; display:flex; flex-direction:column; border-right:1px solid var(--line); background:#f8fbff; }
.editor-tree-head { flex:0 0 auto; display:flex; align-items:center; justify-content:space-between; gap:.5rem; min-height:42px; padding:.55rem .7rem; border-bottom:1px solid var(--line); color:#45698f; font-size:.64rem; }
.editor-tree-head span { color:#8aa1ba; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
.editor-tree-content { flex:1 1 auto; min-height:0; overflow:auto; padding:.35rem 0; }
.editor-tree-loading { padding:.7rem; color:var(--muted); font-size:.62rem; }
.editor-tree-node { min-width:max-content; }
.editor-tree-row { width:100%; min-width:190px; display:block; padding-top:.38rem; padding-bottom:.38rem; padding-right:.6rem; border:0; border-radius:0; background:transparent; color:#587694; text-align:left; white-space:nowrap; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.61rem; }
.editor-tree-row:hover:not(:disabled) { color:var(--blue-deep); background:rgba(77,153,244,.1); }
.editor-tree-row.editable { color:#294f79; }
.editor-tree-row.readonly { opacity:.62; cursor:default; }
.editor-tree-children[hidden] { display:none !important; }
.editor-main { position:relative; min-width:0; min-height:0; overflow:hidden; }
.editor-main .editor-workspace { height:100%; }
.editor-find-panel { position:absolute; z-index:8; top:.7rem; right:.85rem; width:min(430px,calc(100% - 1.7rem)); padding:.5rem; border:1px solid var(--line-strong); border-radius:10px; background:rgba(255,255,255,.985); box-shadow:0 14px 38px rgba(20,55,97,.2); }
.editor-find-panel[hidden] { display:none !important; }
.editor-find-row { display:grid; grid-template-columns:minmax(100px,1fr) 30px auto 30px 30px 30px; align-items:center; gap:.28rem; }
.editor-find-row input,.editor-replace-row input { min-width:0; height:34px; padding:.4rem .55rem; border:1px solid var(--line-strong); border-radius:7px; background:#fff; color:var(--ink); font:inherit; font-size:.64rem; }
.editor-find-row input:focus,.editor-replace-row input:focus { outline:2px solid rgba(47,137,246,.14); border-color:#3b8ef5; }
.editor-find-expand,.editor-find-nav,.editor-find-close { width:30px; height:30px; display:grid; place-items:center; border:1px solid var(--line); border-radius:7px; color:#5d7d9e; background:#fff; font-weight:850; }
.editor-find-count { min-width:48px; color:#7189a4; text-align:center; font-size:.58rem; font-weight:800; font-variant-numeric:tabular-nums; }
.editor-replace-row { display:grid; grid-template-columns:minmax(100px,1fr) auto auto; gap:.35rem; margin-top:.4rem; padding-top:.4rem; border-top:1px solid var(--line); }
.editor-replace-row[hidden] { display:none !important; }
.editor-replace-row button { min-height:34px; padding:.4rem .55rem; border:1px solid var(--line); border-radius:7px; color:#37648f; background:#f8fbff; font-size:.58rem; font-weight:800; }
.editor-replace-row button:hover { color:var(--blue-deep); border-color:var(--line-strong); background:rgba(99,204,248,.12); }
.editor-maximized .editor-layout { grid-template-columns:240px minmax(0,1fr); }
@media (max-width:800px) {
  .editor-layout { grid-template-columns:150px minmax(0,1fr); }
  .editor-tree-row { min-width:140px; }
  .editor-shortcuts { display:none; }
  .editor-find-panel { top:.45rem; right:.45rem; width:calc(100% - .9rem); }
}
'''
write(css_path, css)

# ---------------------------------------------------------------------------
# HTTP integration tests: first-run setup + Remember me assets.
# ---------------------------------------------------------------------------
app_test_path = "internal/httpapi/app_test.go"
app_test = read(app_test_path)
app_test = replace_once(app_test, '`Version 1.5.6`', '`Version 1.5.7`', "http test version")
app_test = replace_once(
    app_test,
    '`data-password-toggle`, `minlength="8"`, `maxlength="16"`, `Sign in`, `data-view="files"`, `id="file-path-form"`, `Version 1.5.7`',
    '`data-password-toggle`, `minlength="8"`, `maxlength="16"`, `Sign in`, `Remember me`, `id="setup-form"`, `data-view="files"`, `id="file-path-form"`, `Version 1.5.7`',
    "auth asset requirements",
)
app_test = sub_once(
    app_test,
    r'response, err = client\.Get\(panelRoot \+ "/api/v1/bootstrap/status"\).*?if response\.StatusCode != http\.StatusNotFound \{.*?\n\t\}',
    r'''response, err = client.Get(panelRoot + "/api/v1/auth/setup/status")
	if err != nil { t.Fatal(err) }
	var setupStatus map[string]any
	if err := json.NewDecoder(response.Body).Decode(&setupStatus); err != nil { t.Fatal(err) }
	response.Body.Close()
	if response.StatusCode != http.StatusOK || setupStatus["required"] != false { t.Fatalf("unexpected setup status: code=%d body=%v", response.StatusCode, setupStatus) }''',
    "replace removed bootstrap assertion",
)
fresh_setup_test = r'''
func TestFreshOwnerPasswordSetupFlow(t *testing.T) {
	dir := t.TempDir()
	cfg := testConfig(dir)
	if err := cryptoutil.CreateKey(cfg.Security.EncryptionKeyFile); err != nil { t.Fatal(err) }
	data, err := store.Open(cfg.Storage.Database); if err != nil { t.Fatal(err) }; defer data.Close()
	created, err := data.InitializeOwner(t.Context(), store.User{ID:"fresh-owner",Username:"hyzorax",PasswordHash:store.PendingOwnerPasswordHash}, time.Now())
	if err != nil || !created { t.Fatalf("initialize pending owner: created=%t err=%v",created,err) }
	box, err := cryptoutil.LoadBox(cfg.Security.EncryptionKeyFile); if err != nil { t.Fatal(err) }
	app, err := New(cfg,data,box,nil,"test"); if err != nil { t.Fatal(err) }
	server := httptest.NewServer(app.Handler()); defer server.Close()
	panelRoot := server.URL + "/12ab56cd"
	client := &http.Client{}
	status := getJSON(t,client,panelRoot+"/api/v1/auth/setup/status",http.StatusOK)
	if status["required"] != true || status["username"] != "hyzorax" { t.Fatalf("unexpected pending setup status: %v",status) }
	postJSON(t,client,panelRoot+"/api/v1/auth/setup",map[string]any{"password":"weakpass","confirm_password":"weakpass"},"",http.StatusBadRequest)
	postJSON(t,client,panelRoot+"/api/v1/auth/setup",map[string]any{"password":"Strong-8Pass!","confirm_password":"Strong-8Pass!"},"",http.StatusOK)
	status = getJSON(t,client,panelRoot+"/api/v1/auth/setup/status",http.StatusOK)
	if status["required"] != false { t.Fatalf("setup did not close permanently: %v",status) }
	postJSON(t,client,panelRoot+"/api/v1/auth/setup",map[string]any{"password":"Other-8Pass!","confirm_password":"Other-8Pass!"},"",http.StatusConflict)
	postJSON(t,client,panelRoot+"/api/v1/auth/login",map[string]any{"username":"hyzorax","password":"Strong-8Pass!","remember":true},"",http.StatusOK)
}

'''
app_test = replace_once(app_test, "func TestRejectsTrailingJSONAndCrossSiteRequests", fresh_setup_test + "func TestRejectsTrailingJSONAndCrossSiteRequests", "fresh setup integration test")
write(app_test_path, app_test)

# ---------------------------------------------------------------------------
# Colored dynamic SSH dashboard. Values are detected at login; no password.
# ---------------------------------------------------------------------------
dashboard = r'''#!/usr/bin/env bash
set -u
BLUE='\033[1;34m'; CYAN='\033[1;36m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; WHITE='\033[1;37m'; DIM='\033[0;37m'; RESET='\033[0m'

human_bytes() { awk -v n="$1" 'BEGIN{split("B KB MB GB TB",u," ");i=1;while(n>=1024&&i<5){n/=1024;i++}printf(i==1?"%.0f%s":"%.1f%s",n,u[i])}'; }
format_uptime() { local s="$1" d h m; d=$((s/86400)); h=$(((s%86400)/3600)); m=$(((s%3600)/60)); if ((d>0)); then printf '%dd %dh' "$d" "$h"; elif ((h>0)); then printf '%dh %dm' "$h" "$m"; else printf '%dm' "$m"; fi; }

panel_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++)if($i=="src"){print $(i+1);exit}}' || true)"
[[ -n "$panel_ip" ]] || panel_ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
[[ -n "$panel_ip" ]] || panel_ip="unknown"
panel_port="$(sed -nE 's/^[[:space:]]*listen[[:space:]]*=[[:space:]]*"[^"]*:([0-9]+)".*/\1/p' /etc/hyzorax-control/config.toml 2>/dev/null | head -n1)"
[[ -n "$panel_port" ]] || panel_port="9443"
entrance="$(tr -d '[:space:]' </etc/hyzorax-control/entrance.code 2>/dev/null || true)"
username="$(/usr/local/bin/hyzorax-control -config /etc/hyzorax-control/config.toml -owner-username 2>/dev/null | tail -n1 || true)"
[[ -n "$username" ]] || username="hyzorax"
panel_url="https://${panel_ip}:${panel_port}/${entrance}/"

vendor="$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null || true)"
product="$(cat /sys/class/dmi/id/product_name 2>/dev/null || true)"
provider="${vendor} ${product}"
provider_lc="${provider,,}"
case "$provider_lc" in
  *contabo*) server_name="Contabo VPS" ;;
  *hetzner*) server_name="Hetzner VPS" ;;
  *digitalocean*) server_name="DigitalOcean VPS" ;;
  *amazon*|*ec2*) server_name="Amazon EC2" ;;
  *google*) server_name="Google Cloud" ;;
  *microsoft*|*azure*) server_name="Microsoft Azure" ;;
  *) server_name="$(echo "$provider" | xargs 2>/dev/null || true)"; [[ -n "$server_name" ]] || server_name="$(hostname)" ;;
esac

read -r disk_total disk_used disk_pct < <(df -P -B1 / 2>/dev/null | awk 'NR==2{gsub(/%/,"",$5);print $2,$3,$5}')
disk_total="${disk_total:-0}"; disk_pct="${disk_pct:-0}"
mem_total_kb="$(awk '/^MemTotal:/{print $2}' /proc/meminfo 2>/dev/null)"; mem_avail_kb="$(awk '/^MemAvailable:/{print $2}' /proc/meminfo 2>/dev/null)"
mem_total_kb="${mem_total_kb:-0}"; mem_avail_kb="${mem_avail_kb:-0}"; mem_used_kb=$((mem_total_kb-mem_avail_kb)); ((mem_used_kb<0)) && mem_used_kb=0
if ((mem_total_kb>0)); then mem_pct=$((mem_used_kb*100/mem_total_kb)); else mem_pct=0; fi
uptime_seconds="$(awk '{printf "%d",$1}' /proc/uptime 2>/dev/null || echo 0)"
if [[ -e /var/run/reboot-required ]]; then reboot_text="Required"; reboot_color="$YELLOW"; else reboot_text="Not required"; reboot_color="$GREEN"; fi

printf '\n'
printf "${BLUE}██╗  ██╗${CYAN}██╗   ██╗${BLUE}███████╗${CYAN} ██████╗ ${BLUE}██████╗  ${CYAN}█████╗ ${BLUE}██╗  ██╗${RESET}\n"
printf "${BLUE}██║  ██║${CYAN}╚██╗ ██╔╝${BLUE}╚══███╔╝${CYAN}██╔═══██╗${BLUE}██╔══██╗${CYAN}██╔══██╗${BLUE}╚██╗██╔╝${RESET}\n"
printf "${CYAN}███████║${BLUE} ╚████╔╝ ${CYAN}  ███╔╝ ${BLUE}██║   ██║${CYAN}██████╔╝${BLUE}███████║${CYAN} ╚███╔╝ ${RESET}\n"
printf "${GREEN}██╔══██║  ╚██╔╝   ███╔╝  ██║   ██║██╔══██╗██╔══██║ ██╔██╗ ${RESET}\n"
printf "${GREEN}██║  ██║   ██║   ███████╗╚██████╔╝██║  ██║██║  ██║██╔╝ ██╗${RESET}\n"
printf "${GREEN}╚═╝  ╚═╝   ╚═╝   ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝${RESET}\n"
printf "${DIM}────────────────────────────────────────────────────────────────────────${RESET}\n"
printf "${YELLOW}Username:${RESET}   ${WHITE}%s${RESET}\n" "$username"
printf "${YELLOW}Panel URL:${RESET}  ${CYAN}%s${RESET}\n" "$panel_url"
printf '\n'
printf "${YELLOW}Server:${RESET}     ${WHITE}%s${RESET}\n" "$server_name"
printf "${CYAN}Disk:${RESET}       ${WHITE}%s%% of %s${RESET}\n" "$disk_pct" "$(human_bytes "$disk_total")"
printf "${CYAN}Memory:${RESET}     ${WHITE}%s%% of %s${RESET}\n" "$mem_pct" "$(human_bytes $((mem_total_kb*1024)))"
printf "${CYAN}Uptime:${RESET}     ${WHITE}%s${RESET}\n" "$(format_uptime "$uptime_seconds")"
printf "${CYAN}IPv4:${RESET}       ${WHITE}%s${RESET}\n" "$panel_ip"
printf "${CYAN}Reboot:${RESET}     ${reboot_color}%s${RESET}\n" "$reboot_text"
printf '\n'
printf "${DIM}Run:${RESET}        ${GREEN}hz${RESET}\n"
printf "${DIM}────────────────────────────────────────────────────────────────────────${RESET}\n"
'''
write("packaging/hyzorax-dashboard", dashboard)

# Make release bundle include dashboard.
makefile_path = "Makefile"
makefile = read(makefile_path)
makefile = replace_once(makefile, 'packaging/hyzorax-control-updater packaging/hz $(BUILD_DIR)/', 'packaging/hyzorax-control-updater packaging/hyzorax-dashboard packaging/hz $(BUILD_DIR)/', "Makefile dashboard copy")
makefile = replace_once(makefile, '$(BUILD_DIR)/hyzorax-control-updater $(BUILD_DIR)/hz', '$(BUILD_DIR)/hyzorax-control-updater $(BUILD_DIR)/hyzorax-dashboard $(BUILD_DIR)/hz', "Makefile dashboard chmod")
makefile = replace_once(makefile, 'hyzorax-control-updater hz > SHA256SUMS', 'hyzorax-control-updater hyzorax-dashboard hz > SHA256SUMS', "Makefile dashboard checksum")
write(makefile_path, makefile)

# Bootstrap: no password cache/output; install colored MOTD and disable Ubuntu MOTD fragments.
bootstrap_path = "packaging/bootstrap.sh"
bootstrap = read(bootstrap_path)
bootstrap = sub_once(
    bootstrap,
    r'install_log="/var/log/hyzorax-control-install\.log"\ncredentials_cache=.*?exec > >\(/usr/bin/tee "\$\{install_log\}"\) 2>&1',
    'install_log="/var/log/hyzorax-control-install.log"\ninstall -o root -g root -m 0600 /dev/null "${install_log}"\nexec > >(/usr/bin/tee "${install_log}") 2>&1',
    "remove owner password cache bootstrap",
)
bootstrap = replace_once(bootstrap, '"${bundle_dir}/hyzorax-control-updater" "${bundle_dir}/hz"', '"${bundle_dir}/hyzorax-control-updater" "${bundle_dir}/hyzorax-dashboard" "${bundle_dir}/hz"', "dashboard required release file")
bootstrap = sub_once(
    bootstrap,
    r'owner_credentials="\$\(runuser -u hyzorax-control -- /usr/local/bin/hyzorax-control \\\n  -config /etc/hyzorax-control/config\.toml \\\n  -initialize-owner\)".*?rm -f -- /var/lib/hyzorax-control/bootstrap\.token',
    'owner_credentials="$(runuser -u hyzorax-control -- /usr/local/bin/hyzorax-control \\\n  -config /etc/hyzorax-control/config.toml \\\n  -initialize-owner)"\ncache_owner_username="$(sed -n \'s/^Initial Owner username:[[:space:]]*//p\' <<<"${owner_credentials}" | tail -n 1)"\nrm -f -- /etc/hyzorax-control/owner.credentials /var/lib/hyzorax-control/bootstrap.token',
    "pending owner bootstrap",
)
# Install dashboard immediately after hz installation, wherever the exact install line lives.
bootstrap, dashboard_install_count = re.subn(
    r'(install[^\n]*"?\$\{bundle_dir\}/hz"?[^\n]*/usr/local/bin/hz[^\n]*\n)',
    r'''\1install -o root -g root -m 0755 "${bundle_dir}/hyzorax-dashboard" /etc/update-motd.d/99-hyzorax-dashboard
for motd_script in /etc/update-motd.d/*; do
  [[ "${motd_script}" == "/etc/update-motd.d/99-hyzorax-dashboard" ]] && continue
  [[ -f "${motd_script}" ]] && chmod a-x "${motd_script}" || true
done
: > /etc/motd
rm -f -- /run/motd.dynamic /run/motd.dynamic.new 2>/dev/null || true
''',
    bootstrap,
    count=1,
)
if dashboard_install_count != 1:
    raise SystemExit(f"dashboard install marker: expected 1 match, got {dashboard_install_count}")
bootstrap = sub_once(
    bootstrap,
    r'final_username="\$\{cache_owner_username:-\}".*?printf \'Password:.*?\n',
    '''final_username="$(/usr/local/bin/hyzorax-control -config /etc/hyzorax-control/config.toml -owner-username 2>/dev/null | tail -n 1 || true)"
[[ -n "${final_username}" ]] || final_username="${cache_owner_username:-hyzorax}"

echo
echo "HYZoraX Control Panel installation is complete."
echo "Version: $(/usr/local/bin/hyzorax-control -version | awk '{print $2}')"
echo "Panel URL: ${panel_url}"
printf 'Username: %s\\n' "${final_username}"
echo "Open the Panel URL to set the administrator password on a fresh installation."
''',
    "installer final no password",
)
write(bootstrap_path, bootstrap)

# ---------------------------------------------------------------------------
# Installer Engine foundation: planning only, no execution/UI/hz menu.
# ---------------------------------------------------------------------------
installer_plan = r'''package installer

import (
	"errors"
	"fmt"
	"sort"
)

type Component struct {
	ID        string
	Name      string
	DependsOn []string
	Conflicts []string
}

type Step struct {
	ComponentID string
}

type Plan struct {
	Requested []string
	Steps     []Step
}

func BuildPlan(catalog map[string]Component, requested []string) (Plan, error) {
	if len(requested) == 0 {
		return Plan{}, errors.New("at least one component must be requested")
	}
	visiting := map[string]bool{}
	resolved := map[string]bool{}
	ordered := make([]string, 0, len(requested))
	var visit func(string) error
	visit = func(id string) error {
		component, ok := catalog[id]
		if !ok { return fmt.Errorf("unknown installer component %q", id) }
		if resolved[id] { return nil }
		if visiting[id] { return fmt.Errorf("installer dependency cycle includes %q", id) }
		visiting[id] = true
		deps := append([]string(nil), component.DependsOn...)
		sort.Strings(deps)
		for _, dependency := range deps { if err := visit(dependency); err != nil { return err } }
		visiting[id] = false
		resolved[id] = true
		ordered = append(ordered, id)
		return nil
	}
	for _, id := range requested { if err := visit(id); err != nil { return Plan{}, err } }
	for id := range resolved {
		component := catalog[id]
		for _, conflict := range component.Conflicts {
			if resolved[conflict] { return Plan{}, fmt.Errorf("installer components %q and %q conflict", id, conflict) }
		}
	}
	steps := make([]Step, 0, len(ordered))
	for _, id := range ordered { steps = append(steps, Step{ComponentID:id}) }
	return Plan{Requested:append([]string(nil),requested...),Steps:steps}, nil
}
'''
installer_test = r'''package installer

import "testing"

func TestBuildPlanResolvesDependencies(t *testing.T) {
	catalog := map[string]Component{
		"runtime":{ID:"runtime"},
		"web":{ID:"web",DependsOn:[]string{"runtime"}},
		"app":{ID:"app",DependsOn:[]string{"web"}},
	}
	plan, err := BuildPlan(catalog,[]string{"app"}); if err != nil { t.Fatal(err) }
	want := []string{"runtime","web","app"}; if len(plan.Steps)!=len(want){t.Fatalf("unexpected steps: %#v",plan.Steps)}
	for i,id := range want { if plan.Steps[i].ComponentID!=id { t.Fatalf("step %d=%q want %q",i,plan.Steps[i].ComponentID,id) } }
}
func TestBuildPlanRejectsConflictAndCycle(t *testing.T) {
	conflicts:=map[string]Component{"a":{ID:"a",Conflicts:[]string{"b"}},"b":{ID:"b"}}
	if _,err:=BuildPlan(conflicts,[]string{"a","b"});err==nil{t.Fatal("expected conflict")}
	cycle:=map[string]Component{"a":{ID:"a",DependsOn:[]string{"b"}},"b":{ID:"b",DependsOn:[]string{"a"}}}
	if _,err:=BuildPlan(cycle,[]string{"a"});err==nil{t.Fatal("expected cycle")}
}
'''
write("internal/installer/plan.go", installer_plan)
write("internal/installer/plan_test.go", installer_test)

print("Applied HYZoraX Control Panel V1.5.7 editor workspace + first-run dashboard + installer planning foundation")
