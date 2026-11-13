#!/usr/bin/env bash
#
# Network setup for the pH controller appliance. Safe to re-run.
# Called by install.sh; can also be run on its own:
#
#     sudo bash deploy/setup_network.sh [service-user]
#
# What it sets up (the same strategy as the Chimera Flask app):
#
#   * Ethernet: DHCP, plus the fixed address 169.254.50.1 that is ALWAYS there.
#     Plug a laptop straight into the Pi and open http://169.254.50.1 -- that
#     is how a headless unit is reached the first time, and how you get back in
#     if any other setting goes wrong.
#   * mDNS (Avahi): http://phcontroller.local on networks that support it.
#   * Lets the service user run `nmcli` as root, so the web UI's Network page
#     can join Wi-Fi and set static addresses.
#   * Removes Comitup (the old Wi-Fi setup hotspot) if it is installed.
#
# Optional environment:
#   PH_HOSTNAME=phcontroller-lab2       mDNS / DHCP hostname (default
#                                       phcontroller; kept on later runs)
#   ETH_STATIC_ADDRESS=192.168.2.50/24  give Ethernet this fixed address instead
#                                       of DHCP (e.g. on the HMI's subnet). Can
#                                       also be done later from the web UI.
#   WIFI_COUNTRY=GB                     regulatory country; Wi-Fi stays blocked
#                                       on Raspberry Pi OS until one is set
set -euo pipefail

# Keep in sync with RESCUE_ADDRESS in netconfig.py.
RESCUE_CIDR="169.254.50.1/16"

# Hostname: an explicit PH_HOSTNAME wins. Otherwise keep a name this script
# set on an earlier run (so updating a unit installed as phcontroller-lab2
# doesn't rename it), and default to phcontroller.
CURRENT_HOSTNAME="$(hostname | tr '[:upper:]' '[:lower:]')"
if [ -n "${PH_HOSTNAME:-}" ]; then
  NEW_HOSTNAME="$PH_HOSTNAME"
elif [[ "$CURRENT_HOSTNAME" == phcontroller* ]]; then
  NEW_HOSTNAME="$CURRENT_HOSTNAME"
else
  NEW_HOSTNAME="phcontroller"
fi
SERVICE_USER="${1:-${SUDO_USER:-pi}}"
ETH_STATIC_ADDRESS="${ETH_STATIC_ADDRESS:-}"

if [ "$(id -u)" -ne 0 ]; then
  echo "error: run as root (sudo bash deploy/setup_network.sh)" >&2
  exit 1
fi
if ! command -v nmcli >/dev/null 2>&1 || ! systemctl is-active --quiet NetworkManager; then
  echo "error: NetworkManager is not running. This appliance needs it (it is the" >&2
  echo "       default on Raspberry Pi OS Bookworm and later)." >&2
  exit 1
fi
if [ -n "$ETH_STATIC_ADDRESS" ] && ! [[ "$ETH_STATIC_ADDRESS" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]]; then
  echo "error: ETH_STATIC_ADDRESS must look like 192.168.2.50/24" >&2
  exit 1
fi

# ---- 1. Comitup (previous Wi-Fi onboarding) -------------------------------
# It must go: in hotspot mode it stops the web service, and it raises a hotspot
# whenever no known Wi-Fi is in range -- which is now the normal case.
if dpkg -s comitup >/dev/null 2>&1 || [ -f /etc/comitup.conf ]; then
  echo "==> removing Comitup"
  systemctl disable --now comitup.service comitup-web.service 2>/dev/null || true
  apt-get purge -y comitup >/dev/null 2>&1 || true
  apt-get purge -y davesteele-comitup-apt-source >/dev/null 2>&1 || true
  rm -f /etc/comitup.conf
  # its setup-hotspot profiles (access-point mode) would otherwise autoconnect
  while IFS=: read -r uuid type; do
    [ "$type" = "802-11-wireless" ] || continue
    if [ "$(nmcli -g 802-11-wireless.mode connection show "$uuid" 2>/dev/null)" = "ap" ]; then
      nmcli connection delete "$uuid" >/dev/null || true
    fi
  done < <(nmcli -t -f UUID,TYPE connection show)
fi

# ---- 2. hostname -----------------------------------------------------------
echo "==> hostname: $NEW_HOSTNAME"
hostnamectl set-hostname "$NEW_HOSTNAME"
# keep /etc/hosts in step so sudo can resolve the name
if grep -q '^127\.0\.1\.1' /etc/hosts; then
  sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$NEW_HOSTNAME/" /etc/hosts
else
  printf '127.0.1.1\t%s\n' "$NEW_HOSTNAME" >> /etc/hosts
fi

# ---- 3. mDNS ---------------------------------------------------------------
echo "==> Avahi (mDNS): http://$NEW_HOSTNAME.local"
if ! command -v avahi-daemon >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq avahi-daemon
fi
AVAHI_CONF=/etc/avahi/avahi-daemon.conf
# IPv4 only: rotating IPv6 privacy addresses make Avahi see its own name as a
# conflict and rename the host (phcontroller-2, -3, ...).
sed -i 's/^use-ipv6=yes/use-ipv6=no/' "$AVAHI_CONF"
sed -i 's/^#deny-interfaces=.*/deny-interfaces=lo/' "$AVAHI_CONF"
sed -i 's/^#publish-aaaa-on-ipv4=yes/publish-aaaa-on-ipv4=no/' "$AVAHI_CONF"
systemctl enable avahi-daemon >/dev/null 2>&1 || true
systemctl restart avahi-daemon

# ---- 4. let the web UI change network settings ----------------------------
if id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "==> sudo rule: $SERVICE_USER may run nmcli"
  rule="$(mktemp)"
  printf '%s ALL=(root) NOPASSWD: %s\n' "$SERVICE_USER" "$(command -v nmcli)" > "$rule"
  if visudo -cf "$rule" >/dev/null; then
    install -m 440 -o root -g root "$rule" /etc/sudoers.d/phcontroller-nmcli
  else
    echo "    warning: could not validate the sudo rule; the Network page will be read-only" >&2
  fi
  rm -f "$rule"
else
  echo "    warning: user '$SERVICE_USER' does not exist; skipping the sudo rule" >&2
fi

# ---- 5. Ethernet profile ---------------------------------------------------
IFACE="$(nmcli -t -f DEVICE,TYPE device | awk -F: '$2=="ethernet"{print $1; exit}')"
if [ -z "$IFACE" ]; then
  echo "    warning: no Ethernet interface found; skipping the wired profile" >&2
else
  UUID="$(nmcli -g GENERAL.CON-UUID device show "$IFACE" 2>/dev/null | tr -d '[:space:]' || true)"
  if [ -z "$UUID" ]; then
    UUID="$(nmcli -t -f UUID,TYPE connection show | awk -F: '$2=="802-3-ethernet"{print $1; exit}')"
  fi
  if [ -z "$UUID" ]; then
    nmcli connection add type ethernet ifname "$IFACE" con-name "Ethernet $IFACE" >/dev/null
    UUID="$(nmcli -g connection.uuid connection show "Ethernet $IFACE")"
  fi

  METHOD="$(nmcli -g ipv4.method connection show "$UUID")"
  if [ -n "$ETH_STATIC_ADDRESS" ]; then
    echo "==> Ethernet ($IFACE): static $ETH_STATIC_ADDRESS + $RESCUE_CIDR"
    nmcli connection modify "$UUID" \
      ipv4.method manual \
      ipv4.addresses "$ETH_STATIC_ADDRESS,$RESCUE_CIDR" \
      ipv4.gateway ""
  elif [ "$METHOD" = "manual" ]; then
    # A static address is already configured (typically the HMI link). Leave
    # it exactly as it is and only make sure the rescue address is present.
    echo "==> Ethernet ($IFACE): keeping the existing static config, adding $RESCUE_CIDR"
    if ! nmcli -g ipv4.addresses connection show "$UUID" | grep -qF "$RESCUE_CIDR"; then
      nmcli connection modify "$UUID" +ipv4.addresses "$RESCUE_CIDR"
    fi
  else
    # DHCP with a short timeout. With no DHCP server (direct cable) IPv4 "fails"
    # but may-fail + IPv6 link-local keep the connection up, so the rescue
    # address stays in place instead of flapping on every retry.
    echo "==> Ethernet ($IFACE): DHCP + $RESCUE_CIDR"
    nmcli connection modify "$UUID" \
      ipv4.method auto \
      ipv4.dhcp-timeout 30 \
      ipv4.may-fail yes \
      ipv6.method link-local
    if ! nmcli -g ipv4.addresses connection show "$UUID" | grep -qF "$RESCUE_CIDR"; then
      nmcli connection modify "$UUID" +ipv4.addresses "$RESCUE_CIDR"
    fi
  fi
  nmcli connection modify "$UUID" connection.autoconnect yes

  # Apply now. `reapply` changes addresses in place (an SSH session over this
  # cable survives); fall back to a full re-activation; neither matters if the
  # cable is unplugged -- the profile applies when it is plugged in.
  nmcli device reapply "$IFACE" >/dev/null 2>&1 \
    || nmcli connection up "$UUID" >/dev/null 2>&1 \
    || true
fi

# ---- 6. Wi-Fi radio --------------------------------------------------------
if [ -n "${WIFI_COUNTRY:-}" ] && command -v raspi-config >/dev/null 2>&1; then
  echo "==> Wi-Fi country: $WIFI_COUNTRY"
  raspi-config nonint do_wifi_country "$WIFI_COUNTRY" || true
fi
if command -v rfkill >/dev/null 2>&1; then
  rfkill unblock wifi || true
fi
nmcli radio wifi on >/dev/null 2>&1 || true
if command -v raspi-config >/dev/null 2>&1 \
   && [ -z "$(raspi-config nonint get_wifi_country 2>/dev/null || true)" ]; then
  echo "    note: no Wi-Fi country is set, so Wi-Fi may stay disabled. Re-run with" >&2
  echo "          WIFI_COUNTRY=GB (your two-letter country code) to enable it." >&2
fi

echo "==> network setup done"
echo "    direct cable : http://${RESCUE_CIDR%/*}"
echo "    on a network : http://$NEW_HOSTNAME.local  (or the address shown on the UI's Network page)"
