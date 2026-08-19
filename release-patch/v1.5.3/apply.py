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
    (root / rel).write_text(text, encoding="utf-8")

def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"{label}: marker not found")
    return text.replace(old, new, 1)

def sub_once(text, pattern, repl, label):
    out, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    return out

# ---------------------------------------------------------------------------
# Version + helper protocol
# ---------------------------------------------------------------------------
html = read("internal/web/static/index.html")
html = replace_once(html, "Version 1.5.2", "Version 1.5.3", "version")

protocol = read("internal/helper/protocol.go")
protocol = replace_once(protocol, "const ProtocolVersion = 8", "const ProtocolVersion = 9", "helper protocol")
write("internal/helper/protocol.go", protocol)

# ---------------------------------------------------------------------------
# Helper recycle-bin backend. Permanent delete remains private for purge only;
# browser Delete now maps to guarded trash/recycle-bin actions.
# ---------------------------------------------------------------------------
fs_path = "internal/helper/filesystem_linux.go"
fs = read(fs_path)

const_marker = "\tmaxDeleteEntries      = 5000\n"
if "filesystemRecycleMetadataDir" not in fs:
    fs = replace_once(
        fs,
        const_marker,
        const_marker + "\nvar filesystemRecycleMetadataDir = \"/var/lib/hyzorax-control/recycle-bin\"\n",
        "recycle metadata dir",
    )

budget_marker = "type filesystemDeleteBudget struct {\n\tEntries int\n}\n"
recycle_types = r'''

type filesystemRecycleRecord struct {
	ID           string `json:"id"`
	OriginalPath string `json:"original_path"`
	StagedPath   string `json:"staged_path"`
	Name         string `json:"name"`
	Kind         string `json:"kind"`
	DeletedAt    string `json:"deleted_at"`
	Entries      int    `json:"entries"`
}
'''
if "type filesystemRecycleRecord struct" not in fs:
    fs = replace_once(fs, budget_marker, budget_marker + recycle_types, "recycle record type")

# Hide same-directory staged trash entries from normal File Manager listings.
if 'strings.HasPrefix(entry.Name(), ".hyzorax-trash-")' not in fs:
    fs = replace_once(
        fs,
        "\tfor _, entry := range entries {\n\t\tentryPath := filepath.Join(cleanPath, entry.Name())",
        "\tfor _, entry := range entries {\n\t\tif strings.HasPrefix(entry.Name(), \".hyzorax-trash-\") {\n\t\t\tcontinue\n\t\t}\n\t\tentryPath := filepath.Join(cleanPath, entry.Name())",
        "hide recycled staged items",
    )

# Add recycle functions before the existing private permanent delete function.
if "func filesystemTrash(" not in fs:
    recycle_backend = r'''
func filesystemRecycleID() (string, error) {
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	return hex.EncodeToString(buffer), nil
}

func filesystemRecycleMetadataPath(id string) (string, *Error) {
	if len(id) != 32 {
		return "", &Error{Code: "invalid_recycle_id", Message: "recycle-bin item identifier is invalid"}
	}
	if _, err := hex.DecodeString(id); err != nil {
		return "", &Error{Code: "invalid_recycle_id", Message: "recycle-bin item identifier is invalid"}
	}
	return filepath.Join(filesystemRecycleMetadataDir, id+".json"), nil
}

func filesystemWriteRecycleRecord(record filesystemRecycleRecord) *Error {
	if err := os.MkdirAll(filesystemRecycleMetadataDir, 0o700); err != nil {
		return filesystemError(err, "recycle-bin metadata directory could not be created")
	}
	if err := os.Chmod(filesystemRecycleMetadataDir, 0o700); err != nil {
		return filesystemError(err, "recycle-bin metadata directory permissions could not be secured")
	}
	metadataPath, pathError := filesystemRecycleMetadataPath(record.ID)
	if pathError != nil {
		return pathError
	}
	encoded, err := json.Marshal(record)
	if err != nil {
		return &Error{Code: "operation_failed", Message: "recycle-bin metadata could not be encoded"}
	}
	temporary, err := os.CreateTemp(filesystemRecycleMetadataDir, ".record-*.tmp")
	if err != nil {
		return filesystemError(err, "recycle-bin metadata could not be created")
	}
	temporaryName := temporary.Name()
	committed := false
	defer func() {
		_ = temporary.Close()
		if !committed {
			_ = os.Remove(temporaryName)
		}
	}()
	if err := temporary.Chmod(0o600); err != nil {
		return filesystemError(err, "recycle-bin metadata permissions could not be secured")
	}
	if _, err := temporary.Write(encoded); err != nil {
		return filesystemError(err, "recycle-bin metadata could not be written")
	}
	if err := temporary.Sync(); err != nil {
		return filesystemError(err, "recycle-bin metadata could not be synchronized")
	}
	if err := temporary.Close(); err != nil {
		return filesystemError(err, "recycle-bin metadata could not be closed")
	}
	if err := os.Rename(temporaryName, metadataPath); err != nil {
		return filesystemError(err, "recycle-bin metadata could not be committed")
	}
	committed = true
	return nil
}

func filesystemReadRecycleRecord(id string) (*filesystemRecycleRecord, *Error) {
	metadataPath, pathError := filesystemRecycleMetadataPath(id)
	if pathError != nil {
		return nil, pathError
	}
	encoded, err := os.ReadFile(metadataPath)
	if errors.Is(err, os.ErrNotExist) {
		return nil, &Error{Code: "recycle_item_not_found", Message: "recycle-bin item was not found"}
	}
	if err != nil {
		return nil, filesystemError(err, "recycle-bin metadata could not be read")
	}
	var record filesystemRecycleRecord
	if err := json.Unmarshal(encoded, &record); err != nil || record.ID != id || record.OriginalPath == "" || record.StagedPath == "" {
		return nil, &Error{Code: "operation_failed", Message: "recycle-bin metadata is invalid"}
	}
	return &record, nil
}

func filesystemTrash(ctx context.Context, rawPath string) (map[string]any, *Error) {
	cleanPath, pathError := validateFilesystemPath(rawPath)
	if pathError != nil {
		return nil, pathError
	}
	if cleanPath == string(os.PathSeparator) {
		return nil, &Error{Code: "root_path_denied", Message: "the filesystem root cannot be moved to the recycle bin"}
	}
	if isProtectedFilesystemDeletePath(cleanPath) {
		return nil, &Error{Code: "protected_path_denied", Message: "this critical system or HYZoraX path cannot be moved to the recycle bin"}
	}
	if err := ctx.Err(); err != nil {
		return nil, &Error{Code: "operation_timeout", Message: "filesystem request timed out"}
	}

	parentPath := filepath.Dir(cleanPath)
	name := filepath.Base(cleanPath)
	parent, openError := openFilesystemPath(parentPath, unix.O_RDONLY|unix.O_DIRECTORY)
	if openError != nil {
		return nil, filesystemError(openError, "recycle-bin parent directory could not be opened")
	}
	defer parent.Close()
	parentStat, statError := filesystemFDStat(parent)
	if statError != nil {
		return nil, filesystemError(statError, "recycle-bin parent directory metadata could not be read")
	}
	source, operationError := inspectFilesystemDeleteSourceAt(int(parent.Fd()), name)
	if operationError != nil {
		return nil, operationError
	}
	if uint64(source.Stat.Dev) != uint64(parentStat.Dev) {
		return nil, &Error{Code: "mount_boundary_denied", Message: "mount-boundary paths cannot be moved to the recycle bin"}
	}
	budget := &filesystemDeleteBudget{}
	if operationError := filesystemDeletePreflightAt(ctx, int(parent.Fd()), name, uint64(source.Stat.Dev), budget); operationError != nil {
		return nil, operationError
	}

	id, err := filesystemRecycleID()
	if err != nil {
		return nil, &Error{Code: "operation_failed", Message: "recycle-bin identifier could not be generated"}
	}
	stagedName := ".hyzorax-trash-" + id
	if err := unix.Renameat2(int(parent.Fd()), name, int(parent.Fd()), stagedName, unix.RENAME_NOREPLACE); err != nil {
		return nil, filesystemError(err, "file or directory could not be moved to the recycle bin")
	}
	stagedPath := filepath.Join(parentPath, stagedName)
	record := filesystemRecycleRecord{
		ID: id, OriginalPath: cleanPath, StagedPath: stagedPath, Name: name,
		Kind: source.Kind, DeletedAt: time.Now().UTC().Format(time.RFC3339Nano), Entries: budget.Entries,
	}
	if metadataError := filesystemWriteRecycleRecord(record); metadataError != nil {
		_ = unix.Renameat2(int(parent.Fd()), stagedName, int(parent.Fd()), name, unix.RENAME_NOREPLACE)
		return nil, metadataError
	}
	_ = unix.Fsync(int(parent.Fd()))
	return map[string]any{
		"id": id, "path": cleanPath, "name": name, "kind": source.Kind,
		"deleted_at": record.DeletedAt, "entries": budget.Entries,
	}, nil
}

func filesystemRecycleList(ctx context.Context) (map[string]any, *Error) {
	if err := ctx.Err(); err != nil {
		return nil, &Error{Code: "operation_timeout", Message: "filesystem request timed out"}
	}
	if err := os.MkdirAll(filesystemRecycleMetadataDir, 0o700); err != nil {
		return nil, filesystemError(err, "recycle-bin metadata directory could not be opened")
	}
	entries, err := os.ReadDir(filesystemRecycleMetadataDir)
	if err != nil {
		return nil, filesystemError(err, "recycle-bin metadata could not be listed")
	}
	items := make([]filesystemRecycleRecord, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		id := strings.TrimSuffix(entry.Name(), ".json")
		record, recordError := filesystemReadRecycleRecord(id)
		if recordError != nil {
			continue
		}
		info, statError := os.Lstat(record.StagedPath)
		if statError != nil {
			continue
		}
		kind := filesystemKind(info.Mode())
		if kind != "file" && kind != "directory" {
			continue
		}
		items = append(items, *record)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].DeletedAt > items[j].DeletedAt })
	return map[string]any{"items": items, "count": len(items)}, nil
}

func filesystemRecycleRestore(ctx context.Context, id string) (map[string]any, *Error) {
	record, operationError := filesystemReadRecycleRecord(id)
	if operationError != nil {
		return nil, operationError
	}
	if err := ctx.Err(); err != nil {
		return nil, &Error{Code: "operation_timeout", Message: "filesystem request timed out"}
	}
	originalPath, pathError := validateFilesystemPath(record.OriginalPath)
	if pathError != nil {
		return nil, pathError
	}
	stagedPath, pathError := validateFilesystemPath(record.StagedPath)
	if pathError != nil {
		return nil, pathError
	}
	if filepath.Dir(originalPath) != filepath.Dir(stagedPath) {
		return nil, &Error{Code: "operation_failed", Message: "recycle-bin metadata does not match the staged filesystem location"}
	}
	parent, openError := openFilesystemPath(filepath.Dir(originalPath), unix.O_RDONLY|unix.O_DIRECTORY)
	if openError != nil {
		return nil, filesystemError(openError, "restore parent directory could not be opened")
	}
	defer parent.Close()
	if err := unix.Renameat2(int(parent.Fd()), filepath.Base(stagedPath), int(parent.Fd()), filepath.Base(originalPath), unix.RENAME_NOREPLACE); err != nil {
		if errors.Is(err, unix.EEXIST) {
			return nil, &Error{Code: "path_exists", Message: "the original path is already occupied; rename or move that item before restoring"}
		}
		return nil, filesystemError(err, "recycle-bin item could not be restored")
	}
	metadataPath, _ := filesystemRecycleMetadataPath(id)
	_ = os.Remove(metadataPath)
	_ = unix.Fsync(int(parent.Fd()))
	return map[string]any{"id": id, "path": originalPath, "name": record.Name, "kind": record.Kind}, nil
}

func filesystemRecyclePurge(ctx context.Context, id string) (map[string]any, *Error) {
	record, operationError := filesystemReadRecycleRecord(id)
	if operationError != nil {
		return nil, operationError
	}
	if err := ctx.Err(); err != nil {
		return nil, &Error{Code: "operation_timeout", Message: "filesystem request timed out"}
	}
	deleted, deleteError := filesystemDelete(ctx, record.StagedPath)
	if deleteError != nil {
		return nil, deleteError
	}
	metadataPath, _ := filesystemRecycleMetadataPath(id)
	_ = os.Remove(metadataPath)
	return map[string]any{"id": id, "name": record.Name, "kind": record.Kind, "entries": deleted["entries"]}, nil
}

'''
    fs = replace_once(fs, "func filesystemDelete(ctx context.Context, rawPath string) (map[string]any, *Error) {", recycle_backend + "func filesystemDelete(ctx context.Context, rawPath string) (map[string]any, *Error) {", "recycle backend insertion")

write(fs_path, fs)

# ---------------------------------------------------------------------------
# Helper dispatch
# ---------------------------------------------------------------------------
server_path = "internal/helper/server_linux.go"
server = read(server_path)
server = replace_once(
    server,
    'if request.Action == "filesystem.delete" {\n\t\ttimeout = 60 * time.Second\n\t}',
    'if request.Action == "filesystem.delete" || request.Action == "filesystem.trash" || request.Action == "filesystem.recycle.purge" {\n\t\ttimeout = 60 * time.Second\n\t}',
    "helper timeout",
)
if 'case "filesystem.trash":' not in server:
    recycle_cases = r'''
	case "filesystem.trash":
		data, operationError := filesystemTrash(ctx, request.Target)
		if operationError != nil {
			response.Error = operationError
			return response
		}
		response.OK = true
		response.Data = data
		return response
	case "filesystem.recycle.list":
		data, operationError := filesystemRecycleList(ctx)
		if operationError != nil {
			response.Error = operationError
			return response
		}
		response.OK = true
		response.Data = data
		return response
	case "filesystem.recycle.restore":
		var params struct { ID string `json:"id"` }
		if operationError := decodeFilesystemParams(request.Params, &params); operationError != nil {
			response.Error = operationError
			return response
		}
		data, operationError := filesystemRecycleRestore(ctx, params.ID)
		if operationError != nil {
			response.Error = operationError
			return response
		}
		response.OK = true
		response.Data = data
		return response
	case "filesystem.recycle.purge":
		var params struct { ID string `json:"id"` }
		if operationError := decodeFilesystemParams(request.Params, &params); operationError != nil {
			response.Error = operationError
			return response
		}
		data, operationError := filesystemRecyclePurge(ctx, params.ID)
		if operationError != nil {
			response.Error = operationError
			return response
		}
		response.OK = true
		response.Data = data
		return response
'''
    server = replace_once(server, '\tcase "filesystem.delete":', recycle_cases + '\tcase "filesystem.delete":', "helper recycle cases")
write(server_path, server)

# ---------------------------------------------------------------------------
# HTTP API: preview + recycle bin. Existing /files/delete becomes trash.
# ---------------------------------------------------------------------------
app_path = "internal/httpapi/app.go"
app = read(app_path)
if 'GET /api/v1/files/preview' not in app:
    app = replace_once(
        app,
        '\tmux.Handle("GET /api/v1/files/download", a.requireAuth(http.HandlerFunc(a.handleFileDownload)))\n',
        '\tmux.Handle("GET /api/v1/files/download", a.requireAuth(http.HandlerFunc(a.handleFileDownload)))\n\tmux.Handle("GET /api/v1/files/preview", a.requireAuth(http.HandlerFunc(a.handleFilePreview)))\n',
        "preview route",
    )
if 'GET /api/v1/files/recycle-bin' not in app:
    app = replace_once(
        app,
        '\tmux.Handle("POST /api/v1/files/delete", a.requireAuth(http.HandlerFunc(a.handleFileDelete)))\n',
        '\tmux.Handle("POST /api/v1/files/delete", a.requireAuth(http.HandlerFunc(a.handleFileDelete)))\n\tmux.Handle("GET /api/v1/files/recycle-bin", a.requireAuth(http.HandlerFunc(a.handleRecycleBinList)))\n\tmux.Handle("POST /api/v1/files/recycle-bin/restore", a.requireAuth(http.HandlerFunc(a.handleRecycleBinRestore)))\n\tmux.Handle("POST /api/v1/files/recycle-bin/purge", a.requireAuth(http.HandlerFunc(a.handleRecycleBinPurge)))\n',
        "recycle routes",
    )
write(app_path, app)

handlers_path = "internal/httpapi/handlers.go"
handlers = read(handlers_path)
if "type recycleActionRequest struct" not in handlers:
    handlers = replace_once(
        handlers,
        'type deleteFileRequest struct {\n\tPath string `json:"path"`\n}\n',
        'type deleteFileRequest struct {\n\tPath string `json:"path"`\n}\n\ntype recycleActionRequest struct {\n\tID string `json:"id"`\n}\n',
        "recycle request type",
    )

if "func (a *App) handleFilePreview" not in handlers:
    preview_handler = r'''
func (a *App) handleFilePreview(writer http.ResponseWriter, request *http.Request) {
	target := request.URL.Query().Get("path")
	extension := strings.ToLower(filepath.Ext(target))
	contentTypes := map[string]string{
		".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
		".webp": "image/webp", ".gif": "image/gif",
	}
	contentType, allowed := contentTypes[extension]
	if !allowed {
		writeError(writer, http.StatusBadRequest, "preview_unsupported", "This file type cannot be previewed in the File Manager.")
		return
	}
	response, ok := a.callFilesystemHelper(writer, request, "filesystem.read", target)
	if !ok { return }
	encoded, valid := response.Data["content_base64"].(string)
	if !valid {
		writeError(writer, http.StatusBadGateway, "helper_invalid_response", "Privileged helper returned an invalid file response.")
		return
	}
	contents, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil {
		writeError(writer, http.StatusBadGateway, "helper_invalid_response", "Privileged helper returned an invalid file response.")
		return
	}
	canonicalTarget, _ := response.Data["path"].(string)
	if canonicalTarget == "" { canonicalTarget = target }
	a.audit(request, "filesystem.preview", canonicalTarget, "success", map[string]any{"bytes": len(contents), "content_type": contentType})
	writer.Header().Set("Content-Type", contentType)
	writer.Header().Set("Content-Length", strconv.Itoa(len(contents)))
	writer.Header().Set("Content-Disposition", "inline")
	writer.Header().Set("Cache-Control", "no-store")
	writer.WriteHeader(http.StatusOK)
	_, _ = writer.Write(contents)
}

'''
    handlers = replace_once(handlers, "func (a *App) handleFileDownload(writer http.ResponseWriter, request *http.Request) {", preview_handler + "func (a *App) handleFileDownload(writer http.ResponseWriter, request *http.Request) {", "preview handler")

# Browser Delete now moves to recycle bin instead of permanent helper delete.
handlers = replace_once(handlers, 'a.callFilesystemHelper(writer, request, "filesystem.delete", input.Path)', 'a.callFilesystemHelper(writer, request, "filesystem.trash", input.Path)', "delete to trash helper")
handlers = replace_once(handlers, 'a.audit(request, "filesystem.delete", input.Path, "success", map[string]any{', 'a.audit(request, "filesystem.trash", input.Path, "success", map[string]any{', "delete trash audit")

if "func (a *App) handleRecycleBinList" not in handlers:
    recycle_handlers = r'''
func (a *App) handleRecycleBinList(writer http.ResponseWriter, request *http.Request) {
	response, ok := a.callFilesystemHelper(writer, request, "filesystem.recycle.list", "")
	if !ok { return }
	writeJSON(writer, http.StatusOK, response.Data)
}

func (a *App) handleRecycleBinRestore(writer http.ResponseWriter, request *http.Request) {
	var input recycleActionRequest
	if !decodeJSON(writer, request, &input) { return }
	params, _ := json.Marshal(map[string]string{"id": input.ID})
	response, ok := a.callFilesystemHelperWithParams(writer, request, "filesystem.recycle.restore", "", params)
	if !ok { return }
	path, _ := response.Data["path"].(string)
	a.audit(request, "filesystem.recycle.restore", path, "success", map[string]any{"id": input.ID, "name": response.Data["name"], "kind": response.Data["kind"]})
	writeJSON(writer, http.StatusOK, response.Data)
}

func (a *App) handleRecycleBinPurge(writer http.ResponseWriter, request *http.Request) {
	var input recycleActionRequest
	if !decodeJSON(writer, request, &input) { return }
	params, _ := json.Marshal(map[string]string{"id": input.ID})
	response, ok := a.callFilesystemHelperWithParams(writer, request, "filesystem.recycle.purge", "", params)
	if !ok { return }
	a.audit(request, "filesystem.recycle.purge", input.ID, "success", map[string]any{"name": response.Data["name"], "kind": response.Data["kind"], "entries": response.Data["entries"]})
	writeJSON(writer, http.StatusOK, response.Data)
}

'''
    handlers = replace_once(handlers, "func (a *App) handleTextFileRead(writer http.ResponseWriter, request *http.Request) {", recycle_handlers + "func (a *App) handleTextFileRead(writer http.ResponseWriter, request *http.Request) {", "recycle handlers")

handlers = replace_once(
    handlers,
    'case "invalid_path", "invalid_name", "invalid_params", "invalid_content", "invalid_hash", "not_text_file", "path_traversal_denied", "not_directory", "not_regular_file", "same_name", "same_path", "copy_descendant_denied", "move_descendant_denied":',
    'case "invalid_path", "invalid_name", "invalid_params", "invalid_content", "invalid_hash", "not_text_file", "path_traversal_denied", "not_directory", "not_regular_file", "same_name", "same_path", "copy_descendant_denied", "move_descendant_denied", "invalid_recycle_id", "preview_unsupported":',
    "http bad request codes",
)
handlers = replace_once(
    handlers,
    'case "path_not_found":',
    'case "path_not_found", "recycle_item_not_found":',
    "recycle not found code",
)
write(handlers_path, handlers)

# ---------------------------------------------------------------------------
# HTML: aaPanel-like persistent upload dialog, image preview, recycle bin.
# ---------------------------------------------------------------------------
# Add Recycle Bin command button after Upload.
if 'id="recycle-bin-button"' not in html:
    html = replace_once(
        html,
        '<button id="upload-button" class="tool-button compact-tool" type="button">⇧ Upload</button>',
        '<button id="upload-button" class="tool-button compact-tool" type="button">⇧ Upload</button>\n              <button id="recycle-bin-button" class="tool-button compact-tool" type="button">♻ Recycle Bin</button>',
        "recycle bin command button",
    )

upload_dialog = r'''<dialog id="upload-dialog" class="modal upload-manager-modal">
      <form id="upload-form" class="modal-card upload-manager-card">
        <div class="operation-heading"><div><h3>Upload files</h3><p class="upload-destination">Destination: <code id="upload-parent-path">/</code></p></div><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        <button id="upload-drop-zone" class="upload-drop-zone" type="button">
          <span class="upload-drop-icon" aria-hidden="true">⇧</span>
          <strong>Choose a file</strong>
          <span>or drag and drop it here</span>
          <small>Maximum file size: 8 MB</small>
        </button>
        <div id="upload-selection" class="upload-selection" hidden>
          <div class="upload-file-row"><span class="upload-file-icon" aria-hidden="true">▤</span><div><strong id="upload-selected-name"></strong><small id="upload-selected-size"></small></div><span id="upload-status-badge" class="upload-status-badge">Ready</span></div>
          <label>File name<input id="upload-name-input" name="name" maxlength="255" autocomplete="off" required></label>
          <div class="upload-progress-track"><span id="upload-progress-bar"></span></div>
          <p id="upload-progress-text" class="upload-progress-text">Ready to upload.</p>
        </div>
        <div id="upload-error" class="alert" role="alert" hidden></div>
        <div class="modal-actions upload-actions"><button type="button" class="ghost compact" data-close-dialog>Close</button><button id="upload-submit-button" type="submit" class="primary compact-primary" disabled>Upload</button></div>
      </form>
    </dialog>'''
html = sub_once(html, r'<dialog id="upload-dialog" class="modal">.*?</dialog>', upload_dialog, "persistent upload dialog")

# Delete wording becomes Recycle Bin, not permanent removal.
html = html.replace('<div class="operation-heading"><h3>Delete</h3>', '<div class="operation-heading"><h3>Move to Recycle Bin</h3>', 1)
html = html.replace('This permanently deletes the selected item. Folders are removed recursively after guarded validation.', 'The selected item will be moved to the Recycle Bin and can be restored later.', 1)
html = html.replace('<button type="submit" class="danger-button">Delete</button>', '<button type="submit" class="danger-button">Move to Recycle Bin</button>', 1)

preview_dialog = r'''<dialog id="image-preview-dialog" class="modal image-preview-modal">
      <div class="modal-card image-preview-card">
        <div class="operation-heading"><div><h3 id="image-preview-name">Image preview</h3><p id="image-preview-path" class="image-preview-path"></p></div><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        <div class="image-preview-stage"><img id="image-preview-image" alt=""></div>
        <div id="image-preview-error" class="alert" role="alert" hidden></div>
        <div class="modal-actions"><a id="image-preview-download" class="ghost compact" href="#">Download</a><button type="button" class="primary compact-primary" data-close-dialog>Close</button></div>
      </div>
    </dialog>'''

recycle_dialog = r'''<dialog id="recycle-bin-dialog" class="modal recycle-bin-modal">
      <div class="modal-card recycle-bin-card">
        <div class="operation-heading"><div><h3>Recycle Bin</h3><p class="recycle-bin-note">Deleted files and folders stay here until you restore or permanently remove them.</p></div><button type="button" class="operation-close" data-close-dialog aria-label="Close">×</button></div>
        <div id="recycle-bin-list" class="recycle-bin-list"></div>
        <div id="recycle-bin-empty" class="recycle-bin-empty" hidden>Recycle Bin is empty.</div>
        <div id="recycle-bin-error" class="alert" role="alert" hidden></div>
        <div class="modal-actions"><button id="recycle-bin-refresh" type="button" class="ghost compact">Refresh</button><button type="button" class="primary compact-primary" data-close-dialog>Close</button></div>
      </div>
    </dialog>'''

if 'id="image-preview-dialog"' not in html:
    html = replace_once(html, '    <dialog id="editor-dialog" class="modal wide">', preview_dialog + '\n\n    ' + recycle_dialog + '\n\n    <dialog id="editor-dialog" class="modal wide">', "preview recycle dialogs")

write("internal/web/static/index.html", html)

# ---------------------------------------------------------------------------
# JavaScript behavior
# ---------------------------------------------------------------------------
js_path = "internal/web/static/app.js"
js = read(js_path)

# Click-to-open/edit/preview file names.
old_name_block = r'''if (entry.kind === "directory") {
const openButton = document.createElement("button");
openButton.type = "button";
openButton.textContent = entry.name;
openButton.addEventListener("click", () => loadFiles(entry.path));
nameMain.append(openButton);
} else {
const name = document.createElement("span");
name.textContent = entry.name;
nameMain.append(name);
}'''
new_name_block = r'''if (entry.kind === "directory" || entry.editable || (entry.downloadable && isImageFileName(entry.name))) {
const openButton = document.createElement("button");
openButton.type = "button";
openButton.className = "file-name-button";
openButton.textContent = entry.name;
if (entry.kind === "directory") openButton.addEventListener("click", () => loadFiles(entry.path));
else if (entry.editable) openButton.addEventListener("click", () => openEditor(entry.path));
else openButton.addEventListener("click", () => openImagePreview(entry));
nameMain.append(openButton);
} else {
const name = document.createElement("span");
name.textContent = entry.name;
nameMain.append(name);
}'''
js = replace_once(js, old_name_block, new_name_block, "clickable file names")

# Add Open action for previewable images in menu.
js = replace_once(
    js,
    'if (entry.kind === "directory") { appendFileAction(menu, "open", "Open", () => loadFiles(entry.path)); primaryCount += 1; }',
    'if (entry.kind === "directory") { appendFileAction(menu, "open", "Open", () => loadFiles(entry.path)); primaryCount += 1; }\nif (entry.kind === "file" && entry.downloadable && isImageFileName(entry.name)) { appendFileAction(menu, "open", "Open", () => openImagePreview(entry)); primaryCount += 1; }',
    "image open menu action",
)

# Helpers before fileKindIcon.
if "function isImageFileName" not in js:
    image_helpers = r'''function isImageFileName(name) {
return /\.(png|jpe?g|webp|gif)$/i.test(String(name || ""));
}
function openImagePreview(entry) {
const image = $("#image-preview-image");
const path = entry.path;
clearError("#image-preview-error");
$("#image-preview-name").textContent = entry.name;
$("#image-preview-path").textContent = path;
image.alt = entry.name;
image.removeAttribute("src");
$("#image-preview-download").href = `api/v1/files/download?path=${encodeURIComponent(path)}`;
image.onload = () => clearError("#image-preview-error");
image.onerror = () => showError("#image-preview-error", "Image preview could not be loaded.");
image.src = `api/v1/files/preview?path=${encodeURIComponent(path)}&v=${Date.now()}`;
openDialog("#image-preview-dialog");
}
async function loadRecycleBin() {
clearError("#recycle-bin-error");
try {
const data = await request("api/v1/files/recycle-bin");
const items = Array.isArray(data.items) ? data.items : [];
const list = $("#recycle-bin-list"); list.replaceChildren();
$("#recycle-bin-empty").hidden = items.length !== 0;
items.forEach((item) => {
const row = document.createElement("div"); row.className = "recycle-bin-row";
const icon = document.createElement("span"); icon.className = "recycle-bin-kind"; icon.textContent = item.kind === "directory" ? "▱" : "▤";
const info = document.createElement("div"); info.className = "recycle-bin-info";
const name = document.createElement("strong"); name.textContent = item.name;
const path = document.createElement("small"); path.textContent = item.original_path;
const time = document.createElement("small"); time.textContent = `Deleted ${formatTimestamp(item.deleted_at)}`;
info.append(name, path, time);
const actions = document.createElement("div"); actions.className = "recycle-bin-actions";
const restore = document.createElement("button"); restore.type = "button"; restore.className = "ghost compact"; restore.textContent = "Restore";
restore.addEventListener("click", async () => { restore.disabled = true; try { await request("api/v1/files/recycle-bin/restore", {method:"POST", body:JSON.stringify({id:item.id})}); await loadRecycleBin(); await loadFiles(state.currentPath); } catch(error) { showError("#recycle-bin-error", error.message); } finally { restore.disabled = false; } });
const purge = document.createElement("button"); purge.type = "button"; purge.className = "recycle-purge-button"; purge.textContent = "Delete permanently";
purge.addEventListener("click", async () => { if (!window.confirm(`Permanently delete ${item.name}? This cannot be undone.`)) return; purge.disabled = true; try { await request("api/v1/files/recycle-bin/purge", {method:"POST", body:JSON.stringify({id:item.id})}); await loadRecycleBin(); } catch(error) { showError("#recycle-bin-error", error.message); } finally { purge.disabled = false; } });
actions.append(restore, purge); row.append(icon, info, actions); list.append(row);
});
} catch (error) { showError("#recycle-bin-error", error.message); }
}
'''
    js = replace_once(js, "function fileKindIcon(kind) {", image_helpers + "function fileKindIcon(kind) {", "preview recycle helpers")

# Delete submit keeps the compact confirmation dialog, but endpoint now trashes.
js = js.replace('await request("api/v1/files/delete", { method: "POST", body: JSON.stringify({ path: state.deletePath }) }); closeDialog($("#delete-dialog")); await loadFiles(state.currentPath);', 'await request("api/v1/files/delete", { method: "POST", body: JSON.stringify({ path: state.deletePath }) }); closeDialog($("#delete-dialog")); await loadFiles(state.currentPath);', 1)

# Replace upload toolbar and input logic with persistent dialog behavior.
upload_old = r'''$("#upload-button").addEventListener("click", () => {
$("#upload-file-input").value = "";
$("#upload-file-input").click();
});
$("#upload-file-input").addEventListener("change", (event) => {
const file = event.currentTarget.files?.[0];
if (!file) return;
if (file.size > 8 * 1024 * 1024) {
showError("#file-error", "File exceeds the 8 MB upload limit.");
return;
}
state.pendingUpload = file;
$("#upload-parent-path").textContent = state.currentPath;
$("#upload-name-input").value = file.name;
$("#upload-file-detail").textContent = `${file.name} · ${formatBytes(file.size)} · Existing paths will not be overwritten.`;
clearError("#upload-error");
openDialog("#upload-dialog");
});'''
upload_new = r'''function resetUploadDialog() {
state.pendingUpload = null;
$("#upload-file-input").value = "";
$("#upload-parent-path").textContent = state.currentPath;
$("#upload-selection").hidden = true;
$("#upload-selected-name").textContent = "";
$("#upload-selected-size").textContent = "";
$("#upload-name-input").value = "";
$("#upload-submit-button").disabled = true;
$("#upload-status-badge").textContent = "Ready";
$("#upload-status-badge").className = "upload-status-badge";
$("#upload-progress-bar").style.width = "0%";
$("#upload-progress-text").textContent = "Ready to upload.";
clearError("#upload-error");
}
function selectUploadFile(file) {
if (!file) return;
clearError("#upload-error");
if (file.size > 8 * 1024 * 1024) { showError("#upload-error", "File exceeds the 8 MB upload limit."); return; }
state.pendingUpload = file;
$("#upload-selection").hidden = false;
$("#upload-selected-name").textContent = file.name;
$("#upload-selected-size").textContent = formatBytes(file.size);
$("#upload-name-input").value = file.name;
$("#upload-submit-button").disabled = false;
$("#upload-status-badge").textContent = "Ready";
$("#upload-status-badge").className = "upload-status-badge";
$("#upload-progress-bar").style.width = "0%";
$("#upload-progress-text").textContent = "Ready to upload.";
}
$("#upload-button").addEventListener("click", () => { resetUploadDialog(); openDialog("#upload-dialog"); });
$("#upload-drop-zone").addEventListener("click", () => { $("#upload-file-input").value = ""; $("#upload-file-input").click(); });
$("#upload-file-input").addEventListener("change", (event) => selectUploadFile(event.currentTarget.files?.[0]));
["dragenter", "dragover"].forEach((name) => $("#upload-drop-zone").addEventListener(name, (event) => { event.preventDefault(); $("#upload-drop-zone").classList.add("dragging"); }));
["dragleave", "drop"].forEach((name) => $("#upload-drop-zone").addEventListener(name, (event) => { event.preventDefault(); $("#upload-drop-zone").classList.remove("dragging"); }));
$("#upload-drop-zone").addEventListener("drop", (event) => selectUploadFile(event.dataTransfer?.files?.[0]));'''
js = replace_once(js, upload_old, upload_new, "persistent upload selection")

upload_submit_old = r'''$("#upload-form").addEventListener("submit", async (event) => {
event.preventDefault();
const form = event.currentTarget;
const file = state.pendingUpload;
if (!file) return;
clearError("#upload-error");
setBusy(form, true);
try {
const content = arrayBufferToBase64(await file.arrayBuffer());
await request("api/v1/files/upload", {
method: "POST",
body: JSON.stringify({ directory: state.currentPath, name: $("#upload-name-input").value, content_base64: content })
});
state.pendingUpload = null;
closeDialog($("#upload-dialog"));
await loadFiles(state.currentPath);
} catch (error) {
showError("#upload-error", error.message);
} finally {
setBusy(form, false);
}
});'''
upload_submit_new = r'''$("#upload-form").addEventListener("submit", async (event) => {
event.preventDefault();
const file = state.pendingUpload;
if (!file) return;
clearError("#upload-error");
const submit = $("#upload-submit-button");
const nameInput = $("#upload-name-input");
submit.disabled = true; nameInput.disabled = true; $("#upload-drop-zone").disabled = true;
$("#upload-status-badge").textContent = "Uploading";
$("#upload-status-badge").className = "upload-status-badge uploading";
$("#upload-progress-bar").style.width = "35%";
$("#upload-progress-text").textContent = "Preparing upload…";
try {
const content = arrayBufferToBase64(await file.arrayBuffer());
$("#upload-progress-bar").style.width = "70%";
$("#upload-progress-text").textContent = "Uploading to server…";
await request("api/v1/files/upload", { method: "POST", body: JSON.stringify({ directory: state.currentPath, name: nameInput.value, content_base64: content }) });
state.pendingUpload = null;
$("#upload-progress-bar").style.width = "100%";
$("#upload-progress-text").textContent = "Upload completed successfully. You can close this window or choose another file.";
$("#upload-status-badge").textContent = "Uploaded";
$("#upload-status-badge").className = "upload-status-badge success";
await loadFiles(state.currentPath);
} catch (error) {
$("#upload-progress-bar").style.width = "0%";
$("#upload-progress-text").textContent = "Upload failed. Fix the issue and try again.";
$("#upload-status-badge").textContent = "Failed";
$("#upload-status-badge").className = "upload-status-badge failed";
showError("#upload-error", error.message);
submit.disabled = false;
} finally {
nameInput.disabled = false; $("#upload-drop-zone").disabled = false;
}
});'''
js = replace_once(js, upload_submit_old, upload_submit_new, "persistent upload submit")

# When the user chooses another file after success, re-enable upload.
js = js.replace('state.pendingUpload = file;\n$("#upload-selection").hidden = false;', 'state.pendingUpload = file;\n$("#upload-selection").hidden = false;', 1)

# Recycle Bin command listeners near other command listeners.
if '$("#recycle-bin-button").addEventListener' not in js:
    js = replace_once(
        js,
        '$("#file-refresh-button").addEventListener("click", () => loadFiles(state.currentPath));',
        '$("#file-refresh-button").addEventListener("click", () => loadFiles(state.currentPath));\n$("#recycle-bin-button").addEventListener("click", async () => { clearError("#recycle-bin-error"); openDialog("#recycle-bin-dialog"); await loadRecycleBin(); });\n$("#recycle-bin-refresh").addEventListener("click", loadRecycleBin);',
        "recycle command listeners",
    )

write(js_path, js)

# ---------------------------------------------------------------------------
# CSS polish
# ---------------------------------------------------------------------------
css_path = "internal/web/static/app.css"
css = read(css_path)
if "/* V1.5.3 preview recycle upload */" not in css:
    css += r'''

/* V1.5.3 preview recycle upload */
.file-name-button { padding:0; border:0; color:var(--text); background:transparent; font:inherit; font-weight:800; text-align:left; cursor:pointer; }
.file-name-button:hover { color:var(--blue-deep); text-decoration:underline; text-underline-offset:3px; }
.upload-manager-modal { width:min(94vw,560px); }
.upload-manager-card { gap:14px; padding:18px; }
.upload-destination { margin:.2rem 0 0; color:var(--muted); font-size:12px; }
.upload-drop-zone { width:100%; min-height:150px; display:grid; place-items:center; align-content:center; gap:5px; padding:20px; border:1.5px dashed rgba(48,129,234,.38); border-radius:13px; color:#31577f; background:linear-gradient(180deg,#fbfdff,#f5faff); text-align:center; }
.upload-drop-zone:hover,.upload-drop-zone.dragging { border-color:var(--blue); background:rgba(99,204,248,.10); }
.upload-drop-icon { width:42px; height:42px; display:grid; place-items:center; border-radius:12px; color:#1262db; background:rgba(65,160,244,.12); font-size:22px; font-weight:900; }
.upload-drop-zone strong { font-size:14px; color:var(--text); }
.upload-drop-zone span:not(.upload-drop-icon),.upload-drop-zone small { color:var(--muted); font-size:11px; }
.upload-selection { display:grid; gap:10px; }
.upload-selection[hidden] { display:none!important; }
.upload-file-row { display:grid; grid-template-columns:36px minmax(0,1fr) auto; align-items:center; gap:9px; padding:10px; border:1px solid var(--line); border-radius:10px; background:#fbfdff; }
.upload-file-icon { width:34px; height:34px; display:grid; place-items:center; border-radius:9px; color:var(--blue-deep); background:rgba(65,160,244,.10); }
.upload-file-row>div { min-width:0; display:grid; gap:2px; }
.upload-file-row strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; }
.upload-file-row small { color:var(--muted); font-size:10px; }
.upload-status-badge { padding:4px 7px; border-radius:999px; color:#496886; background:#eef4fb; font-size:10px; font-weight:850; }
.upload-status-badge.uploading { color:#1262db; background:rgba(65,160,244,.12); }
.upload-status-badge.success { color:#087b5f; background:rgba(29,183,138,.12); }
.upload-status-badge.failed { color:#c92530; background:rgba(227,61,69,.10); }
.upload-progress-track { height:7px; overflow:hidden; border-radius:999px; background:#e9f0f8; }
.upload-progress-track span { display:block; width:0; height:100%; border-radius:inherit; background:linear-gradient(90deg,#63ccf8,#1767e8); transition:width .22s ease; }
.upload-progress-text { margin:0!important; color:var(--muted); font-size:11px; }
.upload-actions { justify-content:flex-end; }
.image-preview-modal { width:min(94vw,920px); }
.image-preview-card { gap:12px; padding:16px; }
.image-preview-path { max-width:70vw; margin:.2rem 0 0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); font-size:11px; }
.image-preview-stage { min-height:280px; max-height:70vh; display:grid; place-items:center; overflow:auto; padding:12px; border:1px solid var(--line); border-radius:12px; background:#f6f9fd; }
.image-preview-stage img { max-width:100%; max-height:66vh; object-fit:contain; border-radius:6px; box-shadow:0 8px 28px rgba(16,42,77,.10); }
.recycle-bin-modal { width:min(94vw,760px); }
.recycle-bin-card { gap:12px; padding:16px; }
.recycle-bin-note { margin:.2rem 0 0; color:var(--muted); font-size:11px; }
.recycle-bin-list { max-height:55vh; overflow:auto; display:grid; gap:6px; }
.recycle-bin-row { display:grid; grid-template-columns:38px minmax(0,1fr) auto; align-items:center; gap:10px; padding:10px; border:1px solid var(--line); border-radius:10px; background:#fbfdff; }
.recycle-bin-kind { width:36px; height:36px; display:grid; place-items:center; border-radius:9px; color:var(--blue-deep); background:rgba(65,160,244,.10); }
.recycle-bin-info { min-width:0; display:grid; gap:2px; }
.recycle-bin-info strong,.recycle-bin-info small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.recycle-bin-info strong { font-size:12px; }
.recycle-bin-info small { color:var(--muted); font-size:10px; }
.recycle-bin-actions { display:flex; gap:6px; }
.recycle-purge-button { min-height:34px; padding:6px 9px; border:1px solid rgba(227,61,69,.20); border-radius:8px; color:#d6303a; background:rgba(227,61,69,.05); font-size:11px; font-weight:800; }
.recycle-purge-button:hover { background:rgba(227,61,69,.10); }
.recycle-bin-empty { padding:30px 10px; color:var(--muted); text-align:center; font-size:12px; }
@media(max-width:680px){.upload-manager-modal,.image-preview-modal,.recycle-bin-modal{width:calc(100vw - 20px)!important}.recycle-bin-row{grid-template-columns:34px minmax(0,1fr)}.recycle-bin-actions{grid-column:1/-1;justify-content:flex-end}.image-preview-stage{min-height:220px}}
'''
write(css_path, css)

# ---------------------------------------------------------------------------
# Tests: keep existing V1.5.2 regressions and add V1.5.3 assertions.
# ---------------------------------------------------------------------------
for rel in ("internal/web/assets_test.go", "internal/httpapi/app_test.go"):
    text = read(rel).replace("Version 1.5.2", "Version 1.5.3")
    write(rel, text)

assets = read("internal/web/assets_test.go")
if "TestFileManagerV153PreviewRecycleUploadUI" not in assets:
    assets += r'''

func TestFileManagerV153PreviewRecycleUploadUI(t *testing.T) {
	htmlBytes, err := Assets.ReadFile("static/index.html")
	if err != nil { t.Fatal(err) }
	javascriptBytes, err := Assets.ReadFile("static/app.js")
	if err != nil { t.Fatal(err) }
	cssBytes, err := Assets.ReadFile("static/app.css")
	if err != nil { t.Fatal(err) }
	html, javascript, css := string(htmlBytes), string(javascriptBytes), string(cssBytes)
	for _, fragment := range []string{`id="recycle-bin-button"`, `id="recycle-bin-dialog"`, `id="image-preview-dialog"`, `id="upload-drop-zone"`, `id="upload-submit-button"`, `Move to Recycle Bin`} {
		if !strings.Contains(html, fragment) { t.Fatalf("V1.5.3 UI is missing %q", fragment) }
	}
	for _, fragment := range []string{`isImageFileName`, `openImagePreview`, `loadRecycleBin`, `api/v1/files/recycle-bin`, `Upload completed successfully`, `file-name-button`} {
		if !strings.Contains(javascript, fragment) { t.Fatalf("V1.5.3 behavior is missing %q", fragment) }
	}
	for _, fragment := range []string{`.upload-manager-modal`, `.image-preview-stage`, `.recycle-bin-row`, `.file-name-button`} {
		if !strings.Contains(css, fragment) { t.Fatalf("V1.5.3 styling is missing %q", fragment) }
	}
}
'''
write("internal/web/assets_test.go", assets)

# Add helper recycle test using a temporary metadata directory.
helper_test_path = "internal/helper/filesystem_linux_test.go"
helper_test = read(helper_test_path)
if "TestFilesystemRecycleRoundTrip" not in helper_test:
    helper_test += r'''

func TestFilesystemRecycleRoundTrip(t *testing.T) {
	oldMetadataDir := filesystemRecycleMetadataDir
	filesystemRecycleMetadataDir = t.TempDir()
	defer func() { filesystemRecycleMetadataDir = oldMetadataDir }()

	root := t.TempDir()
	filePath := filepath.Join(root, "recycle.txt")
	if err := os.WriteFile(filePath, []byte("recycle-safe\n"), 0o640); err != nil { t.Fatal(err) }
	trashed, operationError := filesystemTrash(context.Background(), filePath)
	if operationError != nil { t.Fatalf("trash failed: %+v", operationError) }
	id, _ := trashed["id"].(string)
	if id == "" { t.Fatalf("trash id missing: %#v", trashed) }
	if _, err := os.Lstat(filePath); !errors.Is(err, os.ErrNotExist) { t.Fatalf("original path still exists: %v", err) }
	listed, operationError := filesystemRecycleList(context.Background())
	if operationError != nil { t.Fatalf("recycle list failed: %+v", operationError) }
	if listed["count"] != 1 { t.Fatalf("unexpected recycle count: %#v", listed) }
	restored, operationError := filesystemRecycleRestore(context.Background(), id)
	if operationError != nil { t.Fatalf("restore failed: %+v", operationError) }
	if restored["path"] != filePath { t.Fatalf("unexpected restored path: %#v", restored) }
	if contents, err := os.ReadFile(filePath); err != nil || string(contents) != "recycle-safe\n" { t.Fatalf("restored contents mismatch: %q err=%v", contents, err) }

	trashed, operationError = filesystemTrash(context.Background(), filePath)
	if operationError != nil { t.Fatalf("second trash failed: %+v", operationError) }
	id, _ = trashed["id"].(string)
	if _, operationError = filesystemRecyclePurge(context.Background(), id); operationError != nil { t.Fatalf("purge failed: %+v", operationError) }
	if _, err := os.Lstat(filePath); !errors.Is(err, os.ErrNotExist) { t.Fatalf("purged original unexpectedly exists: %v", err) }
}
'''
write(helper_test_path, helper_test)

print("Applied HYZoraX Control Panel V1.5.3 preview + recycle bin + persistent upload")
