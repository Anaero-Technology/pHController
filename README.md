# pH Controller

A headless Raspberry Pi appliance that keeps up to eight pH channels inside
their limits. It reads live pH and the min/max thresholds from a Rika RK600-07C
HMI, and when a channel leaves its range it doses from one of two Runze SY-03B
syringe pumps: alkaline when pH is low, acid when it is high. Everything is
operated from a web UI served by the Pi.

```
 laptop ── Ethernet cable ──┐
   http://169.254.50.1      │
                            ▼
 browser on the LAN ──► Raspberry Pi ──► HMI (RK600-07C, socket.io)   192.168.2.112
   http://phcontroller.local   ├─ FastAPI + web UI on port 80
                               ├─ trigger engine (controller.py)
                               └─ USB serial ──► 2 × syringe pump (alkaline / acid)
```

## Connecting to it

The controller has no screen, so the wired port is the way in.

1. **Plug an Ethernet cable from your computer straight into the Pi** and open
   **`http://169.254.50.1`**. This address is fixed and always present on the
   Ethernet port, whatever else is configured. (Your computer needs no setup:
   with no DHCP server on the cable it gives itself a 169.254.x.x address
   within about a minute.)
2. Open the **Network** tab to change anything else:
   - **Ethernet** — automatic (DHCP) or a static address. On a network with
     DHCP the controller gets a normal address as well; the page shows it.
   - **Wi-Fi** (optional) — scan, pick a network, enter the password.
     WPA2-Personal, open networks and WPA-Enterprise (eduroam: username +
     password, PEAP/TTLS) are supported. Joined networks are remembered.
3. On a network, `http://phcontroller.local` also works wherever mDNS does
   (Apple and Windows usually; not all Android devices or guest networks). The
   Network page lists the current IP addresses and each interface's MAC, in
   case you want a DHCP reservation on the router.

**You cannot lock yourself out.** A wrong static address or Wi-Fi setting never
removes `169.254.50.1` from the Ethernet port — plug the cable back in.

### The HMI link

The controller talks to the HMI at `192.168.2.112` by default, so it needs an
address on that subnet. If the HMI is on the Pi's Ethernet side, set
**Network → Ethernet → Static address** to e.g. `192.168.2.50`, prefix `24`,
gateway empty (or pass `ETH_STATIC_ADDRESS=192.168.2.50/24` to the installer).
The static address and `169.254.50.1` share the one port, so a laptop and the
HMI can both be connected through a small unmanaged switch. The Network page
shows whether the HMI is reachable and says what is missing if it is not.

A different HMI address: put `PHTEST_HMI_HOST=http://<address>` in
`/etc/default/phcontroller` and `sudo systemctl restart phcontroller`.

## Install (on the Pi)

**[INSTALL.md](INSTALL.md) is the step-by-step guide**: flashing the SD card,
installing, first connection, HMI and pump setup, updating, troubleshooting.

In short, on Raspberry Pi OS Bookworm or later, with internet:

```bash
git clone https://github.com/Anaero-Technology/pHController.git && cd pHController
sudo bash deploy/install.sh
```

Re-run the same command after a `git pull` to update; it also migrates units
that used the old Comitup setup hotspot.

The installer creates the Python venv, installs Node.js if needed and builds
the UI, runs `deploy/setup_network.sh` and installs the `phcontroller` systemd
service (`journalctl -u phcontroller -f` for logs; every start prints the
addresses the UI answers on).

`setup_network.sh` is the whole network strategy in one place: it sets the
hostname and Avahi (mDNS), puts `169.254.50.1/16` on the Ethernet profile next
to DHCP, and allows the service user to run `nmcli` as root (a sudoers rule
scoped to that one binary) so the UI can apply changes. An Ethernet profile
that already has a static address is left as it is, apart from gaining the
rescue address.

## How dosing works

- Each channel has a **LOW** action (pH below min → alkaline pump) and a
  **HIGH** action (pH above max → acid pump): a volume, the valve port to dose
  through, and an optional repeat interval while the limit stays breached.
- Min/max are the HMI's own thresholds; editing them in the UI writes them to
  the HMI.
- The controller starts **disarmed and in dry-run** after every boot. Arm it,
  and turn dry-run off, from the dashboard. Doses are queued one at a time and
  a queued dose is cancelled if pH recovers first.
- The pumps are identified by their Modbus address (stored in the pump), not by
  serial port, so USB re-enumeration does not swap acid and alkaline. Syringes
  refill automatically from each pump's refill valve.
- Every dose is appended to `api/dose_log.csv` (downloadable from the dashboard).

## Layout

| Path | What |
|------|------|
| `api/app.py` | FastAPI app: channels, controller, pumps; serves `web/dist` |
| `api/network.py` | `/api/network` routes (status, DHCP/static, Wi-Fi scan + join) |
| `netconfig.py` | Network strategy and all `nmcli` calls |
| `hmi.py` | socket.io client for the HMI. **Needs `python-socketio` 4.x** — the HMI is a Socket.IO v2 server and 5.x cannot write to it |
| `controller.py` | Trigger engine and two-pump manager |
| `Pump.py` | Runze SY-03B serial protocol |
| `web/` | Vite + React + TypeScript + Tailwind v4 UI |
| `deploy/` | Installer, network setup, systemd unit |
| `tests/` | pytest suite and a fake `nmcli` |
| `main.py` | Standalone console alarm monitor (optional, independent of the API) |

Runtime state lives in `api/config.json` (pump assignments, dose actions) and
`api/dose_log.csv`; both are created on first use and are not in git.

## Develop

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt

# backend (--reload-exclude keeps config saves from restarting it)
.venv/bin/uvicorn api.app:app --reload --reload-exclude "*.json" --port 8000
# frontend, hot reload, proxies /api to :8000
cd web && npm ci && npm run dev          # http://localhost:5173
```

On a machine without NetworkManager the Network tab just says so. To work on
it anyway, put the fake `nmcli` first on `PATH` when starting the backend; it
simulates an Ethernet port, a Wi-Fi adapter and a few networks (password for
`LabNet` is `correct-horse`), keeping its state in `/tmp/fake-nm-state.json`:

```bash
PATH="$PWD/tests/devbin:$PATH" .venv/bin/uvicorn api.app:app --port 8000
```

Tests (no hardware needed; they drive `netconfig.py`, the API and
`deploy/setup_network.sh` against the fake `nmcli`):

```bash
.venv/bin/python -m pytest tests
```

## Things to know

- **There is no login.** Anyone who can reach the UI can arm dosing and change
  network settings. Keep the controller on a trusted network.
- Traffic is plain HTTP, including a Wi-Fi password while you submit it. Saved
  passwords are never sent back to the browser.
