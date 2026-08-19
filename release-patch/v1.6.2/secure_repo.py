#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv)!=2: raise SystemExit('usage: secure_repo.py <source-root>')
root=Path(sys.argv[1]).resolve()
path=root/'internal/helper/installer_php84_linux.go'
text=path.read_text(encoding='utf-8')
text=text.replace('const php84PPA = "ppa:ondrej/php"\nconst php84RepositoryURL = "ppa.launchpadcontent.net/ondrej/php/ubuntu"\nconst php84RepositoryFingerprint = "B8DC7E53946656EFBCE4C1DD71DAEAAB4AD4CAB6"', '''const php84RepositoryURL = "ppa.launchpadcontent.net/ondrej/php/ubuntu"
const php84RepositoryFingerprint = "B8DC7E53946656EFBCE4C1DD71DAEAAB4AD4CAB6"
const php84KeyURL = "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xB8DC7E53946656EFBCE4C1DD71DAEAAB4AD4CAB6"
const php84KeyringPath = "/etc/apt/keyrings/hyzorax-ondrej-php.gpg"
const php84SourcePath = "/etc/apt/sources.list.d/hyzorax-ondrej-php.sources"''')
text=text.replace('strings.Contains(string(content), php84RepositoryURL) || strings.Contains(string(content), php84PPA)', 'strings.Contains(string(content), php84RepositoryURL)')

prereq_pattern=re.compile(r'func php84AptPrerequisites\(ctx context\.Context\) error \{.*?\n\}',re.DOTALL)
new_prereq=r'''func php84AptPrerequisites(ctx context.Context) error {
    args := []string{"-o", "DPkg::Lock::Timeout=120", "-o", "Acquire::Retries=3", "-y", "--no-install-recommends", "install", "ca-certificates", "curl", "gnupg"}
    command := exec.CommandContext(ctx, "/usr/bin/apt-get", args...)
    command.Env = append(os.Environ(), "DEBIAN_FRONTEND=noninteractive", "NEEDRESTART_MODE=l")
    _, err := command.CombinedOutput()
    return err
}'''
text,count=prereq_pattern.subn(new_prereq,text,count=1)
if count!=1: raise SystemExit('php84AptPrerequisites marker not found')

repo_pattern=re.compile(r'func php84AddRepository\(ctx context\.Context\) error \{.*?\n\}\nfunc php84RemoveRepository\(ctx context\.Context\) error \{.*?\n\}\n\nfunc php84VerifyRepository\(ctx context\.Context\) error \{.*?\n\}',re.DOTALL)
new_repo=r'''func php84AddRepository(ctx context.Context) error {
    if err := os.MkdirAll("/etc/apt/keyrings", 0755); err != nil { return err }
    keyFile, err := os.CreateTemp("", "hyzorax-ondrej-php-key-*.asc")
    if err != nil { return err }
    keyPath := keyFile.Name()
    if err := keyFile.Close(); err != nil { _ = os.Remove(keyPath); return err }
    defer os.Remove(keyPath)
    curl := exec.CommandContext(ctx, "/usr/bin/curl", "--fail", "--silent", "--show-error", "--location", "--retry", "3", "--connect-timeout", "15", "--max-time", "120", "--proto", "=https", "--tlsv1.2", "--output", keyPath, php84KeyURL)
    if output, err := curl.CombinedOutput(); err != nil { return fmt.Errorf("download PHP repository key: %w: %s", err, strings.TrimSpace(string(output))) }
    _ = os.Remove(php84KeyringPath)
    dearmor := exec.CommandContext(ctx, "/usr/bin/gpg", "--batch", "--yes", "--dearmor", "--output", php84KeyringPath, keyPath)
    if output, err := dearmor.CombinedOutput(); err != nil { _ = os.Remove(php84KeyringPath); return fmt.Errorf("dearmor PHP repository key: %w: %s", err, strings.TrimSpace(string(output))) }
    if err := os.Chmod(php84KeyringPath, 0644); err != nil { _ = os.Remove(php84KeyringPath); return err }
    if err := php84VerifyKeyring(ctx); err != nil { _ = os.Remove(php84KeyringPath); return err }
    source := "Types: deb\nURIs: https://ppa.launchpadcontent.net/ondrej/php/ubuntu\nSuites: noble\nComponents: main\nSigned-By: " + php84KeyringPath + "\n"
    temporary := php84SourcePath + ".tmp"
    if err := os.WriteFile(temporary, []byte(source), 0644); err != nil { _ = os.Remove(php84KeyringPath); return err }
    if err := os.Rename(temporary, php84SourcePath); err != nil { _ = os.Remove(temporary); _ = os.Remove(php84KeyringPath); return err }
    return nil
}

func php84RemoveRepository(ctx context.Context) error {
    var first error
    for _, path := range []string{php84SourcePath, php84KeyringPath} {
        if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) && first == nil { first = err }
    }
    return first
}

func php84VerifyKeyring(ctx context.Context) error {
    info, err := os.Stat(php84KeyringPath)
    if err != nil || !info.Mode().IsRegular() { return errors.New("PHP repository keyring is missing") }
    command := exec.CommandContext(ctx, "/usr/bin/gpg", "--batch", "--show-keys", "--with-colons", php84KeyringPath)
    output, err := command.CombinedOutput()
    if err != nil { return fmt.Errorf("inspect PHP repository keyring: %w", err) }
    for _, line := range strings.Split(string(output), "\n") {
        fields := strings.Split(line, ":")
        if len(fields) > 9 && fields[0] == "fpr" && strings.EqualFold(fields[9], php84RepositoryFingerprint) { return nil }
    }
    return errors.New("PHP repository keyring fingerprint does not match the pinned Launchpad fingerprint")
}

func php84VerifyRepository(ctx context.Context) error {
    content, err := os.ReadFile(php84SourcePath)
    if err != nil { return errors.New("HYZoraX PHP repository source is missing") }
    source := string(content)
    if !strings.Contains(source, "URIs: https://ppa.launchpadcontent.net/ondrej/php/ubuntu") || !strings.Contains(source, "Suites: noble") || !strings.Contains(source, "Signed-By: "+php84KeyringPath) { return errors.New("HYZoraX PHP repository source is not the pinned Noble source") }
    return php84VerifyKeyring(ctx)
}'''
text,count=repo_pattern.subn(new_repo,text,count=1)
if count!=1: raise SystemExit(f'repository helper block replacement count={count}')
if 'add-apt-repository' in text or 'php84PPA' in text: raise SystemExit('legacy PPA helper remains')
path.write_text(text,encoding='utf-8')
print('Pinned PHP repository to HYZoraX-managed keyring/source')
