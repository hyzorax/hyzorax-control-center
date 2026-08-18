#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PRODUCT="HYZoraX Control Panel"
SUPPORTED_OS_ID="ubuntu"
SUPPORTED_OS_VERSION="24.04"
REPOSITORY="hyzorax/hyzorax-control-center"
RELEASE_BASE="https://github.com/${REPOSITORY}/releases/latest/download"
ARCHIVE_NAME="HYZoraX_Control_Center_Linux_x86_64.tar.gz"
CHECKSUM_NAME="${ARCHIVE_NAME}.sha256"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

if [[ "${EUID}" -ne 0 ]]; then
  fail "Run this installer as root."
fi

if [[ ! -r /etc/os-release ]]; then
  fail "Cannot identify the operating system."
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "${SUPPORTED_OS_ID}" || "${VERSION_ID:-}" != "${SUPPORTED_OS_VERSION}" ]]; then
  fail "${PRODUCT} supports Ubuntu 24.04 LTS only."
fi

machine="$(uname -m)"
case "${machine}" in
  x86_64|amd64) ;;
  *) fail "Unsupported CPU architecture: ${machine}. This release supports Linux x86-64 only." ;;
esac

for command_name in curl sha256sum tar awk install mktemp pgrep; do
  command -v "${command_name}" >/dev/null 2>&1 || fail "Required command is missing: ${command_name}"
done

package_manager_busy() {
  pgrep -x apt-get >/dev/null 2>&1 && return 0
  pgrep -x apt >/dev/null 2>&1 && return 0
  pgrep -x dpkg >/dev/null 2>&1 && return 0
  pgrep -x dpkg-deb >/dev/null 2>&1 && return 0
  pgrep -f '/usr/bin/unattended-upgrade' >/dev/null 2>&1 && return 0
  return 1
}

wait_for_fresh_ubuntu() {
  local waited=0
  local timeout_seconds=900
  local announced=false
  local cloud_state=""

  echo "Checking Ubuntu initialization..."

  if command -v cloud-init >/dev/null 2>&1; then
    cloud_state="$(cloud-init status 2>/dev/null || true)"
    if grep -qi 'status:[[:space:]]*running' <<<"${cloud_state}"; then
      echo "Waiting for cloud initialization to finish..."
      if command -v timeout >/dev/null 2>&1; then
        timeout "${timeout_seconds}" cloud-init status --wait >/dev/null 2>&1 || true
      else
        cloud-init status --wait >/dev/null 2>&1 || true
      fi
    fi
  fi

  while package_manager_busy; do
    if [[ "${announced}" == false ]]; then
      echo "Waiting for Ubuntu package initialization to finish..."
      echo "HYZoraX will continue automatically; no action is required."
      announced=true
    fi

    if (( waited >= timeout_seconds )); then
      fail "Ubuntu package initialization did not finish within ${timeout_seconds} seconds."
    fi

    sleep 5
    waited=$((waited + 5))
  done

  if [[ "${announced}" == true ]]; then
    echo "Ubuntu package manager: ready"
  else
    echo "Ubuntu initialization: ready"
  fi

  # Fresh-image package transactions can trigger a systemd daemon reexec right
  # as apt exits. Let that control-plane activity settle before bootstrap starts
  # its persistent installer worker.
  sleep 3
}

wait_for_fresh_ubuntu

workdir="$(mktemp -d /root/.hyzorax-public-installer.XXXXXX)"
cleanup() {
  rm -rf -- "${workdir}"
}
trap cleanup EXIT

archive_path="${workdir}/${ARCHIVE_NAME}"
checksum_path="${workdir}/${CHECKSUM_NAME}"
extract_dir="${workdir}/extract"
mkdir -p -- "${extract_dir}"

curl_secure() {
  curl \
    --fail \
    --silent \
    --show-error \
    --location \
    --retry 3 \
    --retry-delay 2 \
    --connect-timeout 15 \
    --max-time 600 \
    --proto '=https' \
    --tlsv1.2 \
    "$@"
}

echo "${PRODUCT} installer"
echo "Downloading latest verified release..."
curl_secure --output "${checksum_path}" "${RELEASE_BASE}/${CHECKSUM_NAME}"
curl_secure --output "${archive_path}" "${RELEASE_BASE}/${ARCHIVE_NAME}"

expected_sha="$(awk 'NF {print $1; exit}' "${checksum_path}")"
if [[ ! "${expected_sha}" =~ ^[0-9a-fA-F]{64}$ ]]; then
  fail "Release checksum file is invalid."
fi
actual_sha="$(sha256sum "${archive_path}" | awk '{print $1}')"
if [[ "${actual_sha,,}" != "${expected_sha,,}" ]]; then
  fail "Release archive SHA-256 verification failed."
fi
echo "Outer SHA-256: OK"

# Reject obviously malformed archives before extraction.
# Keep tar separate from any early-exiting parser so `set -o pipefail` cannot
# turn a harmless SIGPIPE into an installer failure.
archive_listing="${workdir}/archive.list"
tar -tzf "${archive_path}" > "${archive_listing}"
archive_root="$(awk -F/ 'NF {print $1; exit}' "${archive_listing}")"
if [[ "${archive_root}" != "hyzorax-control" ]]; then
  fail "Unexpected release archive layout."
fi

tar -xzf "${archive_path}" -C "${extract_dir}"
source_root="${extract_dir}/hyzorax-control"
build_dir="${source_root}/build"

for required in \
  "${build_dir}/SHA256SUMS" \
  "${build_dir}/hyzorax-control" \
  "${build_dir}/hyzorax-control-helper" \
  "${build_dir}/bootstrap.sh"; do
  [[ -f "${required}" ]] || fail "Release is missing required file: ${required##*/}"
done

(
  cd "${build_dir}"
  sha256sum --check --strict SHA256SUMS
)
echo "Internal release checksums: OK"

control_version_output="$("${build_dir}/hyzorax-control" -version)"
helper_version_output="$("${build_dir}/hyzorax-control-helper" -version)"
control_version="$(awk '{print $NF}' <<<"${control_version_output}")"
helper_version="$(awk '{print $NF}' <<<"${helper_version_output}")"

[[ "${control_version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]] || fail "Control binary returned an invalid version."
[[ "${helper_version}" == "${control_version}" ]] || fail "Control/helper version mismatch."

release_dir="/root/hyzorax-releases/v${control_version}"
if [[ -e "${release_dir}" ]]; then
  # Never overwrite a staged release. Reuse it only when its internal checksums
  # are still valid and its binary version matches the downloaded release.
  existing_build="${release_dir}/hyzorax-control/build"
  if [[ ! -f "${existing_build}/SHA256SUMS" || ! -x "${existing_build}/hyzorax-control" ]]; then
    fail "Existing release directory is incomplete: ${release_dir}"
  fi
  (
    cd "${existing_build}"
    sha256sum --check --strict SHA256SUMS >/dev/null
  ) || fail "Existing release directory failed integrity verification: ${release_dir}"
  existing_version="$("${existing_build}/hyzorax-control" -version | awk '{print $NF}')"
  [[ "${existing_version}" == "${control_version}" ]] || fail "Existing release directory contains a different version."
  build_dir="${existing_build}"
  echo "Verified release v${control_version} is already staged; reusing it."
else
  install -d -o root -g root -m 0700 "${release_dir}"
  cp -a "${source_root}" "${release_dir}/hyzorax-control"
  build_dir="${release_dir}/hyzorax-control/build"
  echo "Staged release: ${release_dir}"
fi

echo "Installing ${PRODUCT} v${control_version}..."
cd "${build_dir}"

# Bootstrap prints the branded HYZORAX TLS banner itself. Suppress only noisy
# OpenSSL punctuation/progress lines while preserving real status and errors.
./bootstrap.sh 2>&1 | awk '
  {
    if (length($0) > 80 && $0 !~ /[[:alnum:]_\/:]/ && $0 ~ /[+*]/) next
    if ($0 == "-----") next
    print
    fflush()
  }
'
