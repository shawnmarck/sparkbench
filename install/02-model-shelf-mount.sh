#!/usr/bin/env bash
# Mount QNAP models share at /mnt/model-shelf (CIFS, fstab, auto on boot)
set -euo pipefail

NAS_IP="192.168.0.99"
SHARE="models"
MOUNT="/mnt/model-shelf"
CREDS="/etc/spark/smb-credentials-models"
FSTAB_MARKER="# spark-model-shelf"
SMB_USER="shawn"

echo "==> Installing SMB client tools (if missing)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq cifs-utils smbclient keyutils

echo "==> Creating mount point ${MOUNT}"
mkdir -p "${MOUNT}"

SECRETS="/home/techno/spark/secrets/nas.env"
if [[ ! -f "${CREDS}" ]]; then
  if [[ -f "${SECRETS}" ]]; then
    # shellcheck disable=SC1090
    set -a && source "${SECRETS}" && set +a
  fi
  if [[ -n "${NAS_PASSWORD:-${SPARK_SMB_PASSWORD:-}}" ]]; then
    SPARK_SMB_PASSWORD="${NAS_PASSWORD:-${SPARK_SMB_PASSWORD}}"
  fi
  if [[ -n "${SPARK_SMB_PASSWORD:-}" ]]; then
    mkdir -p /etc/spark
    umask 077
    cat > "${CREDS}" <<EOF
username=${SMB_USER}
password=${SPARK_SMB_PASSWORD}
domain=WORKGROUP
EOF
    chmod 600 "${CREDS}"
    echo "OK: credentials written to ${CREDS}"
  else
    echo "ERROR: Missing ${CREDS}"
    echo
    echo "Create it (one-time), then re-run this script:"
    echo "  sudo install -m 600 /dev/stdin ${CREDS} <<'EOF'"
    echo "  username=${SMB_USER}"
    echo "  password=YOUR_PASSWORD_HERE"
    echo "  domain=WORKGROUP"
    echo "  EOF"
    echo
    echo "Or run: sudo SPARK_SMB_PASSWORD='...' $0"
    exit 1
  fi
fi

chmod 600 "${CREDS}"

echo "==> Testing SMB share visibility"
if ! smbclient -L "//${NAS_IP}" -A "${CREDS}" 2>/dev/null | grep -qi "${SHARE}"; then
  echo "WARN: share '${SHARE}' not listed via smbclient; attempting mount anyway"
fi

MOUNT_OPTS="credentials=${CREDS},uid=techno,gid=techno,file_mode=0664,dir_mode=0775,iocharset=utf8,vers=3.0,nofail,x-systemd.automount,_netdev"

echo "==> Test mount"
if mountpoint -q "${MOUNT}"; then
  umount "${MOUNT}" || true
fi
mount -t cifs "//${NAS_IP}/${SHARE}" "${MOUNT}" -o "${MOUNT_OPTS}"
touch "${MOUNT}/.spark-write-test" && rm -f "${MOUNT}/.spark-write-test"
echo "OK: read/write test passed"

echo "==> Persist in /etc/fstab"
FSTAB_LINE="//${NAS_IP}/${SHARE} ${MOUNT} cifs ${MOUNT_OPTS} 0 0"
if ! grep -qF "${FSTAB_MARKER}" /etc/fstab; then
  cp /etc/fstab /etc/fstab.bak-spark-"$(date +%Y%m%d-%H%M%S)"
  {
    echo
    echo "${FSTAB_MARKER}"
    echo "${FSTAB_LINE}"
  } >> /etc/fstab
  echo "OK: fstab updated"
else
  echo "OK: fstab entry already present"
fi

echo "==> Enable mount on boot"
systemctl daemon-reload
umount "${MOUNT}" || true
mount "${MOUNT}"
echo "OK: mounted via fstab"

echo
echo "Done."
echo "  Mount: ${MOUNT}"
echo "  NAS:   //${NAS_IP}/${SHARE}"
echo "  Creds: ${CREDS} (root-only)"
df -h "${MOUNT}"
