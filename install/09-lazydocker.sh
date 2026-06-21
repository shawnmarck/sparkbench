#!/usr/bin/env bash
# Install lazydocker TUI for Docker on sparky (arm64).
set -euo pipefail

VERSION="0.25.2"
ARCH="Linux_arm64"
TARBALL="lazydocker_${VERSION}_${ARCH}.tar.gz"
BASE_URL="https://github.com/jesseduffield/lazydocker/releases/download/v${VERSION}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

curl -fsSL "${BASE_URL}/checksums.txt" -o "${WORKDIR}/checksums.txt"
curl -fsSL "${BASE_URL}/${TARBALL}" -o "${WORKDIR}/${TARBALL}"

EXPECTED="$(grep "${TARBALL}" "${WORKDIR}/checksums.txt" | awk '{print $1}')"
ACTUAL="$(sha256sum "${WORKDIR}/${TARBALL}" | awk '{print $1}')"
[ "$EXPECTED" = "$ACTUAL" ] || {
  echo "Checksum mismatch for ${TARBALL}" >&2
  exit 1
}

tar -xzf "${WORKDIR}/${TARBALL}" -C "${WORKDIR}"
install -m 755 "${WORKDIR}/lazydocker" /usr/local/bin/lazydocker

echo "OK: lazydocker ${VERSION} installed -> $(command -v lazydocker)"
lazydocker --version