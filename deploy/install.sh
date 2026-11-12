#!/usr/bin/env bash
#
# Install / update the pH controller on a Raspberry Pi (Raspberry Pi OS
# Bookworm or later). Safe to re-run after a `git pull`.
#
#     sudo bash deploy/install.sh
#
# It installs system packages, creates the Python venv, builds the web UI (if
# Node is present, else expects a prebuilt web/dist), configures networking
# (see setup_network.sh -- its environment options work here too, e.g.
# `sudo ETH_STATIC_ADDRESS=192.168.2.50/24 bash deploy/install.sh`), and
# installs + starts the phcontroller systemd service.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "error: run with sudo (sudo bash deploy/install.sh)" >&2
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-pi}"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "error: user '$SERVICE_USER' does not exist. Run via sudo from the account" >&2
  echo "       that should own the service." >&2
  exit 1
fi
echo "==> project: $PROJECT_DIR   user: $SERVICE_USER"

echo "==> apt packages"
apt-get update
apt-get install -y python3-venv python3-pip git avahi-daemon

echo "==> python venv + dependencies"
sudo -u "$SERVICE_USER" python3 -m venv "$PROJECT_DIR/.venv"
sudo -u "$SERVICE_USER" "$PROJECT_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

echo "==> web UI"
if command -v npm >/dev/null 2>&1; then
  sudo -u "$SERVICE_USER" bash -c "cd '$PROJECT_DIR/web' && npm ci && npm run build"
elif [ -f "$PROJECT_DIR/web/dist/index.html" ]; then
  echo "    npm not found; using the prebuilt web/dist"
else
  echo "    warning: npm not found and web/dist is missing. Build it on another" >&2
  echo "             machine (cd web && npm ci && npm run build) and copy web/dist over." >&2
fi

echo "==> serial access for the pumps"
usermod -aG dialout "$SERVICE_USER"

bash "$PROJECT_DIR/deploy/setup_network.sh" "$SERVICE_USER"

echo "==> systemd service"
# The service used to be called phtest-api and was started/stopped by Comitup.
if [ -f /etc/systemd/system/phtest-api.service ]; then
  systemctl disable --now phtest-api.service 2>/dev/null || true
  rm -f /etc/systemd/system/phtest-api.service
fi
sed -e "s#__PROJECT_DIR__#$PROJECT_DIR#g" -e "s#__SERVICE_USER__#$SERVICE_USER#g" \
    "$PROJECT_DIR/deploy/phcontroller.service" > /etc/systemd/system/phcontroller.service
systemctl daemon-reload
systemctl enable phcontroller.service
systemctl restart phcontroller.service

echo
echo "==> done. The controller is running."
echo "    Plug an Ethernet cable from a laptop into the Pi and open  http://169.254.50.1"
echo "    Wi-Fi and fixed addresses are set from the UI's Network page."
echo "    Logs: journalctl -u phcontroller -f"
