#!/usr/bin/env bash
# Ubuntu GitHub runners only. Keep APT's existing signed sources/keyrings;
# avoid waiting per package on a known-unreachable archive route.
set -euo pipefail
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  exit 0
fi
. /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_CODENAME" =~ ^[a-z]+$ ]]
selected=''
# The third archive is the Linux Kernel Archives' Ubuntu mirror:
# https://mirrors.edge.kernel.org/ (Ubuntu entry). APT still authenticates Ubuntu.
for mirror in https://azure.archive.ubuntu.com/ubuntu https://archive.ubuntu.com/ubuntu https://mirrors.edge.kernel.org/ubuntu; do
  if curl --fail --silent --show-error --location --connect-timeout 3 --max-time 5 \
      --max-filesize 1048576 --range 0-255 \
      "$mirror/dists/$VERSION_CODENAME/InRelease" -o /dev/null; then
    selected="$mirror"
    break
  fi
done
if [[ -z "$selected" ]]; then
  echo 'No Ubuntu archive responded within the bounded dependency window' >&2
  exit 1
fi
echo "Media prerequisite archive: $selected"
sudo python3 - "$selected" <<'PY'
from pathlib import Path
import re
import sys

root = Path('/etc/apt')
files = [root / 'sources.list', *root.glob('sources.list.d/*.sources'),
         *root.glob('sources.list.d/*.list'), *root.glob('apt-mirrors*.txt')]
pattern = re.compile(r'https?://(?:(?:[a-z0-9-]+\.)?archive|security)\.ubuntu\.com/ubuntu/?')
for path in files:
    if path.is_file():
        original = path.read_text()
        updated = pattern.sub(sys.argv[1], original)
        if updated != original:
            path.write_text(updated)
PY
apt_options=(-o Acquire::Retries=1 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20)
if [[ -n "${1:-}" ]]; then
  mkdir -p "$1/partial"
  apt_options+=(-o "Dir::Cache::archives=$1")
fi
# An existing cache may already match signed metadata. Refresh only on failure.
timeout 90s sudo apt-get "${apt_options[@]}" install -y --no-install-recommends ffmpeg || {
  timeout 60s sudo apt-get "${apt_options[@]}" update
  timeout 90s sudo apt-get "${apt_options[@]}" install -y --no-install-recommends ffmpeg
}
ffmpeg -version >/dev/null
ffprobe -version >/dev/null
