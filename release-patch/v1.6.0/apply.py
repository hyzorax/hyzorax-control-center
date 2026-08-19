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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def replace_all(rel, old, new):
    text = read(rel)
    if old not in text:
        raise SystemExit(f"{rel}: marker {old!r} not found")
    write(rel, text.replace(old, new))

manifest_go = r'''package installer

import (
    "errors"
    "fmt"
    "path/filepath"
    "regexp"
    "sort"
    "strings"
)

const ManifestSchemaVersion = 1

var manifestIDPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]{1,63}$`)
var paramKeyPattern = regexp.MustCompile(`^[a-z][a-z0-9_.-]{0,63}$`)

var allowedOperationActions = map[string]struct{}{
    "apt.repository.ensure": {},
    "apt.package.install": {},
    "apt.package.remove": {},
    "service.enable": {},
    "service.disable": {},
    "service.start": {},
    "service.stop": {},
    "service.restart": {},
    "directory.ensure": {},
    "file.template": {},
    "file.remove": {},
    "sysctl.set": {},
}

var allowedCheckKinds = map[string]struct{}{
    "arch": {},
    "disk": {},
    "memory": {},
    "os": {},
    "package_absent": {},
    "path_writable": {},
    "port_free": {},
    "service_absent": {},
}

type OSConstraint struct {
    ID      string `json:"id"`
    Version string `json:"version"`
}

type VersionSpec struct {
    Version    string `json:"version"`
    Default    bool   `json:"default"`
    Repository string `json:"repository,omitempty"`
}

type RepositorySpec struct {
    ID             string `json:"id"`
    Kind           string `json:"kind"`
    Source         string `json:"source"`
    KeyFingerprint string `json:"key_fingerprint,omitempty"`
}

type PortSpec struct {
    Protocol   string `json:"protocol"`
    Port       int    `json:"port"`
    MustBeFree bool   `json:"must_be_free"`
}

type ResourceRequirements struct {
    MinMemoryBytes uint64 `json:"min_memory_bytes,omitempty"`
    MinDiskBytes   uint64 `json:"min_disk_bytes,omitempty"`
}

type CheckSpec struct {
    ID     string            `json:"id"`
    Kind   string            `json:"kind"`
    Params map[string]string `json:"params,omitempty"`
}

type OperationSpec struct {
    ID     string            `json:"id"`
    Action string            `json:"action"`
    Params map[string]string `json:"params,omitempty"`
}

type BackupRequirement struct {
    Path     string `json:"path"`
    Kind     string `json:"kind"`
    Required bool   `json:"required"`
}

type Manifest struct {
    SchemaVersion      int                  `json:"schema_version"`
    ID                 string               `json:"id"`
    Name               string               `json:"name"`
    SupportedOS        []OSConstraint       `json:"supported_os"`
    Versions           []VersionSpec        `json:"versions"`
    Repositories       []RepositorySpec     `json:"repositories,omitempty"`
    Dependencies       []string             `json:"dependencies,omitempty"`
    Conflicts          []string             `json:"conflicts,omitempty"`
    Ports              []PortSpec           `json:"ports,omitempty"`
    Resources          ResourceRequirements `json:"resources,omitempty"`
    Preflight          []CheckSpec          `json:"preflight,omitempty"`
    InstallSteps       []OperationSpec      `json:"install_steps,omitempty"`
    SecureDefaults     []OperationSpec      `json:"secure_defaults,omitempty"`
    HealthChecks       []CheckSpec          `json:"health_checks,omitempty"`
    UpgradeSteps       []OperationSpec      `json:"upgrade_steps,omitempty"`
    UninstallSteps     []OperationSpec      `json:"uninstall_steps,omitempty"`
    RollbackPolicy     string               `json:"rollback_policy"`
    RollbackSteps      []OperationSpec      `json:"rollback_steps,omitempty"`
    BackupRequirements []BackupRequirement  `json:"backup_requirements,omitempty"`
}

func ValidateManifest(manifest Manifest) error {
    if manifest.SchemaVersion != ManifestSchemaVersion {
        return fmt.Errorf("unsupported installer manifest schema version %d", manifest.SchemaVersion)
    }
    if !manifestIDPattern.MatchString(manifest.ID) {
        return fmt.Errorf("invalid installer manifest id %q", manifest.ID)
    }
    if strings.TrimSpace(manifest.Name) == "" {
        return errors.New("installer manifest name is required")
    }
    if len(manifest.SupportedOS) == 0 {
        return errors.New("installer manifest must declare at least one supported OS")
    }
    seenOS := map[string]struct{}{}
    for _, supported := range manifest.SupportedOS {
        if strings.TrimSpace(supported.ID) == "" || strings.TrimSpace(supported.Version) == "" {
            return errors.New("supported OS id and version are required")
        }
        key := strings.ToLower(strings.TrimSpace(supported.ID)) + "\x00" + strings.TrimSpace(supported.Version)
        if _, exists := seenOS[key]; exists {
            return fmt.Errorf("duplicate supported OS %s %s", supported.ID, supported.Version)
        }
        seenOS[key] = struct{}{}
    }
    if len(manifest.Versions) == 0 {
        return errors.New("installer manifest must declare at least one version")
    }
    repositoryIDs := map[string]struct{}{}
    for _, repository := range manifest.Repositories {
        if !manifestIDPattern.MatchString(repository.ID) {
            return fmt.Errorf("invalid repository id %q", repository.ID)
        }
        if repository.Kind != "apt" {
            return fmt.Errorf("unsupported repository kind %q", repository.Kind)
        }
        if err := validateSingleLine("repository source", repository.Source); err != nil {
            return err
        }
        if _, exists := repositoryIDs[repository.ID]; exists {
            return fmt.Errorf("duplicate repository id %q", repository.ID)
        }
        repositoryIDs[repository.ID] = struct{}{}
    }
    versionNames := map[string]struct{}{}
    defaultVersions := 0
    for _, version := range manifest.Versions {
        if err := validateSingleLine("version", version.Version); err != nil {
            return err
        }
        if _, exists := versionNames[version.Version]; exists {
            return fmt.Errorf("duplicate installer version %q", version.Version)
        }
        versionNames[version.Version] = struct{}{}
        if version.Default {
            defaultVersions++
        }
        if version.Repository != "" {
            if _, exists := repositoryIDs[version.Repository]; !exists {
                return fmt.Errorf("version %q references unknown repository %q", version.Version, version.Repository)
            }
        }
    }
    if defaultVersions != 1 {
        return fmt.Errorf("installer manifest must declare exactly one default version; got %d", defaultVersions)
    }
    dependencies, err := validateComponentRefs(manifest.ID, "dependency", manifest.Dependencies)
    if err != nil {
        return err
    }
    conflicts, err := validateComponentRefs(manifest.ID, "conflict", manifest.Conflicts)
    if err != nil {
        return err
    }
    for id := range dependencies {
        if _, exists := conflicts[id]; exists {
            return fmt.Errorf("component %q cannot both depend on and conflict with %q", manifest.ID, id)
        }
    }
    ports := map[string]struct{}{}
    for _, port := range manifest.Ports {
        protocol := strings.ToLower(strings.TrimSpace(port.Protocol))
        if protocol != "tcp" && protocol != "udp" {
            return fmt.Errorf("unsupported port protocol %q", port.Protocol)
        }
        if port.Port < 1 || port.Port > 65535 {
            return fmt.Errorf("invalid %s port %d", protocol, port.Port)
        }
        key := fmt.Sprintf("%s/%d", protocol, port.Port)
        if _, exists := ports[key]; exists {
            return fmt.Errorf("duplicate port requirement %s", key)
        }
        ports[key] = struct{}{}
    }
    if err := validateChecks("preflight", manifest.Preflight); err != nil {
        return err
    }
    if err := validateChecks("health check", manifest.HealthChecks); err != nil {
        return err
    }
    for label, operations := range map[string][]OperationSpec{
        "install": manifest.InstallSteps,
        "secure default": manifest.SecureDefaults,
        "upgrade": manifest.UpgradeSteps,
        "uninstall": manifest.UninstallSteps,
        "rollback": manifest.RollbackSteps,
    } {
        if err := validateOperations(label, operations); err != nil {
            return err
        }
    }
    switch manifest.RollbackPolicy {
    case "required":
        if len(manifest.RollbackSteps) == 0 {
            return errors.New("rollback policy is required but no rollback steps are declared")
        }
    case "best_effort", "none":
    default:
        return fmt.Errorf("unsupported rollback policy %q", manifest.RollbackPolicy)
    }
    for _, backup := range manifest.BackupRequirements {
        if !filepath.IsAbs(backup.Path) || filepath.Clean(backup.Path) != backup.Path {
            return fmt.Errorf("backup requirement path must be clean and absolute: %q", backup.Path)
        }
        if backup.Kind != "file" && backup.Kind != "directory" && backup.Kind != "database" {
            return fmt.Errorf("unsupported backup requirement kind %q", backup.Kind)
        }
    }
    return nil
}

func validateComponentRefs(componentID, label string, refs []string) (map[string]struct{}, error) {
    seen := map[string]struct{}{}
    for _, ref := range refs {
        if !manifestIDPattern.MatchString(ref) {
            return nil, fmt.Errorf("invalid %s component id %q", label, ref)
        }
        if ref == componentID {
            return nil, fmt.Errorf("component %q cannot reference itself as a %s", componentID, label)
        }
        if _, exists := seen[ref]; exists {
            return nil, fmt.Errorf("duplicate %s %q", label, ref)
        }
        seen[ref] = struct{}{}
    }
    return seen, nil
}

func validateChecks(label string, checks []CheckSpec) error {
    seen := map[string]struct{}{}
    for _, check := range checks {
        if !manifestIDPattern.MatchString(check.ID) {
            return fmt.Errorf("invalid %s id %q", label, check.ID)
        }
        if _, exists := allowedCheckKinds[check.Kind]; !exists {
            return fmt.Errorf("unsupported %s kind %q", label, check.Kind)
        }
        if _, exists := seen[check.ID]; exists {
            return fmt.Errorf("duplicate %s id %q", label, check.ID)
        }
        seen[check.ID] = struct{}{}
        if err := validateParams(check.Params); err != nil {
            return fmt.Errorf("%s %q: %w", label, check.ID, err)
        }
    }
    return nil
}

func validateOperations(label string, operations []OperationSpec) error {
    seen := map[string]struct{}{}
    for _, operation := range operations {
        if !manifestIDPattern.MatchString(operation.ID) {
            return fmt.Errorf("invalid %s step id %q", label, operation.ID)
        }
        if _, exists := allowedOperationActions[operation.Action]; !exists {
            return fmt.Errorf("unsupported %s action %q", label, operation.Action)
        }
        if _, exists := seen[operation.ID]; exists {
            return fmt.Errorf("duplicate %s step id %q", label, operation.ID)
        }
        seen[operation.ID] = struct{}{}
        if err := validateParams(operation.Params); err != nil {
            return fmt.Errorf("%s step %q: %w", label, operation.ID, err)
        }
    }
    return nil
}

func validateParams(params map[string]string) error {
    keys := make([]string, 0, len(params))
    for key := range params {
        keys = append(keys, key)
    }
    sort.Strings(keys)
    for _, key := range keys {
        if !paramKeyPattern.MatchString(key) {
            return fmt.Errorf("invalid parameter key %q", key)
        }
        if err := validateSingleLine("parameter value", params[key]); err != nil {
            return fmt.Errorf("parameter %q: %w", key, err)
        }
    }
    return nil
}

func validateSingleLine(label, value string) error {
    if value == "" {
        return fmt.Errorf("%s is required", label)
    }
    if len(value) > 4096 || strings.ContainsAny(value, "\x00\r\n") {
        return fmt.Errorf("%s must be a bounded single-line value", label)
    }
    return nil
}
'''

catalog_go = r'''package installer

import (
    "fmt"
    "sort"
)

type Catalog struct {
    manifests map[string]Manifest
}

func NewCatalog(manifests []Manifest) (*Catalog, error) {
    catalog := &Catalog{manifests: make(map[string]Manifest, len(manifests))}
    for _, manifest := range manifests {
        if err := ValidateManifest(manifest); err != nil {
            return nil, fmt.Errorf("manifest %q: %w", manifest.ID, err)
        }
        if _, exists := catalog.manifests[manifest.ID]; exists {
            return nil, fmt.Errorf("duplicate installer manifest %q", manifest.ID)
        }
        catalog.manifests[manifest.ID] = manifest
    }
    componentCatalog := catalog.componentCatalog()
    for id, manifest := range catalog.manifests {
        for _, dependency := range manifest.Dependencies {
            if _, exists := componentCatalog[dependency]; !exists {
                return nil, fmt.Errorf("manifest %q depends on unknown component %q", id, dependency)
            }
        }
        for _, conflict := range manifest.Conflicts {
            if _, exists := componentCatalog[conflict]; !exists {
                return nil, fmt.Errorf("manifest %q conflicts with unknown component %q", id, conflict)
            }
        }
    }
    return catalog, nil
}

func (c *Catalog) Manifest(id string) (Manifest, bool) {
    manifest, ok := c.manifests[id]
    return manifest, ok
}

func (c *Catalog) IDs() []string {
    ids := make([]string, 0, len(c.manifests))
    for id := range c.manifests {
        ids = append(ids, id)
    }
    sort.Strings(ids)
    return ids
}

func (c *Catalog) BuildPlan(requested []string) (Plan, error) {
    return BuildPlan(c.componentCatalog(), requested)
}

func (c *Catalog) componentCatalog() map[string]Component {
    result := make(map[string]Component, len(c.manifests))
    for id, manifest := range c.manifests {
        result[id] = Component{ID: id, Name: manifest.Name, DependsOn: append([]string(nil), manifest.Dependencies...), Conflicts: append([]string(nil), manifest.Conflicts...)}
    }
    return result
}
'''

preflight_go = r'''package installer

import (
    "fmt"
    "strconv"
    "strings"
)

type PortKey struct {
    Protocol string
    Port     int
}

type SystemFacts struct {
    OSID              string
    OSVersion         string
    Arch              string
    MemoryBytes       uint64
    DiskFreeBytes     uint64
    BusyPorts         map[PortKey]bool
    InstalledPackages map[string]bool
    ActiveServices    map[string]bool
    WritablePaths     map[string]bool
}

type CheckResult struct {
    ID      string `json:"id"`
    Kind    string `json:"kind"`
    Passed  bool   `json:"passed"`
    Message string `json:"message"`
}

type PreflightReport struct {
    Passed  bool          `json:"passed"`
    Results []CheckResult `json:"results"`
}

func RunPreflight(manifest Manifest, facts SystemFacts) (PreflightReport, error) {
    if err := ValidateManifest(manifest); err != nil {
        return PreflightReport{}, err
    }
    report := PreflightReport{Passed: true}
    add := func(result CheckResult) {
        report.Results = append(report.Results, result)
        if !result.Passed {
            report.Passed = false
        }
    }
    osSupported := false
    for _, supported := range manifest.SupportedOS {
        if strings.EqualFold(supported.ID, facts.OSID) && supported.Version == facts.OSVersion {
            osSupported = true
            break
        }
    }
    add(CheckResult{ID: "manifest.os", Kind: "os", Passed: osSupported, Message: fmt.Sprintf("host OS %s %s", facts.OSID, facts.OSVersion)})
    if manifest.Resources.MinMemoryBytes > 0 {
        add(CheckResult{ID: "manifest.memory", Kind: "memory", Passed: facts.MemoryBytes >= manifest.Resources.MinMemoryBytes, Message: fmt.Sprintf("memory %d/%d bytes", facts.MemoryBytes, manifest.Resources.MinMemoryBytes)})
    }
    if manifest.Resources.MinDiskBytes > 0 {
        add(CheckResult{ID: "manifest.disk", Kind: "disk", Passed: facts.DiskFreeBytes >= manifest.Resources.MinDiskBytes, Message: fmt.Sprintf("free disk %d/%d bytes", facts.DiskFreeBytes, manifest.Resources.MinDiskBytes)})
    }
    for _, port := range manifest.Ports {
        if !port.MustBeFree {
            continue
        }
        key := PortKey{Protocol: strings.ToLower(port.Protocol), Port: port.Port}
        add(CheckResult{ID: fmt.Sprintf("manifest.port.%s.%d", key.Protocol, key.Port), Kind: "port_free", Passed: !facts.BusyPorts[key], Message: fmt.Sprintf("%s/%d must be free", key.Protocol, key.Port)})
    }
    for _, check := range manifest.Preflight {
        result, err := evaluateCheck(check, facts)
        if err != nil {
            return PreflightReport{}, err
        }
        add(result)
    }
    return report, nil
}

func evaluateCheck(check CheckSpec, facts SystemFacts) (CheckResult, error) {
    result := CheckResult{ID: check.ID, Kind: check.Kind}
    switch check.Kind {
    case "os":
        id, version := check.Params["id"], check.Params["version"]
        result.Passed = strings.EqualFold(id, facts.OSID) && version == facts.OSVersion
        result.Message = fmt.Sprintf("requires OS %s %s", id, version)
    case "arch":
        value := check.Params["value"]
        result.Passed = value == facts.Arch
        result.Message = fmt.Sprintf("requires architecture %s", value)
    case "memory":
        minimum, err := parseUintParam(check, "min_bytes")
        if err != nil { return CheckResult{}, err }
        result.Passed = facts.MemoryBytes >= minimum
        result.Message = fmt.Sprintf("memory %d/%d bytes", facts.MemoryBytes, minimum)
    case "disk":
        minimum, err := parseUintParam(check, "min_bytes")
        if err != nil { return CheckResult{}, err }
        result.Passed = facts.DiskFreeBytes >= minimum
        result.Message = fmt.Sprintf("free disk %d/%d bytes", facts.DiskFreeBytes, minimum)
    case "port_free":
        port64, err := parseUintParam(check, "port")
        if err != nil || port64 < 1 || port64 > 65535 {
            if err == nil { err = fmt.Errorf("preflight %q has invalid port", check.ID) }
            return CheckResult{}, err
        }
        protocol := strings.ToLower(check.Params["protocol"])
        if protocol != "tcp" && protocol != "udp" { return CheckResult{}, fmt.Errorf("preflight %q has invalid protocol", check.ID) }
        key := PortKey{Protocol: protocol, Port: int(port64)}
        result.Passed = !facts.BusyPorts[key]
        result.Message = fmt.Sprintf("%s/%d must be free", protocol, port64)
    case "package_absent":
        name := check.Params["name"]
        result.Passed = name != "" && !facts.InstalledPackages[name]
        result.Message = fmt.Sprintf("package %s must be absent", name)
    case "service_absent":
        name := check.Params["name"]
        result.Passed = name != "" && !facts.ActiveServices[name]
        result.Message = fmt.Sprintf("service %s must be inactive/absent", name)
    case "path_writable":
        path := check.Params["path"]
        result.Passed = path != "" && facts.WritablePaths[path]
        result.Message = fmt.Sprintf("path %s must be writable", path)
    default:
        return CheckResult{}, fmt.Errorf("unsupported preflight check kind %q", check.Kind)
    }
    return result, nil
}

func parseUintParam(check CheckSpec, key string) (uint64, error) {
    value := check.Params[key]
    parsed, err := strconv.ParseUint(value, 10, 64)
    if err != nil {
        return 0, fmt.Errorf("preflight %q parameter %q is invalid", check.ID, key)
    }
    return parsed, nil
}
'''

job_go = r'''package installer

import (
    "errors"
    "fmt"
    "sync"
    "time"
)

type JobStatus string

const (
    JobQueued          JobStatus = "queued"
    JobPreflight       JobStatus = "preflight"
    JobRunning         JobStatus = "running"
    JobSucceeded       JobStatus = "succeeded"
    JobFailed          JobStatus = "failed"
    JobRollbackPending JobStatus = "rollback_pending"
    JobRolledBack      JobStatus = "rolled_back"
    JobRollbackFailed  JobStatus = "rollback_failed"
)

type RollbackState string

const (
    RollbackNone     RollbackState = "none"
    RollbackPending  RollbackState = "pending"
    RollbackComplete RollbackState = "complete"
    RollbackFailed   RollbackState = "failed"
)

type Job struct {
    ID            string        `json:"id"`
    Action        string        `json:"action"`
    Requested     []string      `json:"requested"`
    Plan          Plan          `json:"plan"`
    Status        JobStatus     `json:"status"`
    CurrentStep   int           `json:"current_step"`
    TotalSteps    int           `json:"total_steps"`
    RollbackState RollbackState `json:"rollback_state"`
    ErrorCode     string        `json:"error_code,omitempty"`
    ErrorMessage  string        `json:"error_message,omitempty"`
    CreatedAt     time.Time     `json:"created_at"`
    StartedAt     *time.Time    `json:"started_at,omitempty"`
    FinishedAt    *time.Time    `json:"finished_at,omitempty"`
    UpdatedAt     time.Time     `json:"updated_at"`
}

func NewJob(id, action string, plan Plan, now time.Time) (Job, error) {
    if id == "" { return Job{}, errors.New("installer job id is required") }
    switch action {
    case "install", "upgrade", "uninstall":
    default:
        return Job{}, fmt.Errorf("unsupported installer job action %q", action)
    }
    if len(plan.Steps) == 0 { return Job{}, errors.New("installer job plan has no steps") }
    return Job{ID: id, Action: action, Requested: append([]string(nil), plan.Requested...), Plan: plan, Status: JobQueued, TotalSteps: len(plan.Steps), RollbackState: RollbackNone, CreatedAt: now.UTC(), UpdatedAt: now.UTC()}, nil
}

func TransitionJob(job Job, next JobStatus, now time.Time, errorCode, errorMessage string) (Job, error) {
    if !CanTransition(job.Status, next) {
        return Job{}, fmt.Errorf("invalid installer job transition %s -> %s", job.Status, next)
    }
    when := now.UTC()
    job.Status = next
    job.UpdatedAt = when
    if next == JobPreflight && job.StartedAt == nil { job.StartedAt = &when }
    if next == JobSucceeded || next == JobFailed || next == JobRolledBack || next == JobRollbackFailed { job.FinishedAt = &when }
    if next == JobRollbackPending { job.RollbackState = RollbackPending }
    if next == JobRolledBack { job.RollbackState = RollbackComplete }
    if next == JobRollbackFailed { job.RollbackState = RollbackFailed }
    job.ErrorCode, job.ErrorMessage = errorCode, errorMessage
    return job, nil
}

func CanTransition(from, to JobStatus) bool {
    allowed := map[JobStatus]map[JobStatus]bool{
        JobQueued: {JobPreflight: true, JobFailed: true},
        JobPreflight: {JobRunning: true, JobFailed: true},
        JobRunning: {JobSucceeded: true, JobFailed: true, JobRollbackPending: true},
        JobFailed: {JobRollbackPending: true},
        JobRollbackPending: {JobRolledBack: true, JobRollbackFailed: true},
    }
    return allowed[from][to]
}

type ProgressEvent struct {
    JobID      string         `json:"job_id"`
    Phase      string         `json:"phase"`
    Level      string         `json:"level"`
    Message    string         `json:"message"`
    Metadata   map[string]any `json:"metadata,omitempty"`
    OccurredAt time.Time      `json:"occurred_at"`
}

type EventBus struct {
    mu         sync.RWMutex
    subscribers map[chan ProgressEvent]struct{}
    buffer     int
}

func NewEventBus(buffer int) *EventBus {
    if buffer < 1 { buffer = 16 }
    return &EventBus{subscribers: map[chan ProgressEvent]struct{}{}, buffer: buffer}
}

func (bus *EventBus) Subscribe() (<-chan ProgressEvent, func()) {
    channel := make(chan ProgressEvent, bus.buffer)
    bus.mu.Lock(); bus.subscribers[channel] = struct{}{}; bus.mu.Unlock()
    var once sync.Once
    cancel := func() { once.Do(func() { bus.mu.Lock(); delete(bus.subscribers, channel); close(channel); bus.mu.Unlock() }) }
    return channel, cancel
}

func (bus *EventBus) Publish(event ProgressEvent) {
    bus.mu.RLock(); defer bus.mu.RUnlock()
    for subscriber := range bus.subscribers {
        select { case subscriber <- event: default: }
    }
}
'''

store_migration_go = r'''package store

func init() {
    migrations = append(migrations, `CREATE TABLE installer_jobs (
        id TEXT PRIMARY KEY,
        action TEXT NOT NULL CHECK (action IN ('install','upgrade','uninstall')),
        requested_json TEXT NOT NULL,
        plan_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('queued','preflight','running','succeeded','failed','rollback_pending','rolled_back','rollback_failed')),
        current_step INTEGER NOT NULL DEFAULT 0,
        total_steps INTEGER NOT NULL,
        rollback_state TEXT NOT NULL CHECK (rollback_state IN ('none','pending','complete','failed')),
        error_code TEXT NOT NULL DEFAULT '',
        error_message TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX installer_jobs_status_idx ON installer_jobs(status);
    CREATE INDEX installer_jobs_created_at_idx ON installer_jobs(created_at);

    CREATE TABLE installer_job_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL REFERENCES installer_jobs(id) ON DELETE CASCADE,
        occurred_at TEXT NOT NULL,
        phase TEXT NOT NULL,
        level TEXT NOT NULL CHECK (level IN ('info','warning','error','success')),
        message TEXT NOT NULL,
        metadata_json TEXT NOT NULL
    );
    CREATE INDEX installer_job_events_job_sequence_idx ON installer_job_events(job_id, sequence);

    CREATE TABLE installed_components (
        component_id TEXT PRIMARY KEY,
        manifest_schema INTEGER NOT NULL,
        manifest_version TEXT NOT NULL,
        installed_version TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('installed','degraded','removing')),
        metadata_json TEXT NOT NULL,
        installed_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );`)
}
'''

store_jobs_go = r'''package store

import (
    "context"
    "database/sql"
    "encoding/json"
    "errors"
    "fmt"
    "time"
)

type InstallerJob struct {
    ID, Action, RequestedJSON, PlanJSON, Status string
    CurrentStep, TotalSteps int
    RollbackState, ErrorCode, ErrorMessage string
    CreatedAt time.Time
    StartedAt, FinishedAt *time.Time
    UpdatedAt time.Time
}

type InstallerJobEvent struct {
    Sequence int64
    JobID string
    OccurredAt time.Time
    Phase, Level, Message string
    Metadata map[string]any
}

type InstallerJobUpdate struct {
    Status string
    CurrentStep int
    RollbackState, ErrorCode, ErrorMessage string
    StartedAt, FinishedAt *time.Time
}

func (s *Store) CreateInstallerJob(ctx context.Context, job InstallerJob) error {
    if job.ID == "" || job.Action == "" || job.Status == "" { return errors.New("installer job identity/action/status are required") }
    if !json.Valid([]byte(job.RequestedJSON)) || !json.Valid([]byte(job.PlanJSON)) { return errors.New("installer job requested/plan JSON must be valid") }
    _, err := s.db.ExecContext(ctx, `INSERT INTO installer_jobs
        (id,action,requested_json,plan_json,status,current_step,total_steps,rollback_state,error_code,error_message,created_at,started_at,finished_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
        job.ID, job.Action, job.RequestedJSON, job.PlanJSON, job.Status, job.CurrentStep, job.TotalSteps, job.RollbackState, job.ErrorCode, job.ErrorMessage,
        formatInstallerTime(job.CreatedAt), nullableInstallerTime(job.StartedAt), nullableInstallerTime(job.FinishedAt), formatInstallerTime(job.UpdatedAt))
    return err
}

func (s *Store) UpdateInstallerJob(ctx context.Context, id string, update InstallerJobUpdate, now time.Time) error {
    result, err := s.db.ExecContext(ctx, `UPDATE installer_jobs SET status=?,current_step=?,rollback_state=?,error_code=?,error_message=?,started_at=?,finished_at=?,updated_at=? WHERE id=?`,
        update.Status, update.CurrentStep, update.RollbackState, update.ErrorCode, update.ErrorMessage, nullableInstallerTime(update.StartedAt), nullableInstallerTime(update.FinishedAt), formatInstallerTime(now), id)
    if err != nil { return err }
    changed, err := result.RowsAffected(); if err != nil { return err }; if changed != 1 { return ErrNotFound }
    return nil
}

func (s *Store) InstallerJob(ctx context.Context, id string) (InstallerJob, error) {
    var job InstallerJob
    var created, updated string
    var started, finished sql.NullString
    err := s.db.QueryRowContext(ctx, `SELECT id,action,requested_json,plan_json,status,current_step,total_steps,rollback_state,error_code,error_message,created_at,started_at,finished_at,updated_at FROM installer_jobs WHERE id=?`, id).Scan(
        &job.ID,&job.Action,&job.RequestedJSON,&job.PlanJSON,&job.Status,&job.CurrentStep,&job.TotalSteps,&job.RollbackState,&job.ErrorCode,&job.ErrorMessage,&created,&started,&finished,&updated)
    if errors.Is(err, sql.ErrNoRows) { return InstallerJob{}, ErrNotFound }; if err != nil { return InstallerJob{}, err }
    job.CreatedAt, err = parseInstallerTime(created); if err != nil { return InstallerJob{}, err }
    job.UpdatedAt, err = parseInstallerTime(updated); if err != nil { return InstallerJob{}, err }
    if started.Valid { value, parseErr := parseInstallerTime(started.String); if parseErr != nil { return InstallerJob{}, parseErr }; job.StartedAt=&value }
    if finished.Valid { value, parseErr := parseInstallerTime(finished.String); if parseErr != nil { return InstallerJob{}, parseErr }; job.FinishedAt=&value }
    return job,nil
}

func (s *Store) AppendInstallerJobEvent(ctx context.Context, event InstallerJobEvent) (int64, error) {
    if event.JobID == "" || event.Phase == "" || event.Level == "" || event.Message == "" { return 0, errors.New("installer job event fields are required") }
    metadata := event.Metadata; if metadata == nil { metadata = map[string]any{} }
    encoded, err := json.Marshal(metadata); if err != nil { return 0, err }
    result, err := s.db.ExecContext(ctx, `INSERT INTO installer_job_events (job_id,occurred_at,phase,level,message,metadata_json) VALUES (?,?,?,?,?,?)`, event.JobID, formatInstallerTime(event.OccurredAt), event.Phase, event.Level, event.Message, string(encoded))
    if err != nil { return 0, err }
    return result.LastInsertId()
}

func (s *Store) InstallerJobEvents(ctx context.Context, jobID string, afterSequence int64, limit int) ([]InstallerJobEvent, error) {
    if limit < 1 || limit > 1000 { limit = 200 }
    rows, err := s.db.QueryContext(ctx, `SELECT sequence,job_id,occurred_at,phase,level,message,metadata_json FROM installer_job_events WHERE job_id=? AND sequence>? ORDER BY sequence ASC LIMIT ?`, jobID, afterSequence, limit)
    if err != nil { return nil, err }; defer rows.Close()
    var events []InstallerJobEvent
    for rows.Next() {
        var event InstallerJobEvent; var occurred, metadata string
        if err := rows.Scan(&event.Sequence,&event.JobID,&occurred,&event.Phase,&event.Level,&event.Message,&metadata); err != nil { return nil, err }
        event.OccurredAt, err = parseInstallerTime(occurred); if err != nil { return nil, err }
        if err := json.Unmarshal([]byte(metadata), &event.Metadata); err != nil { return nil, fmt.Errorf("decode installer event metadata: %w", err) }
        events = append(events,event)
    }
    return events, rows.Err()
}

func formatInstallerTime(value time.Time) string { return value.UTC().Format(time.RFC3339Nano) }
func nullableInstallerTime(value *time.Time) any { if value == nil { return nil }; return formatInstallerTime(*value) }
func parseInstallerTime(value string) (time.Time,error) { return time.Parse(time.RFC3339Nano,value) }
'''

persistence_go = r'''package installer

import (
    "context"
    "encoding/json"
    "fmt"
    "time"

    "github.com/hyzorax/hyzorax-control/internal/store"
)

type DurableTracker struct {
    Store *store.Store
    Bus   *EventBus
}

func (tracker DurableTracker) Create(ctx context.Context, job Job) error {
    if tracker.Store == nil { return fmt.Errorf("installer durable tracker store is required") }
    requested, err := json.Marshal(job.Requested); if err != nil { return err }
    plan, err := json.Marshal(job.Plan); if err != nil { return err }
    return tracker.Store.CreateInstallerJob(ctx, store.InstallerJob{
        ID: job.ID, Action: job.Action, RequestedJSON: string(requested), PlanJSON: string(plan), Status: string(job.Status), CurrentStep: job.CurrentStep, TotalSteps: job.TotalSteps,
        RollbackState: string(job.RollbackState), ErrorCode: job.ErrorCode, ErrorMessage: job.ErrorMessage, CreatedAt: job.CreatedAt, StartedAt: job.StartedAt, FinishedAt: job.FinishedAt, UpdatedAt: job.UpdatedAt,
    })
}

func (tracker DurableTracker) Save(ctx context.Context, job Job) error {
    if tracker.Store == nil { return fmt.Errorf("installer durable tracker store is required") }
    return tracker.Store.UpdateInstallerJob(ctx, job.ID, store.InstallerJobUpdate{Status:string(job.Status),CurrentStep:job.CurrentStep,RollbackState:string(job.RollbackState),ErrorCode:job.ErrorCode,ErrorMessage:job.ErrorMessage,StartedAt:job.StartedAt,FinishedAt:job.FinishedAt},job.UpdatedAt)
}

func (tracker DurableTracker) Load(ctx context.Context, id string) (Job,error) {
    if tracker.Store == nil { return Job{}, fmt.Errorf("installer durable tracker store is required") }
    record, err := tracker.Store.InstallerJob(ctx,id); if err != nil { return Job{},err }
    var requested []string; var plan Plan
    if err := json.Unmarshal([]byte(record.RequestedJSON),&requested); err != nil { return Job{},err }
    if err := json.Unmarshal([]byte(record.PlanJSON),&plan); err != nil { return Job{},err }
    return Job{ID:record.ID,Action:record.Action,Requested:requested,Plan:plan,Status:JobStatus(record.Status),CurrentStep:record.CurrentStep,TotalSteps:record.TotalSteps,RollbackState:RollbackState(record.RollbackState),ErrorCode:record.ErrorCode,ErrorMessage:record.ErrorMessage,CreatedAt:record.CreatedAt,StartedAt:record.StartedAt,FinishedAt:record.FinishedAt,UpdatedAt:record.UpdatedAt},nil
}

func (tracker DurableTracker) Progress(ctx context.Context, event ProgressEvent) error {
    if tracker.Store == nil { return fmt.Errorf("installer durable tracker store is required") }
    if event.OccurredAt.IsZero() { event.OccurredAt = time.Now().UTC() }
    _, err := tracker.Store.AppendInstallerJobEvent(ctx,store.InstallerJobEvent{JobID:event.JobID,OccurredAt:event.OccurredAt,Phase:event.Phase,Level:event.Level,Message:event.Message,Metadata:event.Metadata})
    if err != nil { return err }
    if tracker.Bus != nil { tracker.Bus.Publish(event) }
    return nil
}
'''

manifest_test_go = r'''package installer

import "testing"

func validManifest(id string) Manifest {
    return Manifest{SchemaVersion:ManifestSchemaVersion,ID:id,Name:id,SupportedOS:[]OSConstraint{{ID:"ubuntu",Version:"24.04"}},Versions:[]VersionSpec{{Version:"1.0",Default:true}},RollbackPolicy:"none"}
}

func TestManifestCatalogPlanAndValidation(t *testing.T) {
    runtime := validManifest("runtime"); web := validManifest("web"); web.Dependencies=[]string{"runtime"}
    catalog,err:=NewCatalog([]Manifest{web,runtime});if err!=nil{t.Fatal(err)}
    plan,err:=catalog.BuildPlan([]string{"web"});if err!=nil{t.Fatal(err)}
    if len(plan.Steps)!=2 || plan.Steps[0].ComponentID!="runtime" || plan.Steps[1].ComponentID!="web"{t.Fatalf("unexpected plan: %#v",plan)}
    bad:=validManifest("bad");bad.InstallSteps=[]OperationSpec{{ID:"run",Action:"shell",Params:map[string]string{"command":"curl example | sh"}}}
    if err:=ValidateManifest(bad);err==nil{t.Fatal("free-form shell action was accepted")}
}

func TestManifestRequiresDeterministicVersionAndRollback(t *testing.T){
    manifest:=validManifest("nginx");manifest.Versions=append(manifest.Versions,VersionSpec{Version:"2.0",Default:true})
    if err:=ValidateManifest(manifest);err==nil{t.Fatal("multiple default versions accepted")}
    manifest=validManifest("nginx");manifest.RollbackPolicy="required"
    if err:=ValidateManifest(manifest);err==nil{t.Fatal("required rollback without steps accepted")}
}
'''

preflight_test_go = r'''package installer

import "testing"

func TestRunPreflightReportsResourceAndPortFailures(t *testing.T){
    manifest:=validManifest("nginx");manifest.Resources=ResourceRequirements{MinMemoryBytes:1024,MinDiskBytes:2048};manifest.Ports=[]PortSpec{{Protocol:"tcp",Port:80,MustBeFree:true}}
    report,err:=RunPreflight(manifest,SystemFacts{OSID:"ubuntu",OSVersion:"24.04",Arch:"x86_64",MemoryBytes:512,DiskFreeBytes:4096,BusyPorts:map[PortKey]bool{{Protocol:"tcp",Port:80}:true}})
    if err!=nil{t.Fatal(err)};if report.Passed{t.Fatal("preflight unexpectedly passed")};if len(report.Results)<4{t.Fatalf("missing preflight results: %#v",report.Results)}
}
'''

job_test_go = r'''package installer

import (
    "testing"
    "time"
)

func TestJobTransitionsAndEventBus(t *testing.T){
    now:=time.Unix(100,0).UTC();job,err:=NewJob("job-1","install",Plan{Requested:[]string{"nginx"},Steps:[]Step{{ComponentID:"nginx"}}},now);if err!=nil{t.Fatal(err)}
    job,err=TransitionJob(job,JobPreflight,now.Add(time.Second),"","");if err!=nil{t.Fatal(err)}
    job,err=TransitionJob(job,JobRunning,now.Add(2*time.Second),"","");if err!=nil{t.Fatal(err)}
    job,err=TransitionJob(job,JobRollbackPending,now.Add(3*time.Second),"install_failed","failed");if err!=nil{t.Fatal(err)}
    job,err=TransitionJob(job,JobRolledBack,now.Add(4*time.Second),"install_failed","rolled back");if err!=nil{t.Fatal(err)}
    if job.RollbackState!=RollbackComplete{t.Fatalf("rollback state=%s",job.RollbackState)}
    if _,err:=TransitionJob(job,JobRunning,now,"","");err==nil{t.Fatal("invalid terminal transition accepted")}
    bus:=NewEventBus(2);ch,cancel:=bus.Subscribe();defer cancel();event:=ProgressEvent{JobID:"job-1",Phase:"preflight",Level:"info",Message:"checking"};bus.Publish(event)
    select{case got:=<-ch:if got.Message!="checking"{t.Fatalf("event=%+v",got)};case <-time.After(time.Second):t.Fatal("event bus did not deliver progress")}
}
'''

store_test_go = r'''package store

import (
    "context"
    "path/filepath"
    "testing"
    "time"
)

func TestInstallerJobsPersistProgressAndState(t *testing.T){
    path:=filepath.Join(t.TempDir(),"panel.sqlite");data,err:=Open(path);if err!=nil{t.Fatal(err)}
    now:=time.Unix(1000,0).UTC();job:=InstallerJob{ID:"job-1",Action:"install",RequestedJSON:`["nginx"]`,PlanJSON:`{"requested":["nginx"],"steps":[{"ComponentID":"nginx"}]}`,Status:"queued",TotalSteps:1,RollbackState:"none",CreatedAt:now,UpdatedAt:now}
    if err:=data.CreateInstallerJob(context.Background(),job);err!=nil{t.Fatal(err)}
    if _,err:=data.AppendInstallerJobEvent(context.Background(),InstallerJobEvent{JobID:"job-1",OccurredAt:now,Phase:"preflight",Level:"info",Message:"checking",Metadata:map[string]any{"check":"os"}});err!=nil{t.Fatal(err)}
    started:=now.Add(time.Second);if err:=data.UpdateInstallerJob(context.Background(),"job-1",InstallerJobUpdate{Status:"running",CurrentStep:1,RollbackState:"none",StartedAt:&started},started);err!=nil{t.Fatal(err)}
    data.Close();data,err=Open(path);if err!=nil{t.Fatal(err)};defer data.Close()
    loaded,err:=data.InstallerJob(context.Background(),"job-1");if err!=nil{t.Fatal(err)};if loaded.Status!="running"||loaded.CurrentStep!=1||loaded.StartedAt==nil{t.Fatalf("job not durable: %+v",loaded)}
    events,err:=data.InstallerJobEvents(context.Background(),"job-1",0,10);if err!=nil{t.Fatal(err)};if len(events)!=1||events[0].Metadata["check"]!="os"{t.Fatalf("events=%+v",events)}
}
'''

persistence_test_go = r'''package installer

import (
    "context"
    "path/filepath"
    "testing"
    "time"

    "github.com/hyzorax/hyzorax-control/internal/store"
)

func TestDurableTrackerRoundTrip(t *testing.T){
    data,err:=store.Open(filepath.Join(t.TempDir(),"panel.sqlite"));if err!=nil{t.Fatal(err)};defer data.Close()
    plan:=Plan{Requested:[]string{"nginx"},Steps:[]Step{{ComponentID:"nginx"}}};job,err:=NewJob("job-1","install",plan,time.Unix(1,0));if err!=nil{t.Fatal(err)}
    bus:=NewEventBus(2);tracker:=DurableTracker{Store:data,Bus:bus};if err:=tracker.Create(context.Background(),job);err!=nil{t.Fatal(err)}
    if err:=tracker.Progress(context.Background(),ProgressEvent{JobID:job.ID,Phase:"queued",Level:"info",Message:"queued",OccurredAt:time.Unix(2,0)});err!=nil{t.Fatal(err)}
    loaded,err:=tracker.Load(context.Background(),job.ID);if err!=nil{t.Fatal(err)};if loaded.ID!=job.ID||len(loaded.Plan.Steps)!=1{t.Fatalf("loaded=%+v",loaded)}
}
'''

write("internal/installer/manifest.go", manifest_go)
write("internal/installer/catalog.go", catalog_go)
write("internal/installer/preflight.go", preflight_go)
write("internal/installer/job.go", job_go)
write("internal/installer/persistence.go", persistence_go)
write("internal/installer/manifest_test.go", manifest_test_go)
write("internal/installer/preflight_test.go", preflight_test_go)
write("internal/installer/job_test.go", job_test_go)
write("internal/installer/persistence_test.go", persistence_test_go)
write("internal/store/installer_migration.go", store_migration_go)
write("internal/store/installer_jobs.go", store_jobs_go)
write("internal/store/installer_jobs_test.go", store_test_go)

replace_all("internal/web/static/index.html", "Version 1.5.8", "Version 1.6.0")
replace_all("internal/web/assets_test.go", "1.5.8", "1.6.0")
replace_all("internal/httpapi/app_test.go", "Version 1.5.8", "Version 1.6.0")
print("Applied HYZoraX Control Panel V1.6.0 generic Installer Engine foundation")
