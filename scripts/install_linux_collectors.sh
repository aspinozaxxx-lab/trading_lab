#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:-/opt/trading_lab}"
storage_root="${2:-/srv/trading_lab_data}"
runtime_default="/opt/trading_lab_runtime/cpython-3.11.4/bin/python3.11"
python_runtime="${TRADING_LAB_PYTHON:-$runtime_default}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "install_linux_collectors.sh must run as root" >&2
  exit 2
fi
if [[ "$repo_root" != "/opt/trading_lab" || "$storage_root" != "/srv/trading_lab_data" ]]; then
  echo "systemd units are pinned to /opt/trading_lab and /srv/trading_lab_data" >&2
  exit 2
fi
if [[ ! -f "$repo_root/pyproject.toml" || ! -d "$repo_root/deploy/systemd" ]]; then
  echo "Trading Lab checkout is incomplete: $repo_root" >&2
  exit 2
fi
if [[ ! -x "$python_runtime" ]]; then
  echo "Python 3.11 runtime is missing: $python_runtime" >&2
  exit 2
fi

if ! getent group trading-lab >/dev/null; then
  groupadd --system trading-lab
fi
if ! id trading-lab >/dev/null 2>&1; then
  useradd --system --gid trading-lab --home-dir /nonexistent --shell /usr/sbin/nologin trading-lab
fi

install -d -m 0750 -o trading-lab -g trading-lab "$storage_root"
for directory in data runs models; do
  install -d -m 0750 -o trading-lab -g trading-lab "$storage_root/$directory"
  if [[ -e "$repo_root/$directory" && ! -L "$repo_root/$directory" ]]; then
    echo "Refusing to replace non-symlink path: $repo_root/$directory" >&2
    exit 2
  fi
  if [[ -L "$repo_root/$directory" ]]; then
    existing_target="$(readlink -f "$repo_root/$directory")"
    expected_target="$(readlink -f "$storage_root/$directory")"
    if [[ "$existing_target" != "$expected_target" ]]; then
      echo "Unexpected symlink target: $repo_root/$directory -> $existing_target" >&2
      exit 2
    fi
  else
    ln -s "$storage_root/$directory" "$repo_root/$directory"
  fi
done

if [[ ! -x "$repo_root/.venv/bin/python" ]]; then
  "$python_runtime" -m venv "$repo_root/.venv"
fi
"$repo_root/.venv/bin/python" -m pip install --disable-pip-version-check -r "$repo_root/requirements.lock" openpyxl==3.1.5
"$repo_root/.venv/bin/python" -m pip install --disable-pip-version-check --no-deps -e "$repo_root"

install -d -m 0750 -o root -g trading-lab /etc/trading-lab
if [[ ! -e /etc/trading-lab/collector.env ]]; then
  install -m 0640 -o root -g trading-lab /dev/null /etc/trading-lab/collector.env
fi

install -m 0644 "$repo_root/deploy/systemd/trading-lab-collector@.service" /etc/systemd/system/
for timer in "$repo_root"/deploy/systemd/trading-lab-*.timer; do
  install -m 0644 "$timer" /etc/systemd/system/
done
systemd-analyze verify /etc/systemd/system/trading-lab-collector@.service \
  /etc/systemd/system/trading-lab-*.timer
systemctl daemon-reload
mapfile -t timer_units < <(
  find "$repo_root/deploy/systemd" -maxdepth 1 -type f -name 'trading-lab-*.timer' \
    -printf '%f\n' | sort
)
systemctl enable --now "${timer_units[@]}"

echo "Installed Trading Lab collectors. Secrets, if authorized, belong only in:"
echo "  /etc/trading-lab/collector.env"
systemctl list-timers --all --no-pager 'trading-lab-*'
