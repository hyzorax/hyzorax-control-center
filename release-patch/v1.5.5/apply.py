#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: apply.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()

def read(rel): return (root / rel).read_text(encoding="utf-8")
def write(rel, text): (root / rel).write_text(text, encoding="utf-8")
def replace_once(text, old, new, label):
    if old not in text: raise SystemExit(f"{label}: marker not found")
    return text.replace(old, new, 1)

# Version + helper protocol.
html = read("internal/web/static/index.html")
html = replace_once(html, "Version 1.5.4", "Version 1.5.5", "version")
protocol = read("internal/helper/protocol.go")
protocol = replace_once(protocol, "const ProtocolVersion = 9", "const ProtocolVersion = 10", "protocol")
write("internal/helper/protocol.go", protocol)

# Guarded metadata helper: regular files/directories only; no root, symlinks,
# special files or mount-boundary entries. Modes are limited to ordinary rwx
# bits (0000-0777); setuid/setgid/sticky are deliberately not exposed yet.
fs_path = "internal/helper/filesystem_linux.go"
fs = read(fs_path)
params_marker = '''type filesystemMoveParams struct {
\tDestinationDirectory string `json:"destination_directory"`
\tName                 string `json:"name"`
}
'''
metadata_params = '''

type filesystemMetadataParams struct {
\tPermissions string `json:"permissions"`
\tOwner       string `json:"owner"`
\tGroup       string `json:"group"`
}
'''
if "type filesystemMetadataParams struct" not in fs:
    fs = replace_once(fs, params_marker, params_marker + metadata_params, "metadata params")

metadata_impl = r'''
func resolveFilesystemUID(raw string) (int, *Error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return -1, nil
	}
	if numeric, err := strconv.ParseUint(raw, 10, 32); err == nil {
		return int(numeric), nil
	}
	account, err := user.Lookup(raw)
	if err != nil {
		return 0, &Error{Code: "invalid_owner", Message: "owner account does not exist"}
	}
	value, err := strconv.ParseUint(account.Uid, 10, 32)
	if err != nil {
		return 0, &Error{Code: "invalid_owner", Message: "owner account identifier is invalid"}
	}
	return int(value), nil
}

func resolveFilesystemGID(raw string) (int, *Error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return -1, nil
	}
	if numeric, err := strconv.ParseUint(raw, 10, 32); err == nil {
		return int(numeric), nil
	}
	group, err := user.LookupGroup(raw)
	if err != nil {
		return 0, &Error{Code: "invalid_group", Message: "group does not exist"}
	}
	value, err := strconv.ParseUint(group.Gid, 10, 32)
	if err != nil {
		return 0, &Error{Code: "invalid_group", Message: "group identifier is invalid"}
	}
	return int(value), nil
}

func filesystemUpdateMetadata(ctx context.Context, rawPath string, params filesystemMetadataParams) (map[string]any, *Error) {
	cleanPath, pathError := validateFilesystemPath(rawPath)
	if pathError != nil { return nil, pathError }
	if cleanPath == string(os.PathSeparator) {
		return nil, &Error{Code: "root_path_denied", Message: "filesystem root metadata cannot be changed through File Manager"}
	}
	permissionText := strings.TrimSpace(params.Permissions)
	if len(permissionText) == 4 && permissionText[0] == '0' { permissionText = permissionText[1:] }
	if len(permissionText) != 3 {
		return nil, &Error{Code: "invalid_permissions", Message: "permissions must be a three- or four-digit octal value such as 0644"}
	}
	permissionValue, err := strconv.ParseUint(permissionText, 8, 9)
	if err != nil || permissionValue > 0o777 {
		return nil, &Error{Code: "invalid_permissions", Message: "permissions must use ordinary rwx bits from 0000 through 0777"}
	}
	uid, ownerError := resolveFilesystemUID(params.Owner)
	if ownerError != nil { return nil, ownerError }
	gid, groupError := resolveFilesystemGID(params.Group)
	if groupError != nil { return nil, groupError }
	if err := ctx.Err(); err != nil { return nil, &Error{Code: "operation_timeout", Message: "filesystem request timed out"} }

	parentPath := filepath.Dir(cleanPath)
	name := filepath.Base(cleanPath)
	parent, openError := openFilesystemPath(parentPath, unix.O_RDONLY|unix.O_DIRECTORY)
	if openError != nil { return nil, filesystemError(openError, "metadata parent directory could not be opened") }
	defer parent.Close()
	parentStat, statError := filesystemFDStat(parent)
	if statError != nil { return nil, filesystemError(statError, "metadata parent directory could not be read") }
	source, operationError := inspectFilesystemCopySourceAt(int(parent.Fd()), name)
	if operationError != nil { return nil, operationError }
	if uint64(source.Stat.Dev) != uint64(parentStat.Dev) {
		return nil, &Error{Code: "mount_boundary_denied", Message: "mount-boundary metadata cannot be changed through File Manager"}
	}
	file, operationError := openFilesystemCopySourceAt(int(parent.Fd()), name, source.Stat, source.Kind == "directory")
	if operationError != nil { return nil, operationError }
	defer file.Close()

	originalUID, originalGID := int(source.Stat.Uid), int(source.Stat.Gid)
	originalMode := source.Info.Mode().Perm()
	if uid < 0 { uid = originalUID }
	if gid < 0 { gid = originalGID }
	changedOwner := uid != originalUID || gid != originalGID
	changedMode := os.FileMode(permissionValue) != originalMode
	if changedOwner {
		if err := file.Chown(uid, gid); err != nil { return nil, filesystemError(err, "file ownership could not be changed") }
	}
	if changedMode {
		if err := file.Chmod(os.FileMode(permissionValue)); err != nil {
			if changedOwner { _ = file.Chown(originalUID, originalGID) }
			return nil, filesystemError(err, "file permissions could not be changed")
		}
	}
	if err := file.Sync(); err != nil {
		if changedOwner { _ = file.Chown(originalUID, originalGID) }
		if changedMode { _ = file.Chmod(originalMode) }
		_ = file.Sync()
		return nil, filesystemError(err, "file metadata could not be synchronized")
	}
	updated, err := file.Stat()
	if err != nil { return nil, filesystemError(err, "updated file metadata could not be read") }
	stat, ok := updated.Sys().(*syscall.Stat_t)
	if !ok { return nil, &Error{Code: "operation_failed", Message: "updated file metadata is unavailable"} }
	ownerCache := map[uint32]string{}
	groupCache := map[uint32]string{}
	return map[string]any{
		"path": cleanPath, "name": name, "kind": source.Kind,
		"permissions": fmt.Sprintf("%04o", updated.Mode().Perm()),
		"uid": stat.Uid, "gid": stat.Gid,
		"owner": lookupOwner(stat.Uid, ownerCache), "group": lookupGroup(stat.Gid, groupCache),
	}, nil
}

'''
if "func filesystemUpdateMetadata(" not in fs:
    fs = replace_once(fs, "func filesystemFDStat(file *os.File) (*syscall.Stat_t, error) {", metadata_impl + "func filesystemFDStat(file *os.File) (*syscall.Stat_t, error) {", "metadata implementation")
write(fs_path, fs)

server_path = "internal/helper/server_linux.go"
server = read(server_path)
if 'case "filesystem.metadata.update":' not in server:
    metadata_case = r'''
	case "filesystem.metadata.update":
		var params filesystemMetadataParams
		if operationError := decodeFilesystemParams(request.Params, &params); operationError != nil {
			response.Error = operationError
			return response
		}
		data, operationError := filesystemUpdateMetadata(ctx, request.Target, params)
		if operationError != nil {
			response.Error = operationError
			return response
		}
		response.OK = true
		response.Data = data
		return response
'''
    server = replace_once(server, '\tcase "filesystem.text.read":', metadata_case + '\tcase "filesystem.text.read":', "metadata helper dispatch")
write(server_path, server)

# API route + audit.
app_path = "internal/httpapi/app.go"
app = read(app_path)
if 'POST /api/v1/files/metadata' not in app:
    app = replace_once(app, '\tmux.Handle("POST /api/v1/files/move", a.requireAuth(http.HandlerFunc(a.handleFileMove)))\n', '\tmux.Handle("POST /api/v1/files/move", a.requireAuth(http.HandlerFunc(a.handleFileMove)))\n\tmux.Handle("POST /api/v1/files/metadata", a.requireAuth(http.HandlerFunc(a.handleFileMetadata)))\n', "metadata route")
write(app_path, app)

handlers_path = "internal/httpapi/handlers.go"
handlers = read(handlers_path)
if "type metadataFileRequest struct" not in handlers:
    marker = '''type moveFileRequest struct {
\tPath                 string `json:"path"`
\tDestinationDirectory string `json:"destination_directory"`
\tName                 string `json:"name"`
}
'''
    request_type = '''

type metadataFileRequest struct {
\tPath        string `json:"path"`
\tPermissions string `json:"permissions"`
\tOwner       string `json:"owner"`
\tGroup       string `json:"group"`
}
'''
    handlers = replace_once(handlers, marker, marker + request_type, "metadata request")
if "func (a *App) handleFileMetadata" not in handlers:
    metadata_handler = r'''
func (a *App) handleFileMetadata(writer http.ResponseWriter, request *http.Request) {
	var input metadataFileRequest
	if !decodeJSON(writer, request, &input) { return }
	params, _ := json.Marshal(map[string]string{"permissions": input.Permissions, "owner": input.Owner, "group": input.Group})
	response, ok := a.callFilesystemHelperWithParams(writer, request, "filesystem.metadata.update", input.Path, params)
	if !ok { return }
	canonicalTarget, _ := response.Data["path"].(string)
	if canonicalTarget == "" { canonicalTarget = input.Path }
	a.audit(request, "filesystem.metadata.update", canonicalTarget, "success", map[string]any{
		"permissions": response.Data["permissions"], "owner": response.Data["owner"], "group": response.Data["group"],
		"uid": response.Data["uid"], "gid": response.Data["gid"], "kind": response.Data["kind"],
	})
	writeJSON(writer, http.StatusOK, response.Data)
}

'''
    handlers = replace_once(handlers, "func (a *App) handleTextFileRead(writer http.ResponseWriter, request *http.Request) {", metadata_handler + "func (a *App) handleTextFileRead(writer http.ResponseWriter, request *http.Request) {", "metadata handler")
# Map metadata validation errors to HTTP 400 when the existing bad-request case is present.
for token in ("invalid_owner", "invalid_group", "invalid_permissions"):
    if token not in handlers:
        handlers = handlers.replace('"preview_unsupported":', f'"preview_unsupported", "{token}":', 1)
write(handlers_path, handlers)

# Properties dialog + toast host.
properties_dialog = r'''<dialog id="metadata-dialog" class="modal operation-modal metadata-modal">
      <form id="metadata-form" class="modal-card operation-card metadata-card">
        <div class="operation-heading"><div><h3>Properties</h3><p id="metadata-path" class="metadata-path"></p></div><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        <div class="metadata-owner-grid"><label>Owner<input id="metadata-owner" maxlength="64" autocomplete="off" required></label><label>Group<input id="metadata-group" maxlength="64" autocomplete="off" required></label></div>
        <div class="metadata-permission-heading"><strong>Permissions</strong><label>Octal<input id="metadata-permissions" inputmode="numeric" maxlength="4" pattern="0?[0-7]{3}" required></label></div>
        <div class="permission-grid" aria-label="Permission bits">
          <span></span><strong>Read</strong><strong>Write</strong><strong>Execute</strong>
          <strong>Owner</strong><label><input type="checkbox" data-permission-bit="400"></label><label><input type="checkbox" data-permission-bit="200"></label><label><input type="checkbox" data-permission-bit="100"></label>
          <strong>Group</strong><label><input type="checkbox" data-permission-bit="040"></label><label><input type="checkbox" data-permission-bit="020"></label><label><input type="checkbox" data-permission-bit="010"></label>
          <strong>Others</strong><label><input type="checkbox" data-permission-bit="004"></label><label><input type="checkbox" data-permission-bit="002"></label><label><input type="checkbox" data-permission-bit="001"></label>
        </div>
        <p class="operation-hint">Regular files and folders only. Symlinks, special files, mount boundaries and the filesystem root are blocked.</p>
        <div id="metadata-error" class="alert" role="alert" hidden></div>
        <div class="modal-actions"><button type="button" class="ghost compact" data-close-dialog>Cancel</button><button type="submit" class="primary compact-primary">Apply</button></div>
      </form>
    </dialog>'''
if 'id="metadata-dialog"' not in html:
    html = replace_once(html, '    <dialog id="confirmation-dialog"', properties_dialog + '\n\n    <dialog id="confirmation-dialog"', "properties dialog")
if 'id="toast-host"' not in html:
    html = html.replace('</body>', '  <div id="toast-host" class="toast-host" aria-live="polite" aria-atomic="true"></div>\n</body>', 1)
write("internal/web/static/index.html", html)

# File Manager UI behavior.
js_path = "internal/web/static/app.js"
js = read(js_path)
# State slot.
if 'metadataEntry: null' not in js:
    js = js.replace('destinationPickerPath: "/",', 'destinationPickerPath: "/",\nmetadataEntry: null,', 1)
# Menu icon + item.
js = js.replace('delete: "⌫" };', 'delete: "⌫", permissions: "⚙" };', 1)
menu_marker = 'if (entry.movable) appendFileAction(menu, "move", "Move", () => openMove(entry), "move-link");'
if 'openMetadata(entry)' not in js:
    js = replace_once(js, menu_marker, menu_marker + '\nif ((entry.kind === "file" || entry.kind === "directory") && !entry.mount_boundary) appendFileAction(menu, "permissions", "Properties", () => openMetadata(entry), "metadata-link");', "properties menu action")

metadata_js = r'''
function normalizedPermissionValue(value) {
const text=String(value||"").trim().replace(/^0(?=[0-7]{3}$)/,"");
return /^[0-7]{3}$/.test(text)?text:null;
}
function syncPermissionChecksFromOctal() {
const text=normalizedPermissionValue($("#metadata-permissions").value); if(!text)return;
const value=parseInt(text,8); document.querySelectorAll('[data-permission-bit]').forEach((box)=>{box.checked=(value & parseInt(box.dataset.permissionBit,8))!==0;});
}
function syncOctalFromPermissionChecks() {
let value=0; document.querySelectorAll('[data-permission-bit]').forEach((box)=>{if(box.checked)value|=parseInt(box.dataset.permissionBit,8);});
$("#metadata-permissions").value=`0${value.toString(8).padStart(3,"0")}`;
}
function openMetadata(entry) {
state.metadataEntry=entry; $("#metadata-path").textContent=entry.path; $("#metadata-owner").value=entry.owner||String(entry.uid??""); $("#metadata-group").value=entry.group||String(entry.gid??""); $("#metadata-permissions").value=entry.permissions||"0644"; syncPermissionChecksFromOctal(); clearError("#metadata-error"); openDialog("#metadata-dialog");
}
function showToast(message, kind="success") {
const host=$("#toast-host"); if(!host)return;
const toast=document.createElement("div"); toast.className=`panel-toast ${kind}`; const icon=document.createElement("span"); icon.className="panel-toast-icon"; icon.textContent=kind==="error"?"!":"✓"; const text=document.createElement("span"); text.textContent=message; toast.append(icon,text); host.append(toast); requestAnimationFrame(()=>toast.classList.add("visible")); window.setTimeout(()=>{toast.classList.remove("visible");window.setTimeout(()=>toast.remove(),220);},3200);
}
'''
if 'function openMetadata(entry)' not in js:
    js = replace_once(js, 'function openDelete(entry) {', metadata_js + 'function openDelete(entry) {', "metadata/toast helpers")

# Permission grid listeners + form.
listener_marker = '$("#recycle-bin-button").addEventListener'
if 'metadata-permissions").addEventListener' not in js and listener_marker in js:
    js = js.replace(listener_marker, '$("#metadata-permissions").addEventListener("input", syncPermissionChecksFromOctal);\ndocument.querySelectorAll("[data-permission-bit]").forEach((box)=>box.addEventListener("change", syncOctalFromPermissionChecks));\n' + listener_marker, 1)
metadata_form = r'''
$("#metadata-form").addEventListener("submit", async (event) => {
event.preventDefault(); const form=event.currentTarget; const entry=state.metadataEntry; if(!entry)return; clearError("#metadata-error"); setBusy(form,true);
try { const data=await request("api/v1/files/metadata",{method:"POST",body:JSON.stringify({path:entry.path,permissions:$("#metadata-permissions").value,owner:$("#metadata-owner").value.trim(),group:$("#metadata-group").value.trim()})}); closeDialog($("#metadata-dialog")); showToast(`Properties updated for ${data.name||entry.name}.`); await loadFiles(state.currentPath); }
catch(error){ showError("#metadata-error",error.message); }
finally{ setBusy(form,false); }
});
'''
if '$("#metadata-form").addEventListener' not in js:
    js = replace_once(js, '$("#rename-form").addEventListener("submit", async (event) => {', metadata_form + '$("#rename-form").addEventListener("submit", async (event) => {', "metadata form")

# Success notifications for existing file operations. These are intentionally
# lightweight and do not replace detailed modal errors.
notification_replacements = [
('closeDialog($("#rename-dialog"));\nawait loadFiles(state.currentPath);', 'closeDialog($("#rename-dialog"));\nshowToast("Item renamed successfully.");\nawait loadFiles(state.currentPath);'),
('closeDialog($("#copy-dialog"));\nawait loadFiles(state.currentPath);', 'closeDialog($("#copy-dialog"));\nshowToast("Copy completed successfully.");\nawait loadFiles(state.currentPath);'),
('closeDialog($("#move-dialog"));\nawait loadFiles(state.currentPath);', 'closeDialog($("#move-dialog"));\nshowToast("Move completed successfully.");\nawait loadFiles(state.currentPath);'),
('closeDialog($("#delete-dialog"));\nawait loadFiles(state.currentPath);', 'closeDialog($("#delete-dialog"));\nshowToast("Item moved to Recycle Bin.");\nawait loadFiles(state.currentPath);'),
('$("#upload-status-badge").textContent = "Uploaded";', '$("#upload-status-badge").textContent = "Uploaded";\nshowToast("Upload completed successfully.");'),
('$("#editor-status").textContent = "Saved";', '$("#editor-status").textContent = "Saved";\nshowToast("File saved successfully.");'),
]
for old,new in notification_replacements:
    if old in js and new not in js: js=js.replace(old,new,1)
# Native browser confirms must stay absent from this and future versions.
if "window.confirm(" in js: raise SystemExit("native browser confirmation regressed")
write(js_path, js)

css_path = "internal/web/static/app.css"
css = read(css_path)
if "/* V1.5.5 metadata + notifications */" not in css:
    css += r'''

/* V1.5.5 metadata + notifications */
.metadata-modal{width:min(94vw,520px)}.metadata-card{gap:13px}.metadata-path{max-width:410px;margin:.2rem 0 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font-size:11px}.metadata-owner-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.metadata-permission-heading{display:flex;align-items:end;justify-content:space-between;gap:14px}.metadata-permission-heading>label{width:112px}.permission-grid{display:grid;grid-template-columns:92px repeat(3,1fr);align-items:center;gap:1px;overflow:hidden;border:1px solid var(--line);border-radius:11px;background:var(--line)}.permission-grid>*{min-height:38px;display:grid;place-items:center;margin:0;padding:7px;background:#fbfdff}.permission-grid>strong{color:#486987;font-size:11px}.permission-grid label{cursor:pointer}.permission-grid input{width:17px;height:17px;accent-color:#1b72ea}.toast-host{position:fixed;z-index:200;right:22px;bottom:22px;display:grid;gap:8px;pointer-events:none}.panel-toast{min-width:250px;max-width:min(420px,calc(100vw - 32px));display:flex;align-items:center;gap:9px;padding:11px 13px;border:1px solid rgba(29,183,138,.24);border-radius:11px;background:rgba(255,255,255,.98);box-shadow:0 18px 48px rgba(16,42,77,.22);color:#244969;font-size:12px;font-weight:750;opacity:0;transform:translateY(10px);transition:.2s ease}.panel-toast.visible{opacity:1;transform:translateY(0)}.panel-toast-icon{width:24px;height:24px;display:grid;place-items:center;flex:0 0 auto;border-radius:999px;color:#087b5f;background:rgba(29,183,138,.12);font-weight:900}.panel-toast.error{border-color:rgba(227,61,69,.25)}.panel-toast.error .panel-toast-icon{color:#c92530;background:rgba(227,61,69,.10)}@media(max-width:680px){.metadata-owner-grid{grid-template-columns:1fr}.toast-host{left:12px;right:12px;bottom:12px}.panel-toast{max-width:none;width:100%}}
'''
write(css_path, css)

# Tests.
for rel in ("internal/web/assets_test.go", "internal/httpapi/app_test.go"):
    text=read(rel).replace("Version 1.5.4","Version 1.5.5")
    write(rel,text)
assets_path="internal/web/assets_test.go"; assets=read(assets_path)
if "TestFileManagerV155MetadataNotifications" not in assets:
    assets += r'''

func TestFileManagerV155MetadataNotifications(t *testing.T) {
	htmlBytes, err := Assets.ReadFile("static/index.html"); if err != nil { t.Fatal(err) }
	jsBytes, err := Assets.ReadFile("static/app.js"); if err != nil { t.Fatal(err) }
	cssBytes, err := Assets.ReadFile("static/app.css"); if err != nil { t.Fatal(err) }
	html, js, css := string(htmlBytes), string(jsBytes), string(cssBytes)
	for _, fragment := range []string{`id="metadata-dialog"`, `id="metadata-form"`, `id="toast-host"`, `data-permission-bit="400"`} { if !strings.Contains(html, fragment) { t.Fatalf("V1.5.5 UI missing %q", fragment) } }
	for _, fragment := range []string{`openMetadata`, `showToast`, `api/v1/files/metadata`, `Properties`} { if !strings.Contains(js, fragment) { t.Fatalf("V1.5.5 behavior missing %q", fragment) } }
	if strings.Contains(js, "window.confirm(") { t.Fatal("native browser confirmation must remain disabled") }
	for _, fragment := range []string{`.permission-grid`, `.panel-toast`, `.metadata-owner-grid`} { if !strings.Contains(css, fragment) { t.Fatalf("V1.5.5 styling missing %q", fragment) } }
}
'''
write(assets_path, assets)

helper_test_path="internal/helper/filesystem_linux_test.go"; helper_test=read(helper_test_path)
if "TestFilesystemUpdateMetadata" not in helper_test:
    helper_test += r'''

func TestFilesystemUpdateMetadata(t *testing.T) {
	root:=t.TempDir(); target:=filepath.Join(root,"metadata.txt")
	if err:=os.WriteFile(target,[]byte("metadata\n"),0o640);err!=nil{t.Fatal(err)}
	info,err:=os.Stat(target);if err!=nil{t.Fatal(err)}; stat:=info.Sys().(*syscall.Stat_t)
	params:=filesystemMetadataParams{Permissions:"0600",Owner:strconv.FormatUint(uint64(stat.Uid),10),Group:strconv.FormatUint(uint64(stat.Gid),10)}
	data,operationError:=filesystemUpdateMetadata(context.Background(),target,params);if operationError!=nil{t.Fatalf("metadata update failed: %+v",operationError)}
	if data["permissions"]!="0600"{t.Fatalf("unexpected permissions: %#v",data)}
	updated,err:=os.Stat(target);if err!=nil{t.Fatal(err)};if updated.Mode().Perm()!=0o600{t.Fatalf("unexpected mode: %o",updated.Mode().Perm())}
	if _,operationError=filesystemUpdateMetadata(context.Background(),target,filesystemMetadataParams{Permissions:"4755",Owner:params.Owner,Group:params.Group});operationError==nil||operationError.Code!="invalid_permissions"{t.Fatalf("special mode should be rejected: %+v",operationError)}
}
'''
write(helper_test_path,helper_test)
print("Applied HYZoraX Control Panel V1.5.5 metadata controls + operation notifications")
