"use strict";
const state = {
user: null,
currentView: "overview",
currentPath: "/",
filesLoaded: false,
pendingUpload: null,
editorPath: "",
editorHash: "",
renamePath: "",
renameOldName: "",
copyPath: "",
copyName: "",
movePath: "",
moveName: "",
dashboardTimer: null,
dashboardBusy: false,
updateBusy: false
};
const $ = (selector) => document.querySelector(selector);
async function request(path, options = {}) {
const headers = new Headers(options.headers || {});
headers.set("Accept", "application/json");
if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
if (options.method && !["GET", "HEAD"].includes(options.method)) {
const csrf = readCookie("hyzorax_csrf");
if (csrf) headers.set("X-CSRF-Token", csrf);
}
const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
let data = {};
try { data = await response.json(); } catch (_) { data = {}; }
if (!response.ok) {
const error = new Error(data.error?.message || `Request failed (${response.status})`);
error.status = response.status;
throw error;
}
return data;
}
function readCookie(name) {
return document.cookie.split("; ").find((value) => value.startsWith(`${name}=`))?.split("=").slice(1).join("=") || "";
}
function showLogin() {
stopDashboardLive();
$("#login-form").hidden = false;
$("#gate").hidden = false;
$("#app").hidden = true;
clearError("#gate-error");
}
function showError(selector, message) {
const box = $(selector);
box.textContent = message;
box.hidden = false;
}
function clearError(selector) {
const box = $(selector);
box.textContent = "";
box.hidden = true;
}
function setBusy(form, busy) {
form.querySelectorAll("button, input, textarea").forEach((element) => { element.disabled = busy; });
}
async function start() {
try {
state.user = await request("api/v1/auth/session");
await showDashboard();
} catch (_) {
showLogin();
}
}
$("#login-form").addEventListener("submit", async (event) => {
event.preventDefault();
clearError("#gate-error");
const form = event.currentTarget;
const fields = Object.fromEntries(new FormData(form));
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
});
document.querySelectorAll("[data-password-toggle]").forEach((button) => {
button.addEventListener("click", () => {
const input = button.closest(".password-input").querySelector("input");
const reveal = input.type === "password";
input.type = reveal ? "text" : "password";
button.classList.toggle("revealed", reveal);
button.setAttribute("aria-label", reveal ? "Hide password" : "Show password");
button.setAttribute("title", reveal ? "Hide password" : "Show password");
input.focus();
});
});
function resetPasswordToggles() {
document.querySelectorAll("[data-password-toggle]").forEach((button) => {
const input = button.closest(".password-input").querySelector("input");
input.type = "password";
button.classList.remove("revealed");
button.setAttribute("aria-label", "Show password");
button.setAttribute("title", "Show password");
});
}
async function showDashboard() {
$("#gate").hidden = true;
$("#app").hidden = false;
$("#user-name").textContent = state.user.username;
$("#user-menu-name").textContent = state.user.username;
$("#user-initial").textContent = state.user.username.slice(0, 1).toUpperCase();
await switchView(window.location.hash === "#files" ? "files" : "overview");
setTimeout(() => checkUpdateStatus(true), 1500);
}
async function switchView(view) {
stopDashboardLive();
const selected = view === "files" ? "files" : "overview";
state.currentView = selected;
$("#overview-view").hidden = selected !== "overview";
$("#files-view").hidden = selected !== "files";
document.querySelectorAll("[data-view]").forEach((link) => link.classList.toggle("active", link.dataset.view === selected));
$("#workspace-eyebrow").textContent = selected === "files" ? "Server filesystem" : "Control Panel";
$("#workspace-title").textContent = selected === "files" ? "File Manager" : "System overview";
$("#refresh-button").title = selected === "files" ? "Refresh directory" : "Refresh dashboard";
$(".sidebar").classList.remove("open");
if (selected === "files") {
await loadFiles(state.filesLoaded ? state.currentPath : "/");
} else {
await refreshDashboard();
scheduleDashboardLive();
}
}
function stopDashboardLive() {
clearTimeout(state.dashboardTimer);
state.dashboardTimer = null;
}
function scheduleDashboardLive() {
stopDashboardLive();
if (!state.user || state.currentView !== "overview" || document.hidden) return;
state.dashboardTimer = setTimeout(async () => {
await refreshDashboard(true);
scheduleDashboardLive();
}, 1000);
}
async function refreshDashboard(live = false) {
if (state.dashboardBusy) return;
state.dashboardBusy = true;
clearError("#app-error");
if (!live) $("#refresh-button").disabled = true;
try {
const summary = await request("api/v1/system/summary");
renderSummary(summary);
} catch (error) {
if (error.status === 401) {
showLogin();
return;
}
showError("#app-error", error.message);
} finally {
state.dashboardBusy = false;
if (!live) $("#refresh-button").disabled = false;
}
}
function renderSummary(data) {
$("#hostname").textContent = data.hostname || "Unnamed server";
$("#platform").textContent = `${data.os_name || "Linux"} · Kernel ${data.kernel || "unknown"}`;
$("#collection-time").textContent = `Updated ${new Date(data.collected_at).toLocaleTimeString()}`;
setMetric("cpu", data.cpu_percent, `${data.cpu_cores} cores · load ${data.load_1.toFixed(2)}`);
setMetric("memory", data.memory_percent, `${formatBytes(data.memory_used_bytes)} of ${formatBytes(data.memory_total_bytes)}`);
setMetric("disk", data.disk_percent, `${formatBytes(data.disk_used_bytes)} of ${formatBytes(data.disk_total_bytes)}`);
$("#uptime-value").textContent = formatDuration(data.uptime_seconds);
$("#load-detail").textContent = `Load averages ${data.load_1.toFixed(2)} · ${data.load_5.toFixed(2)} · ${data.load_15.toFixed(2)}`;
$("#network-rx").textContent = formatBytes(data.network_rx_bytes);
$("#network-tx").textContent = formatBytes(data.network_tx_bytes);
}
function setMetric(name, value, detail) {
const safe = Math.max(0, Math.min(100, Number(value) || 0));
$(`#${name}-value`).textContent = `${safe.toFixed(1)}%`;
$(`#${name}-meter`).style.width = `${safe}%`;
$(`#${name}-detail`).textContent = detail;
}
async function checkUpdateStatus(silent = false) {
if (!state.user || state.updateBusy) return null;
try {
const data = await request("api/v1/update/status");
const button = $("#update-button");
if (data.update_available) {
button.textContent = `Update ${data.latest_version}`;
button.classList.add("available");
button.title = `Update HYZoraX Control Panel ${data.current_version} → ${data.latest_version}`;
} else {
button.textContent = "Update";
button.classList.remove("available");
button.title = `HYZoraX Control Panel ${data.current_version} is up to date`;
if (!silent) {
button.textContent = "Up to date";
setTimeout(() => { if (!state.updateBusy) button.textContent = "Update"; }, 2500);
}
}
return data;
} catch (error) {
if (!silent) showError("#app-error", error.message);
return null;
}
}
async function waitForAppliedUpdate(targetVersion) {
const button = $("#update-button");
for (let attempt = 0; attempt < 80; attempt += 1) {
await new Promise((resolve) => setTimeout(resolve, 2000));
try {
const data = await request("api/v1/update/status");
if (data.current_version === targetVersion) {
button.textContent = "Updated";
window.location.reload();
return;
}
} catch (_) { /* service may be restarting */ }
}
state.updateBusy = false;
button.disabled = false;
button.textContent = "Check update";
showError("#app-error", "Update was started but completion could not be confirmed. Check again in a moment.");
}
async function applyAvailableUpdate() {
if (state.updateBusy) return;
clearError("#app-error");
const button = $("#update-button");
button.disabled = true;
const status = await checkUpdateStatus(false);
if (!status) { button.disabled = false; return; }
if (!status.update_available) { button.disabled = false; return; }
if (!window.confirm(`Update HYZoraX Control Panel ${status.current_version} to ${status.latest_version}? The panel will restart automatically.`)) {
button.disabled = false;
return;
}
state.updateBusy = true;
button.textContent = "Updating…";
try {
await request("api/v1/update/apply", { method: "POST", body: JSON.stringify({}) });
waitForAppliedUpdate(status.latest_version);
} catch (error) {
state.updateBusy = false;
button.disabled = false;
button.textContent = "Update";
showError("#app-error", error.message);
}
}
async function loadFiles(path) {
clearError("#file-error");
$("#refresh-button").disabled = true;
$("#file-status").textContent = "Loading filesystem…";
try {
const data = await request(`api/v1/files?path=${encodeURIComponent(path)}`);
state.currentPath = data.path;
state.filesLoaded = true;
$("#file-path-input").value = data.path;
$("#file-current-path").textContent = data.path;
$("#file-up-button").disabled = data.path === "/";
renderBreadcrumbs(data.path);
renderFiles(data);
} catch (error) {
if (error.status === 401) {
showLogin();
return;
}
$("#file-status").textContent = `Still at ${state.currentPath}`;
showError("#file-error", error.message);
} finally {
$("#refresh-button").disabled = false;
}
}
function renderBreadcrumbs(path) {
const breadcrumbs = $("#file-breadcrumbs");
breadcrumbs.replaceChildren();
const rootButton = document.createElement("button");
rootButton.type = "button";
rootButton.textContent = "/";
rootButton.addEventListener("click", () => loadFiles("/"));
breadcrumbs.append(rootButton);
let current = "";
path.split("/").filter(Boolean).forEach((part) => {
const separator = document.createElement("span");
separator.textContent = "›";
breadcrumbs.append(separator);
current += `/${part}`;
const destination = current;
const button = document.createElement("button");
button.type = "button";
button.textContent = part;
button.addEventListener("click", () => loadFiles(destination));
breadcrumbs.append(button);
});
}
function renderFiles(data) {
const rows = $("#file-rows");
rows.replaceChildren();
const entries = Array.isArray(data.entries) ? data.entries : [];
$("#file-empty").hidden = entries.length !== 0;
const limit = formatBytes(data.max_download_bytes || 0);
const uploadLimit = formatBytes(data.max_upload_bytes || 0);
const editLimit = formatBytes(data.max_edit_bytes || 0);
$("#file-status").textContent = `${entries.length} item${entries.length === 1 ? "" : "s"} · Uploads up to ${uploadLimit} · Text edits up to ${editLimit} · Downloads up to ${limit}${data.truncated ? ` · First ${data.max_entries} shown` : ""}`;
entries.forEach((entry) => {
const row = document.createElement("tr");
const nameCell = document.createElement("td");
const nameWrap = document.createElement("div");
nameWrap.className = "file-name";
const icon = document.createElement("span");
icon.className = `file-kind ${entry.kind}`;
icon.textContent = fileKindIcon(entry.kind);
const nameMain = document.createElement("div");
nameMain.className = "file-name-main";
if (entry.kind === "directory") {
const openButton = document.createElement("button");
openButton.type = "button";
openButton.textContent = entry.name;
openButton.addEventListener("click", () => loadFiles(entry.path));
nameMain.append(openButton);
} else {
const name = document.createElement("span");
name.textContent = entry.name;
nameMain.append(name);
}
if (entry.symlink_target) {
const target = document.createElement("small");
target.textContent = `→ ${entry.symlink_target}`;
nameMain.append(target);
}
if (entry.mount_boundary) {
const mount = document.createElement("span");
mount.className = "mount-label";
mount.textContent = "Mount";
nameMain.append(mount);
}
nameWrap.append(icon, nameMain);
nameCell.append(nameWrap);
const sizeCell = document.createElement("td");
sizeCell.textContent = entry.kind === "file" ? formatBytes(entry.size) : "—";
const ownerCell = document.createElement("td");
ownerCell.textContent = `${entry.owner}:${entry.group}`;
const modeCell = document.createElement("td");
const mode = document.createElement("code");
mode.textContent = entry.permissions;
mode.title = entry.mode;
modeCell.append(mode);
const modifiedCell = document.createElement("td");
modifiedCell.textContent = formatTimestamp(entry.modified_at);
const actionCell = document.createElement("td");
const actionGroup = document.createElement("div");
actionGroup.className = "file-actions";
if (entry.downloadable) {
const download = document.createElement("a");
download.className = "download-link";
download.href = `api/v1/files/download?path=${encodeURIComponent(entry.path)}`;
download.textContent = "Download";
actionGroup.append(download);
}
if (entry.editable) {
const edit = document.createElement("button");
edit.className = "edit-link";
edit.type = "button";
edit.textContent = "Edit";
edit.addEventListener("click", () => openEditor(entry.path));
actionGroup.append(edit);
}
if (entry.copyable) {
const copy = document.createElement("button");
copy.className = "copy-link";
copy.type = "button";
copy.textContent = "Copy";
copy.addEventListener("click", () => openCopy(entry));
actionGroup.append(copy);
}
if (entry.movable) {
const move = document.createElement("button");
move.className = "move-link";
move.type = "button";
move.textContent = "Move";
move.addEventListener("click", () => openMove(entry));
actionGroup.append(move);
}
if (entry.renamable) {
const rename = document.createElement("button");
rename.className = "rename-link";
rename.type = "button";
rename.textContent = "Rename";
rename.addEventListener("click", () => openRename(entry));
actionGroup.append(rename);
}
if (actionGroup.childElementCount === 0) {
const unavailable = document.createElement("span");
unavailable.className = "file-unavailable";
unavailable.textContent = entry.kind === "file" ? "Over limit" : entry.kind === "symlink" ? "Symlink" : entry.kind === "directory" ? "Open folder" : "Unavailable";
actionGroup.append(unavailable);
}
actionCell.append(actionGroup);
row.append(nameCell, sizeCell, ownerCell, modeCell, modifiedCell, actionCell);
rows.append(row);
});
}
function fileKindIcon(kind) {
if (kind === "directory") return "▱";
if (kind === "file") return "▤";
if (kind === "symlink") return "↗";
return "◇";
}
function formatTimestamp(value) {
const date = new Date(value);
return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}
function formatBytes(value) {
let size = Number(value) || 0;
const units = ["B", "KB", "MB", "GB", "TB"];
let index = 0;
while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}
function formatDuration(seconds) {
const days = Math.floor(seconds / 86400);
const hours = Math.floor((seconds % 86400) / 3600);
const minutes = Math.floor((seconds % 3600) / 60);
if (days) return `${days}d ${hours}h`;
if (hours) return `${hours}h ${minutes}m`;
return `${minutes}m`;
}
function openDialog(selector) {
const dialog = $(selector);
if (!dialog.open) dialog.showModal();
}
function closeDialog(dialog) {
if (dialog?.open) dialog.close();
}
async function openEditor(path) {
clearError("#file-error");
try {
const data = await request(`api/v1/files/text?path=${encodeURIComponent(path)}`);
state.editorPath = data.path;
state.editorHash = data.sha256;
$("#editor-path").textContent = data.path;
$("#editor-content").value = data.content;
clearError("#editor-error");
openDialog("#editor-dialog");
$("#editor-content").focus();
} catch (error) {
showError("#file-error", error.message);
}
}
function openRename(entry) {
state.renamePath = entry.path;
state.renameOldName = entry.name;
$("#rename-source-path").textContent = entry.path;
$("#rename-name-input").value = entry.name;
clearError("#rename-error");
openDialog("#rename-dialog");
$("#rename-name-input").focus();
$("#rename-name-input").select();
}
function openCopy(entry) {
state.copyPath = entry.path;
state.copyName = entry.name;
$("#copy-source-path").textContent = entry.path;
$("#copy-destination-input").value = state.currentPath;
$("#copy-name-input").value = entry.name;
clearError("#copy-error");
openDialog("#copy-dialog");
$("#copy-destination-input").focus();
$("#copy-destination-input").select();
}
function openMove(entry) {
state.movePath = entry.path;
state.moveName = entry.name;
$("#move-source-path").textContent = entry.path;
$("#move-destination-input").value = state.currentPath;
$("#move-name-input").value = entry.name;
clearError("#move-error");
openDialog("#move-dialog");
$("#move-destination-input").focus();
$("#move-destination-input").select();
}
function arrayBufferToBase64(buffer) {
const bytes = new Uint8Array(buffer);
const chunkSize = 0x8000;
let binary = "";
for (let offset = 0; offset < bytes.length; offset += chunkSize) {
binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
}
return btoa(binary);
}
$("#update-button").addEventListener("click", applyAvailableUpdate);
$("#refresh-button").addEventListener("click", () => {
if (state.currentView === "files") loadFiles(state.currentPath);
else refreshDashboard();
});
$("#menu-button").addEventListener("click", () => $(".sidebar").classList.toggle("open"));
document.querySelectorAll("[data-view]").forEach((link) => {
link.addEventListener("click", (event) => {
event.preventDefault();
const hash = `#${link.dataset.view}`;
if (window.location.hash === hash) switchView(link.dataset.view);
else window.location.hash = hash;
});
});
document.addEventListener("visibilitychange", () => {
if (document.hidden) stopDashboardLive();
else if (state.user && state.currentView === "overview") refreshDashboard(true).finally(scheduleDashboardLive);
});
window.addEventListener("hashchange", () => {
if (state.user) switchView(window.location.hash === "#files" ? "files" : "overview");
});
$("#file-path-form").addEventListener("submit", (event) => {
event.preventDefault();
loadFiles($("#file-path-input").value.trim());
});
$("#file-up-button").addEventListener("click", () => {
if (state.currentPath === "/") return;
const parts = state.currentPath.split("/").filter(Boolean);
parts.pop();
loadFiles(`/${parts.join("/")}`);
});
$("#new-folder-button").addEventListener("click", () => {
$("#folder-parent-path").textContent = state.currentPath;
$("#folder-form").reset();
clearError("#folder-error");
openDialog("#folder-dialog");
$("#folder-name-input").focus();
});
$("#upload-button").addEventListener("click", () => {
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
});
$("#folder-form").addEventListener("submit", async (event) => {
event.preventDefault();
const form = event.currentTarget;
clearError("#folder-error");
setBusy(form, true);
try {
await request("api/v1/files/directory", {
method: "POST",
body: JSON.stringify({ directory: state.currentPath, name: $("#folder-name-input").value })
});
closeDialog($("#folder-dialog"));
await loadFiles(state.currentPath);
} catch (error) {
showError("#folder-error", error.message);
} finally {
setBusy(form, false);
}
});
$("#upload-form").addEventListener("submit", async (event) => {
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
});
$("#rename-form").addEventListener("submit", async (event) => {
event.preventDefault();
const form = event.currentTarget;
clearError("#rename-error");
setBusy(form, true);
try {
const data = await request("api/v1/files/rename", {
method: "POST",
body: JSON.stringify({ path: state.renamePath, new_name: $("#rename-name-input").value })
});
state.renamePath = data.path || "";
state.renameOldName = data.name || "";
closeDialog($("#rename-dialog"));
await loadFiles(state.currentPath);
} catch (error) {
showError("#rename-error", error.message);
} finally {
setBusy(form, false);
}
});
$("#copy-form").addEventListener("submit", async (event) => {
event.preventDefault();
const form = event.currentTarget;
clearError("#copy-error");
setBusy(form, true);
try {
const data = await request("api/v1/files/copy", {
method: "POST",
body: JSON.stringify({ path: state.copyPath, destination_directory: $("#copy-destination-input").value.trim(), name: $("#copy-name-input").value })
});
state.copyPath = data.path || "";
state.copyName = data.name || "";
closeDialog($("#copy-dialog"));
await loadFiles(state.currentPath);
} catch (error) {
showError("#copy-error", error.message);
} finally {
setBusy(form, false);
}
});
$("#move-form").addEventListener("submit", async (event) => {
event.preventDefault();
const form = event.currentTarget;
clearError("#move-error");
setBusy(form, true);
try {
const data = await request("api/v1/files/move", {
method: "POST",
body: JSON.stringify({ path: state.movePath, destination_directory: $("#move-destination-input").value.trim(), name: $("#move-name-input").value })
});
state.movePath = data.path || "";
state.moveName = data.name || "";
closeDialog($("#move-dialog"));
await loadFiles(state.currentPath);
} catch (error) {
showError("#move-error", error.message);
} finally {
setBusy(form, false);
}
});
$("#editor-form").addEventListener("submit", async (event) => {
event.preventDefault();
const form = event.currentTarget;
clearError("#editor-error");
setBusy(form, true);
try {
const data = await request("api/v1/files/text", {
method: "PUT",
body: JSON.stringify({ path: state.editorPath, content: $("#editor-content").value, expected_sha256: state.editorHash })
});
state.editorHash = data.sha256;
closeDialog($("#editor-dialog"));
await loadFiles(state.currentPath);
} catch (error) {
showError("#editor-error", error.message);
} finally {
setBusy(form, false);
}
});
document.querySelectorAll("[data-close-dialog]").forEach((button) => {
button.addEventListener("click", () => closeDialog(button.closest("dialog")));
});
const userMenuButton = $("#user-menu-button");
const userMenu = $("#user-menu");
function setUserMenu(open) {
userMenu.hidden = !open;
userMenuButton.setAttribute("aria-expanded", open ? "true" : "false");
}
userMenuButton.addEventListener("click", (event) => {
event.stopPropagation();
setUserMenu(userMenu.hidden);
});
document.addEventListener("click", (event) => {
if (!event.target.closest(".user-menu")) setUserMenu(false);
});
document.addEventListener("keydown", (event) => {
if (event.key === "Escape") setUserMenu(false);
});
$("#logout-button").addEventListener("click", async () => {
setUserMenu(false);
try { await request("api/v1/auth/logout", { method: "POST" }); } catch (_) { /* local logout still proceeds */ }
state.user = null;
stopDashboardLive();
showLogin();
});
start();
