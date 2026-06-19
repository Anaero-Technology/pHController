#!/usr/bin/env bash
#
# One-time setup on a Raspberry Pi (Raspberry Pi OS / Debian Bookworm).
# Run from the project root:  sudo bash deploy/install.sh
#
# It: installs system deps + Comitup, creates the Python venv, builds the web
# UI (if Node is present, else expects a prebuilt web/dist), and installs the
# systemd service + Comitup config.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-pi}"
echo "==> project: $PROJECT_DIR   user: $SERVICE_USER"

echo "==> apt deps"
apt-get update
apt-get install -y python3-venv python3-pip git

echo "==> hostname  (so the Pi shows up as 'pHController' in the Fing app / router device list)"
hostnamectl set-hostname pHController || true
# keep /etc/hosts in sync so the name resolves locally (avoids sudo warnings)
if grep -q '^127\.0\.1\.1' /etc/hosts; then
  sed -i 's/^127\.0\.1\.1.*/127.0.1.1\tpHController/' /etc/hosts
else
  printf '127.0.1.1\tpHController\n' >> /etc/hosts
fi

echo "==> Comitup (Wi-Fi onboarding)"
# Comitup ships from its own apt repo. See https://davesteele.github.io/comitup/
if ! command -v comitup >/dev/null 2>&1; then
  curl -sL https://davesteele.github.io/comitup/deb/davesteele-comitup-apt-source_latest.deb \
       -o /tmp/comitup-apt-source.deb
  dpkg -i /tmp/comitup-apt-source.deb || true
  apt-get update
  apt-get install -y comitup
  # Comitup needs NetworkManager and conflicts with dhcpcd/wpa_supplicant mgmt.
  echo "    (review Comitup docs: it disables dhcpcd and uses NetworkManager)"
fi

echo "==> python venv + deps"
sudo -u "$SERVICE_USER" python3 -m venv "$PROJECT_DIR/.venv"
sudo -u "$SERVICE_USER" "$PROJECT_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$SERVICE_USER" "$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

echo "==> build web UI"
if command -v npm >/dev/null 2>&1; then
  sudo -u "$SERVICE_USER" bash -c "cd '$PROJECT_DIR/web' && npm install && npm run build"
else
  echo "    npm not found; expecting a prebuilt $PROJECT_DIR/web/dist (build it on a dev machine)."
fi

echo "==> install configs"
chmod +x "$PROJECT_DIR/deploy/wait-online.sh"
install -m 644 "$PROJECT_DIR/deploy/comitup.conf" /etc/comitup.conf
# render the service file for the actual user/path
sed -e "s#/home/pi/pHTest#$PROJECT_DIR#g" -e "s#User=pi#User=$SERVICE_USER#g" \
    "$PROJECT_DIR/deploy/phtest-api.service" > /etc/systemd/system/phtest-api.service

systemctl daemon-reload
systemctl enable comitup comitup-web || true
systemctl enable phtest-api.service
echo "==> done. Reboot to start Comitup onboarding."
echo "    After joining Wi-Fi, open the UI at the Pi's IP. The IP is printed in the service log:"
echo "        journalctl -u phtest-api -b | grep 'pH Controller UI'"
echo "    and the Pi appears as 'pHController' in the Fing app or your router's device list."
