# pH Controller appliance (Raspberry Pi)

Turns the Pi into a headless appliance that:

1. **Onboards to Wi-Fi via Comitup** — on first boot it raises a setup hotspot +
   captive portal; you pick the Wi-Fi network from a phone and it stays
   connected thereafter.
2. **Serves a web UI** (React) once online, where you set each pH channel's
   **min**, **max**, and an **action** (placeholder today; the syringe pump will
   consume it later).
3. **Reads/writes the HMI live** over its socket.io interface (no RS-485 needed
   from the Pi).

## Architecture

```
            Wi-Fi (internet, via Comitup)          Ethernet / local net
 phone/laptop ───────────────► Raspberry Pi ───────────────► HMI (RK600-07C)
   browser                     ├─ FastAPI (api/app.py)  :80     192.168.2.112
   http://pHController.local        ├─ serves web/dist (React UI)
                                ├─ hmi.py  (socket.io v2 client) ── reads pH,
                                │                                   writes min/max
                                └─ config.json (per-channel action)
```

> **Two networks:** the Pi needs **internet** (Wi-Fi, onboarded by Comitup) *and*
> a path to the **HMI** at `192.168.2.112` (typically wired Ethernet onto the
> HMI's subnet — give `eth0` a static `192.168.2.x`). Set a different HMI
> address with the `PHTEST_HMI_HOST` env var (e.g. `http://192.168.2.112`).

## Components

| Path | What |
|------|------|
| `hmi.py` | Shared socket.io client — live pH + read/write thresholds. **Needs `python-socketio==4.x`** (the HMI is a Socket.IO v2 server; v5 can't write). |
| `api/app.py` | FastAPI: `/api/channels`, `PUT /api/channels/{ch}`, serves `web/dist`. |
| `web/` | Vite + React + TS config UI. |
| `deploy/` | Comitup config, systemd unit, installer. |
| `main.py` | Standalone console alarm monitor (optional, separate from the API). |

## Install (on the Pi)

```bash
git clone <repo> /home/pi/pHTest && cd /home/pi/pHTest
sudo bash deploy/install.sh
sudo reboot
```

After reboot: join the **pHController-xxxx** hotspot, pick your Wi-Fi in the
portal. Once connected, open the UI at the Pi's address — see
**[Finding the Pi](#finding-the-pi--giving-it-a-fixed-address)** below.

`install.sh` installs Comitup, creates the venv, installs `requirements.txt`,
builds the UI (needs Node; otherwise build `web/dist` on a dev machine and copy
it over), and installs `/etc/comitup.conf` + the `phtest-api.service` unit.
Comitup's `web_service:` setting starts the app when online and stops it in
config mode.

## Finding the Pi / giving it a fixed address

Comitup gets the Pi onto your Wi-Fi, but the router then assigns it an IP that
can change. mDNS (`pHController.local`) works on Apple/Windows but is flaky on
some networks and Android, so the reliable options are:

**Find the current IP (simple, no command line):**
- From a phone, install **Fing** (free, iOS/Android), scan the Wi-Fi, and tap the
  device named **`pHController`** — it shows the IP (and can open it).
- Or open your **router's admin page → connected devices** and find `pHController`.
- On the Pi itself, the service prints it every boot:
  `journalctl -u phtest-api -b | grep "pH Controller UI"`.

**Make the IP fixed (recommended — set once, bookmark forever):**
A *DHCP reservation* tells the router to always hand the Pi the same IP, with no
config change on the Pi:
1. Find the Pi's IP **and MAC** (any method above; the MAC looks like `b8:27:eb:…`).
2. Log into the router (often `http://192.168.1.1`).
3. Open **DHCP / LAN → "Address Reservation"** (the name varies by router).
4. Select `pHController` (or paste its MAC) and pin it to a free IP, e.g.
   `192.168.1.50`.
5. Reboot the Pi — from then on it's always at `http://192.168.1.50`. Bookmark it.

> Alternative: a **static IP** set on the Pi itself (no router access needed) —
> only suitable if the appliance always lives on the same network. Ask and it can
> be wired into `install.sh`.

## Develop (on a laptop)

```bash
# backend (auto-reload on .py; --reload-exclude keeps config saves from restarting it)
.venv/bin/uvicorn api.app:app --reload --reload-exclude "*.json" --port 8000
# frontend (hot reload, proxies /api -> :8000)
cd web && npm install && npm run dev      # http://localhost:5173
```

Both must run for dev. UI stack: Vite + React + TypeScript + Tailwind CSS v4
(styled to match `../FlaskApp`), with light/dark theme and lucide icons.

Production build: `cd web && npm run build` → FastAPI serves `web/dist` at `/`.

## Notes / next steps

- The **action** is stored in `api/config.json` as a placeholder (`none` / `stop`).
  Wiring it to the pump (`Pump.py`) is the next phase: when a channel trips its
  min/max, run its action.
- The UI polls `/api/channels` every 2 s for live pH and alarm state.
