#!/usr/bin/env bash
# Ubuntu CI only; preserve APT signatures/keyrings and the existing package cache.
set -euo pipefail
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  exit 0
fi
. /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_CODENAME" =~ ^[a-z]+$ ]]
media_started=$SECONDS
media_budget=255
apt_options=(-o Acquire::Retries=0 -o Acquire::http::Timeout=10 -o Acquire::https::Timeout=10)
if [[ -n "${1:-}" ]]; then
  mkdir -p "$1/partial"
  apt_options+=(-o "Dir::Cache::archives=$1")
fi
run_apt() {
  local stage_budget="$1" remaining
  shift
  remaining=$((media_budget - (SECONDS - media_started)))
  (( remaining > 0 )) || return 124
  if (( remaining < stage_budget )); then stage_budget=$remaining; fi
  timeout "${stage_budget}s" sudo apt-get "${apt_options[@]}" "$@"
}
media_attempt=0
# Index reachability is insufficient: CI43064224036 downloaded many packages
# before an Azure package stalled. On actual failure switch archive, keeping
# completed downloads and Ubuntu authentication, within the same total window.
for mirror in https://azure.archive.ubuntu.com/ubuntu https://mirrors.edge.kernel.org/ubuntu https://archive.ubuntu.com/ubuntu; do
  (( SECONDS - media_started < media_budget )) || break
  if ! curl --fail --silent --show-error --location --connect-timeout 3 --max-time 5 \
      --max-filesize 1048576 --range 0-255 \
      "$mirror/dists/$VERSION_CODENAME/InRelease" -o /dev/null; then
    continue
  fi
  echo "Media prerequisite archive: $mirror"
  sudo python3 - "$mirror" <<'PY'
from pathlib import Path
import re
import sys

root = Path('/etc/apt')
files = [root / 'sources.list', *root.glob('sources.list.d/*.sources'),
         *root.glob('sources.list.d/*.list'), *root.glob('apt-mirrors*.txt')]
pattern = re.compile(r'https?://(?:(?:(?:[a-z0-9-]+\.)?archive|security)\.ubuntu\.com/ubuntu|mirrors\.edge\.kernel\.org/ubuntu)/?')
for path in files:
    if path.is_file():
        original = path.read_text()
        updated = pattern.sub(sys.argv[1], original)
        if updated != original:
            path.write_text(updated)
PY
  if (( media_attempt > 0 )); then
    run_apt 35 update || continue
  fi
  media_attempt=$((media_attempt + 1))
  if run_apt 80 install -y --no-install-recommends ffmpeg; then
    ffmpeg -version >/dev/null
    ffprobe -version >/dev/null
    exit 0
  fi
done
echo 'Media prerequisites unavailable within the bounded signed-archive window' >&2
exit 1
