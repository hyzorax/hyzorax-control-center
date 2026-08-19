#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: acceptance.py <hyzorax-control-source-root>")
root = Path(sys.argv[1]).resolve()
path = root / "internal/helper/installer_nginx_existing_acceptance_test.go"
path.write_text(r'''//go:build integration && linux

package helper

import (
    "context"
    "os"
    "testing"
    "time"
)

func TestNginxInstallerRejectsExistingInstallation(t *testing.T) {
    if os.Getenv("HYZORAX_INSTALLER_ACCEPTANCE") != "1" { t.Skip("real installer acceptance is opt-in") }
    if os.Geteuid() != 0 { t.Fatal("real installer acceptance must run as root") }
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()
    installed, err := dpkgPackageInstalled(ctx, "nginx")
    if err != nil { t.Fatal(err) }
    if !installed { t.Skip("runner does not have preinstalled Nginx") }
    server := &Server{}
    response := server.dispatch(ctx, Request{Version: ProtocolVersion, ID: "existing-nginx", CorrelationID: "v161-existing", ActorID: "github-actions", Action: "installer.nginx.preflight", Target: "nginx"})
    if response.OK || response.Error == nil || response.Error.Code != "component_exists" {
        t.Fatalf("existing Nginx was not refused safely: %+v", response)
    }
}
''', encoding="utf-8")
print("Added V1.6.1 existing-Nginx refusal acceptance")
