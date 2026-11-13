# Installing the pH controller on a Raspberry Pi

From a blank SD card to a running controller.

**You need**

- A Raspberry Pi with an Ethernet port (and Wi-Fi, if you want it wireless
  later), its power supply and a microSD card of 16 GB or more
- A computer with an SD card reader and an Ethernet port (or USB adapter)
- Internet access for the Pi during the install only: a router or network
  socket to plug it into, or a Wi-Fi network
- The two syringe pumps on their USB-serial adapters, and the HMI

## 1. Flash the SD card

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) and choose
**Raspberry Pi OS Lite (64-bit)**, Bookworm or newer. Older releases do not use
NetworkManager and the installer will refuse them.

In the Imager's customisation settings, before writing:

| Setting | Value |
|---------|-------|
| Username and password | Your choice. The controller runs as this user. Write them down. |
| SSH | **Enabled**, password authentication |
| Wireless LAN country | Your country (e.g. `GB`). Needed even if you only use Wi-Fi later. |
| Wireless LAN network | Only if Wi-Fi is how the Pi gets internet for the install. Otherwise leave it empty. |
| Hostname | Anything; the installer changes it to `phcontroller`. |

## 2. Get the Pi online and log in

Put the card in the Pi, plug its Ethernet port into your router or a network
socket (skip this if you set up Wi-Fi in step 1) and power it on. Give it two
minutes for the first boot, then from your computer:

```bash
ssh <username>@<hostname>.local
```

using the username and hostname from step 1. If the name does not resolve,
look up the Pi's IP address in your router's device list and use that instead.

No network socket to hand? A monitor and keyboard on the Pi work just as well
for the next step, as long as the Pi itself has internet.

## 3. Install

On the Pi:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/Anaero-Technology/pHController.git
cd pHController
sudo bash deploy/install.sh
```

Run it as the normal user with `sudo`, as shown, not from a root login: the
service is set up to run as the user who invoked it.

This takes several minutes. It installs Python packages and Node.js, builds the
web UI, configures the network and starts the controller as a service that
comes back on every boot. It finishes with `==> done. The controller is
running.`

Options go in front of `bash`, e.g. `sudo ETH_STATIC_ADDRESS=192.168.2.50/24 bash deploy/install.sh`:

| Option | Effect |
|--------|--------|
| `ETH_STATIC_ADDRESS=192.168.2.50/24` | Give Ethernet a fixed address on the HMI's subnet now, instead of doing it in the web UI in step 5. **Only use this if the Pi is getting its internet over Wi-Fi**: it replaces DHCP on the Ethernet port. |
| `WIFI_COUNTRY=GB` | Set the Wi-Fi country if you did not set one in the Imager |
| `PH_HOSTNAME=phcontroller-lab2` | A different hostname, for a second unit on the same network. Later updates keep it. |

## 4. Check it

Still on the Pi:

```bash
systemctl is-active phcontroller        # should print: active
journalctl -u phcontroller -n 30        # look for the "pH Controller UI:" block of addresses
```

Then open one of those addresses in a browser on the same network, or
`http://phcontroller.local`. You should see the dashboard. The badge in the top
right will say **HMI not connected** until step 5 is done.

The hostname has changed, so later SSH sessions use `ssh <username>@phcontroller.local`.

## 5. Put it in place and connect to it

From here on the Pi does not need internet.

1. Move the Pi to where it will live. Plug in both pumps (USB) and connect the
   HMI to the Pi's Ethernet port. To have a laptop on the same port at the same
   time, put a small network switch between them.
2. Plug your laptop into the Pi (or the switch) and open
   **`http://169.254.50.1`**. This address always works on the Ethernet port;
   your laptop needs no configuration, though it can take up to a minute to
   sort out its own address after you plug in. If the page does not load, turn
   the laptop's Wi-Fi and any VPN off and try again.
3. Open the **Network** tab.
   - **HMI:** the HMI is at `192.168.2.112`, so the Pi needs an address in that
     range. Under Ethernet choose **IP settings → Static address**, enter
     `192.168.2.50`, prefix `24`, leave the gateway empty, **Apply**. The HMI
     link card should turn to *connected* within a minute.
   - **Wi-Fi (optional):** press **Scan**, pick the network, enter the password.
     Once joined, the page shows the Wi-Fi address; the controller is then also
     reachable from that network.

## 6. Tell it which pump is which

The controller identifies each pump by an address stored inside the pump, so it
needs to know which address is the alkaline pump and which is the acid pump.
There is no screen for this in the web UI yet; it is done once with two
commands, from any computer that can reach the controller (replace
`169.254.50.1` with whatever address you are using).

List the pumps it can see:

```bash
curl -X POST http://169.254.50.1/api/pumps/discover
# {"found":{"1":"/dev/ttyUSB0","2":"/dev/ttyUSB1"}}
```

Assign each address to its role:

```bash
curl -X PUT http://169.254.50.1/api/pumps/alkaline -H 'Content-Type: application/json' -d '{"address": 1}'
curl -X PUT http://169.254.50.1/api/pumps/acid     -H 'Content-Type: application/json' -d '{"address": 2}'
```

The **Pumps** panel on the dashboard should now show both as *online*.

If `discover` lists only one address although both pumps are plugged in, the
two pumps share that address. Unplug one, then give the remaining one a new
address and its role in one go. This writes the new address into the pump
permanently:

```bash
curl -X POST http://169.254.50.1/api/pumps/acid/assign -H 'Content-Type: application/json' \
     -d '{"current_address": 1, "new_address": 2}'
```

Plug the other pump back in and assign it to `alkaline` with the `PUT` command above.

## 7. First run

On the dashboard, set each pump's refill valve, then each channel's dose
volume, valve port and limits. The controller starts **disarmed** and in **dry
run** after every boot: arm it with dry run still ticked first and watch
**Recent doses** to confirm it would dose when you expect. Untick dry run when
you are satisfied.

## Updating

With the Pi back on a network with internet:

```bash
cd ~/pHController && git pull && sudo bash deploy/install.sh
```

Network settings, pump assignments and dose settings are kept.

### From a unit that used the Wi-Fi setup hotspot (Comitup)

The same update command migrates it: Comitup and its hotspot are removed, the
old `phtest-api` service is replaced by `phcontroller`, and saved Wi-Fi
networks and an existing static Ethernet address are left alone. Do it over
Ethernet or with a keyboard attached, not while connected through the setup
hotspot, which disappears during the update.

## If something is wrong

| Symptom | What to do |
|---------|-----------|
| Installer stops with *NetworkManager is not running* | The OS is older than Bookworm. Re-flash with a current Raspberry Pi OS. |
| Installer stops at Node.js or `npm ci` | The Pi lost internet, or cannot reach `deb.nodesource.com` / `registry.npmjs.org`. Fix the connection and re-run the installer; it is safe to repeat. |
| `http://169.254.50.1` does not load | Wait a minute after plugging in. Check the laptop's Ethernet adapter has a `169.254.x.x` address, and that Wi-Fi/VPN are off. On the Pi, `ip -4 addr show` should list `169.254.50.1/16` on the Ethernet interface while a cable is connected; if not, re-run `sudo bash deploy/setup_network.sh`. |
| Browser shows *UI not built yet* | The web build did not finish. Re-run the installer. |
| Network tab says the controller *is not allowed to change network settings* | Re-run the installer (it restores the permission for `nmcli`). |
| Wi-Fi shows *unavailable* | No Wi-Fi country is set. `sudo WIFI_COUNTRY=GB bash deploy/setup_network.sh` |
| *HMI not connected* | See the HMI link card on the Network tab: it says whether the Pi lacks an address in the HMI's range or the HMI is not answering. A different HMI address goes in `/etc/default/phcontroller` as `PHTEST_HMI_HOST=http://<address>`, then `sudo systemctl restart phcontroller`. |
| Pumps show *offline* | Check the USB cables, then run the `discover` command from step 6 to see which addresses answer. |
| Anything else | `journalctl -u phcontroller -n 100` shows the controller's log. |
