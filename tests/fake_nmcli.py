"""
A small stand-in for NetworkManager's `nmcli`, covering exactly the commands
netconfig.py issues. It models devices, connection profiles and the Wi-Fi
networks "in the air", and re-derives each device's addresses from its profile
on activation -- enough to exercise the real code paths end to end without a
Raspberry Pi.

Two ways to use it:

  * In-process (unit tests): `FakeNM().run(argv)` -> CompletedProcess.
  * As an executable (running the whole app on a dev machine):

        FAKE_NM_STATE=/tmp/nm.json python tests/fake_nmcli.py <nmcli args>

    State persists in that JSON file between invocations. tests/devbin/ holds
    `nmcli` / `sudo` shims that route to it.

It imitates nmcli's terse output format from the documentation; it is not a
substitute for a run on real hardware.
"""
import json
import os
import subprocess
import sys
import uuid as uuidlib

RESCUE = "169.254.50.1/16"


def default_state():
    eth_uuid = "11111111-1111-4111-8111-111111111111"
    return {
        "devices": [
            {"device": "eth0", "type": "ethernet", "state": "connected",
             "uuid": eth_uuid, "hwaddr": "DC:A6:32:01:02:03",
             "addresses": [RESCUE], "gateway": None},
            {"device": "wlan0", "type": "wifi", "state": "disconnected",
             "uuid": None, "hwaddr": "DC:A6:32:01:02:04",
             "addresses": [], "gateway": None},
            {"device": "lo", "type": "loopback", "state": "connected (externally)",
             "uuid": None, "hwaddr": "00:00:00:00:00:00",
             "addresses": ["127.0.0.1/8"], "gateway": None},
        ],
        "connections": {
            eth_uuid: {"name": "Wired connection 1", "type": "802-3-ethernet",
                       "props": {"ipv4.method": "auto", "ipv4.addresses": RESCUE}},
        },
        # what a DHCP server would hand out on each link (None = no server)
        "dhcp": {"eth0": None, "wlan0": {"address": "192.168.1.73/24", "gateway": "192.168.1.1"}},
        "air": [
            {"ssid": "LabNet", "signal": 82, "security": "WPA2", "psk": "correct-horse"},
            {"ssid": "LabNet", "signal": 47, "security": "WPA2", "psk": "correct-horse"},
            {"ssid": "eduroam", "signal": 64, "security": "WPA2 802.1X",
             "identity": "fabio@uni.ac.uk", "password": "s3cret"},
            {"ssid": "Guest: Lobby", "signal": 38, "security": ""},
            {"ssid": "", "signal": 30, "security": "WPA2"},
        ],
        "log": [],
    }


def esc(value):
    return str(value).replace("\\", "\\\\").replace(":", "\\:")


def ok(stdout=""):
    return subprocess.CompletedProcess([], 0, stdout, "")


def fail(stderr, code=10):
    return subprocess.CompletedProcess([], code, "", stderr + "\n")


class FakeNM:
    def __init__(self, state=None):
        self.state = state or default_state()

    # -- helpers --
    def _dev(self, name):
        return next((d for d in self.state["devices"] if d["device"] == name), None)

    def _conn(self, ident):
        conns = self.state["connections"]
        if ident in conns:
            return ident
        return next((u for u, c in conns.items() if c["name"] == ident), None)

    def _derive(self, dev, conn):
        """Addresses a device ends up with after activating `conn`."""
        props = conn["props"]
        static = [a.strip() for a in props.get("ipv4.addresses", "").split(",") if a.strip()]
        if props.get("ipv4.method", "auto") == "manual":
            return static, props.get("ipv4.gateway") or None
        lease = self.state["dhcp"].get(dev["device"])
        if lease:
            return [lease["address"]] + static, lease["gateway"]
        return static, None

    # -- entry point --
    def run(self, argv):
        argv = list(argv)
        self.state["log"].append(argv)
        fields = None
        self.values_only = False        # -g: print values without "KEY:"
        while argv and argv[0].startswith("-"):
            flag = argv.pop(0)
            if flag in ("-f", "-g"):
                fields = argv.pop(0).split(",")
                self.values_only = flag == "-g"
            elif flag == "--wait":
                argv.pop(0)
            # -t (terse) is the only output mode implemented
        if not argv:
            return fail("Error: missing command")
        obj, rest = argv[0], argv[1:]
        if obj in ("device", "dev"):
            return self._device(rest, fields)
        if obj in ("connection", "con"):
            return self._connection(rest, fields)
        if obj == "radio":
            return ok()
        return fail(f"Error: argument '{obj}' not understood")

    def _kv(self, key, value):
        return f"{esc(value)}" if self.values_only else f"{key}:{esc(value)}"

    # -- device --
    def _device(self, rest, fields):
        if not rest or rest[0] == "status":
            lines = []
            for d in self.state["devices"]:
                name = self.state["connections"].get(d["uuid"], {}).get("name", "")
                row = {"DEVICE": d["device"], "TYPE": d["type"],
                       "STATE": d["state"], "CONNECTION": name}
                lines.append(":".join(esc(row[f]) for f in fields))
            return ok("\n".join(lines) + "\n")

        if rest[0] == "show":
            d = self._dev(rest[1])
            if not d:
                return fail(f"Error: Device '{rest[1]}' not found.")
            lines = []
            for f in fields:
                if f == "GENERAL.HWADDR":
                    lines.append(self._kv(f, d["hwaddr"]))
                elif f == "GENERAL.CON-UUID":
                    lines.append(self._kv(f, d["uuid"] or ""))
                elif f == "IP4.ADDRESS":
                    lines += [self._kv(f"{f}[{i + 1}]", a) for i, a in enumerate(d["addresses"])]
                elif f == "IP4.GATEWAY":
                    lines.append(self._kv(f, d["gateway"] or ""))
            return ok("\n".join(lines) + "\n")

        if rest[0] == "wifi":
            if len(rest) > 1 and rest[1] == "rescan":
                return ok()
            wlan = next((d for d in self.state["devices"] if d["type"] == "wifi"), None)
            if not wlan:
                return fail("Error: No Wi-Fi device found.")
            active = self.state["connections"].get(wlan["uuid"] or "", {})
            active_ssid = active.get("props", {}).get("802-11-wireless.ssid")
            lines, marked = [], False
            for net in self.state["air"]:
                in_use = (wlan["state"] == "connected" and net["ssid"] == active_ssid
                          and not marked)
                marked = marked or in_use
                row = {"IN-USE": "*" if in_use else " ", "SSID": net["ssid"],
                       "SIGNAL": net["signal"], "SECURITY": net["security"]}
                lines.append(":".join(esc(row[f]) for f in fields))
            return ok("\n".join(lines) + "\n")

        if rest[0] == "reapply":
            return ok()
        return fail("Error: unsupported device command")

    # -- connection --
    def _connection(self, rest, fields):
        conns = self.state["connections"]
        cmd = rest[0] if rest else "show"

        if cmd == "show" and len(rest) == 1:
            lines = []
            for u, c in conns.items():
                row = {"UUID": u, "NAME": c["name"], "TYPE": c["type"]}
                lines.append(":".join(esc(row[f]) for f in fields))
            return ok("\n".join(lines) + "\n")

        if cmd == "show":
            u = self._conn(rest[1])
            if not u:
                return fail(f"Error: {rest[1]} - no such connection profile.")
            props = dict(conns[u]["props"], **{"connection.uuid": u})
            lines = []
            for f in fields:
                value = props.get(f, "")
                if f in ("ipv4.addresses", "ipv4.dns"):
                    # nmcli prints list properties joined with ", "
                    value = ", ".join(v.strip() for v in value.split(",") if v.strip())
                lines.append(self._kv(f, value))
            return ok("\n".join(lines) + "\n")

        if cmd == "add":
            args = dict(zip(rest[1::2], rest[2::2]))
            u = str(uuidlib.uuid4())
            ctype = {"ethernet": "802-3-ethernet", "wifi": "802-11-wireless"}[args.pop("type")]
            props = {"ipv4.method": "auto"}
            name = args.pop("con-name")
            args.pop("ifname", None)
            if "ssid" in args:
                props["802-11-wireless.ssid"] = args.pop("ssid")
                props["802-11-wireless.mode"] = "infrastructure"
            props.update(args)
            conns[u] = {"name": name, "type": ctype, "props": props}
            return ok(f"Connection '{name}' ({u}) successfully added.\n")

        u = self._conn(rest[1]) if len(rest) > 1 else None
        if not u:
            return fail(f"Error: unknown connection '{rest[1] if len(rest) > 1 else ''}'.")
        conn = conns[u]

        if cmd == "modify":
            args = rest[2:]
            while args:
                key = args.pop(0)
                if key == "remove":
                    setting = args.pop(0)
                    prefix = {"802-11-wireless-security": "wifi-sec."}.get(setting, setting + ".")
                    for k in [k for k in conn["props"] if k.startswith(prefix)]:
                        del conn["props"][k]
                    continue
                value = args.pop(0)
                if key.startswith("+"):
                    old = conn["props"].get(key[1:], "")
                    conn["props"][key[1:]] = f"{old},{value}" if old else value
                else:
                    conn["props"][key] = value
            return ok()

        if cmd == "delete":
            for d in self.state["devices"]:
                if d["uuid"] == u:
                    d.update(uuid=None, state="disconnected", addresses=[], gateway=None)
            del conns[u]
            return ok()

        if cmd == "up":
            kind = "ethernet" if conn["type"] == "802-3-ethernet" else "wifi"
            dev = next(d for d in self.state["devices"] if d["type"] == kind)
            if kind == "wifi":
                problem = self._wifi_auth(conn["props"])
                if problem:
                    return fail(problem, 4)
            addresses, gateway = self._derive(dev, conn)
            dev.update(uuid=u, state="connected", addresses=addresses, gateway=gateway)
            return ok("Connection successfully activated\n")

        return fail("Error: unsupported connection command")

    def _wifi_auth(self, props):
        ssid = props.get("802-11-wireless.ssid")
        net = next((n for n in self.state["air"] if n["ssid"] == ssid), None)
        if not net:
            return ("Error: Connection activation failed: (53) The Wi-Fi network "
                    "could not be found.")
        secrets = "Error: Connection activation failed: (7) Secrets were required, but not provided."
        if "802.1X" in net["security"]:
            good = (props.get("wifi-sec.key-mgmt") == "wpa-eap"
                    and props.get("802-1x.identity") == net["identity"]
                    and props.get("802-1x.password") == net["password"])
            return None if good else secrets
        if net["security"]:
            return None if props.get("wifi-sec.psk") == net["psk"] else secrets
        return None if "wifi-sec.key-mgmt" not in props else secrets


def main():
    path = os.environ.get("FAKE_NM_STATE", "/tmp/fake-nm-state.json")
    try:
        with open(path) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = default_state()
    nm = FakeNM(state)
    result = nm.run(sys.argv[1:])
    with open(path, "w") as f:
        json.dump(nm.state, f, indent=1)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
