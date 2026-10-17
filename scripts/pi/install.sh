#!/usr/bin/env bash
# Install as the normal Pi user. No disk flashing, network exposure or key in argv.
set -euo pipefail
task_repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
task_state="${XDG_STATE_HOME:-$HOME/.local/state}/LeagueDraftLab"
task_user="$(id -un)"
task_group="$(id -gn)"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != aarch64 || "$(id -u)" == 0 ]]; then
  echo 'Run this as your normal user on Raspberry Pi OS 64-bit (not as root).'
  exit 1
fi
for task_path in "$task_repo" "$task_state" "$task_user" "$task_group"; do
  if [[ ! "$task_path" =~ ^[A-Za-z0-9_./-]+$ ]]; then
    echo 'Use standard Linux paths and user names without spaces or special characters.'
    exit 1
  fi
done
sudo apt-get update
sudo apt-get install -y python3 python3-venv ca-certificates
umask 077
mkdir -p -- "$task_repo/data" "$task_state"
chmod 700 -- "$task_state"
if [[ ! -f "$task_state/.env" ]]; then
  printf '%s\n' 'LOL_REGION=EUW1' 'LOL_QUEUE=420' 'LOL_TARGET_MATCHES=100000' > "$task_state/.env"
fi
chmod 600 -- "$task_state/.env"
python3 -m venv "$task_repo/.collector-venv"
"$task_repo/.collector-venv/bin/python" -m pip install -r "$task_repo/requirements-collector.lock"
"$task_repo/.collector-venv/bin/python" -m pip check
task_unit="$(mktemp)"
trap 'rm -f -- "$task_unit"' EXIT
sed -e "s|@USER@|$task_user|g" -e "s|@GROUP@|$task_group|g" \
    -e "s|@ROOT@|$task_repo|g" -e "s|@STATE@|$task_state|g" \
    "$task_repo/scripts/pi/league-draft-collector.service.in" > "$task_unit"
sudo install -o root -g root -m 644 -- "$task_unit" /etc/systemd/system/league-draft-collector.service
sudo systemctl daemon-reload
sudo timedatectl set-ntp true
sudo systemctl enable league-draft-collector.service
echo 'Service installed and enabled for boot; it has not been started.'
echo 'Import the saved database and configure the private key, then run:'
echo '  sudo systemctl start league-draft-collector.service'
echo '  sudo systemctl status league-draft-collector.service --no-pager'
