"""
Network configuration for the pH controller appliance, built on nmcli.

Strategy (the same one the Chimera Flask app uses):

  * The appliance is headless, so the wired port is the way in. The Ethernet
    profile always carries a fixed link-local "rescue" address
    (RESCUE_ADDRESS) next to whatever else is configured. Plug a laptop
    straight into the Pi and http://169.254.50.1 answers -- no DHCP server, no
    screen, no setup hotspot.
  * Ethernet otherwise runs DHCP (with a short timeout, so a direct cable
    doesn't stall) or a static address chosen in the web UI.
  * Wi-Fi is optional and is joined from the web UI once you are in over the
    cable (WPA-PSK, WPA-Enterprise / eduroam, or open).

Because the rescue address survives every Ethernet mode, a bad static address
or a wrong Wi-Fi password can never lock anyone out: the cable still works.

Reads use plain `nmcli`; anything that changes state goes through
`sudo -n nmcli` (deploy/setup_network.sh installs a sudoers rule scoped to
exactly that binary). Terse-output parsing is adapted from Opentrons' nmcli
wrapper (Apache-2.0).

Only NetworkManager is supported. Where there is no `nmcli` (a dev laptop)
every call degrades to "not supported" instead of raising; tests/devbin has a
fake nmcli for working on the Network page without a Pi.
"""
import ipaddress
import re
import shutil
import subprocess
import threading
from typing import Dict, List, Optional, Tuple

# Kept on the Ethernet profile in every mode. deploy/setup_network.sh sets the
# same value -- change both together.
RESCUE_ADDRESS = "169.254.50.1/16"

# PEAP+MSCHAPv2 is the common eduroam setup, but plenty of sites use TTLS+PAP.
VALID_EAP_METHODS = ("peap", "ttls", "pwd")
VALID_PHASE2_METHODS = ("mschapv2", "pap", "chap", "mschap", "md5", "gtc")
DEFAULT_EAP_METHOD = "peap"
DEFAULT_PHASE2 = "mschapv2"

NOT_SUPPORTED = "Network settings can only be changed on the controller itself"

# One reconfiguration at a time: two overlapping `nmcli connection up` calls
# on the same profile leave it in whichever state lost the race.
_mutate_lock = threading.Lock()


# ---------------------------------------------------------------------------
# nmcli plumbing
# ---------------------------------------------------------------------------
def supported() -> bool:
    return shutil.which("nmcli") is not None


def _run(cmd: List[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _nmcli(args: List[str], timeout: float = 10.0,
           privileged: bool = False) -> subprocess.CompletedProcess:
    """Run nmcli. `privileged` routes it through sudo (-n: fail fast instead
    of waiting on a password prompt if the sudoers rule is missing)."""
    cmd = (["sudo", "-n"] if privileged else []) + ["nmcli"] + args
    return _run(cmd, timeout)


def split_terse_fields(line: str) -> List[str]:
    """Split one line of `nmcli -t` output on unescaped colons.

    nmcli escapes ':' as '\\:' and '\\' as '\\\\' in terse mode, so a plain
    line.split(':') corrupts SSIDs and MAC addresses.
    """
    fields: List[str] = []
    current: List[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def _error_text(result: subprocess.CompletedProcess, fallback: str) -> str:
    text = (result.stderr or result.stdout or "").strip()
    if "a password is required" in text or "sudo:" in text:
        return ("The controller is not allowed to change network settings "
                "(sudo rule for nmcli is missing -- re-run deploy/install.sh)")
    # nmcli prefixes everything with "Error: "; the UI adds its own framing.
    return re.sub(r"^Error:\s*", "", text) or fallback


def _key_values(result: subprocess.CompletedProcess) -> Dict[str, List[str]]:
    """Parse `KEY:value` terse lines into {KEY: [values]}. Indexed keys such
    as IP4.ADDRESS[1] / IP4.ADDRESS[2] collapse onto one list."""
    out: Dict[str, List[str]] = {}
    if result.returncode != 0:
        return out
    for line in result.stdout.splitlines():
        fields = split_terse_fields(line)
        if len(fields) < 2:
            continue
        key = re.sub(r"\[\d+\]$", "", fields[0])
        value = ":".join(fields[1:]).strip()
        if value and value != "--":
            out.setdefault(key, []).append(value)
    return out


def _first(values: Dict[str, List[str]], key: str) -> Optional[str]:
    return (values.get(key) or [None])[0]


def _device_show(device: str, fields: str) -> Dict[str, List[str]]:
    return _key_values(_nmcli(["-t", "-f", fields, "device", "show", device], timeout=5))


def _connection_show(uuid: str, fields: str) -> Dict[str, List[str]]:
    return _key_values(_nmcli(["-t", "-f", fields, "connection", "show", uuid], timeout=5))


def _devices() -> List[Tuple[str, str, str, str]]:
    """(device, type, state, connection-name) for every NetworkManager device."""
    result = _nmcli(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"], timeout=5)
    if result.returncode != 0:
        return []
    rows = []
    for line in result.stdout.splitlines():
        fields = split_terse_fields(line)
        if len(fields) >= 4:
            rows.append((fields[0], fields[1], fields[2], fields[3]))
    return rows


def _interface(dev_type: str) -> Optional[str]:
    """Name of the first device of `dev_type` ('ethernet' / 'wifi'). Not
    cached: a USB adapter can come and go, and the lookup is one cheap call."""
    for device, kind, _state, _conn in _devices():
        if kind == dev_type:
            return device
    return None


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def interfaces() -> List[dict]:
    """Live state of the Ethernet and Wi-Fi interfaces for the Network page."""
    if not supported():
        return []
    out = []
    try:
        for device, dev_type, state, connection in _devices():
            if dev_type not in ("ethernet", "wifi"):
                continue
            info = _device_show(
                device, "GENERAL.HWADDR,GENERAL.CON-UUID,IP4.ADDRESS,IP4.GATEWAY")
            uuid = _first(info, "GENERAL.CON-UUID")

            profile: Dict[str, List[str]] = {}
            if uuid:
                fields = "ipv4.method,ipv4.dns"
                if dev_type == "wifi":
                    fields += ",802-11-wireless.ssid"
                profile = _connection_show(uuid, fields)

            dns = []
            for entry in profile.get("ipv4.dns", []):
                dns += [d.strip() for d in entry.split(",") if d.strip()]

            out.append({
                "device": device,
                "type": dev_type,
                "state": state,
                "connection": connection or None,
                "ssid": _first(profile, "802-11-wireless.ssid"),
                "method": _first(profile, "ipv4.method"),
                "addresses": info.get("IP4.ADDRESS", []),
                "gateway": _first(info, "IP4.GATEWAY"),
                "dns": dns,
                "mac": _first(info, "GENERAL.HWADDR"),
            })
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[network] status query failed: {e}")
    return out


def mdns_hostname() -> Optional[str]:
    """The name Avahi is actually announcing, e.g. 'phcontroller.local'.

    Asked from Avahi rather than derived from the system hostname: with two
    controllers on one network Avahi renames the second to
    'phcontroller-2.local', and that is the name that resolves.
    Returns None when Avahi isn't running (then no .local name exists).
    """
    try:
        result = _run(
            ["dbus-send", "--system", "--print-reply=literal",
             "--dest=org.freedesktop.Avahi", "/",
             "org.freedesktop.Avahi.Server.GetHostNameFqdn"],
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    name = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[A-Za-z0-9.-]+", name):
        return None
    return name


def local_addresses() -> List[str]:
    """IPv4 addresses this host answers on, most useful first: wired LAN,
    Wi-Fi, then the link-local rescue address. Works with no default route
    (a direct cable has none), unlike the connect-to-8.8.8.8 trick."""
    try:
        result = _run(["ip", "-4", "-o", "addr", "show", "up"], timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    wired, wifi, link_local = [], [], []
    for line in result.stdout.splitlines():
        # "2: eth0    inet 192.168.1.10/24 brd ... scope global ..."
        match = re.search(r"^\d+:\s+(\S+)\s+inet\s+([\d.]+)/\d+", line)
        if not match:
            continue
        iface, addr = match.group(1), match.group(2)
        if iface == "lo" or addr.startswith("127."):
            continue
        if addr.startswith("169.254."):
            link_local.append(addr)
        elif iface.startswith("wl"):
            wifi.append(addr)
        else:
            wired.append(addr)
    return wired + wifi + link_local


# ---------------------------------------------------------------------------
# IP configuration (DHCP / static)
# ---------------------------------------------------------------------------
def parse_static_config(address: Optional[str], prefix: int = 24,
                        gateway: Optional[str] = None,
                        dns: Optional[List[str]] = None) -> dict:
    """Validate a static IPv4 configuration. Raises ValueError with a message
    fit to show the user; returns the normalised config."""
    if not 1 <= prefix <= 32:
        raise ValueError("Prefix length must be between 1 and 32")

    try:
        addr = ipaddress.IPv4Address((address or "").strip())
    except ValueError:
        raise ValueError("Invalid IP address") from None
    if addr.is_loopback or addr.is_multicast or addr.is_unspecified or addr.is_reserved:
        raise ValueError("IP address must be a usable host address")
    if addr.is_link_local:
        raise ValueError("169.254.x.x is reserved for the built-in direct-cable "
                         "address and cannot be set manually")

    network = ipaddress.IPv4Network(f"{addr}/{prefix}", strict=False)
    if prefix <= 30 and addr in (network.network_address, network.broadcast_address):
        raise ValueError(f"{addr} is the network or broadcast address of "
                         f"{network.with_prefixlen}, not a host address")

    gw = None
    if gateway and gateway.strip():
        try:
            gw = ipaddress.IPv4Address(gateway.strip())
        except ValueError:
            raise ValueError("Invalid gateway address") from None
        if gw not in network:
            raise ValueError(f"Gateway {gw} is not inside {network.with_prefixlen} "
                             f"-- it must be on the same subnet")
        if gw == addr:
            raise ValueError("Gateway cannot be the controller's own address")

    servers = []
    for server in dns or []:
        server = server.strip()
        if not server:
            continue
        try:
            servers.append(str(ipaddress.IPv4Address(server)))
        except ValueError:
            raise ValueError(f"Invalid DNS server address: {server}") from None
    if len(servers) > 3:
        raise ValueError("At most 3 DNS servers are supported")

    return {
        "address": str(addr),
        "prefix": prefix,
        "gateway": str(gw) if gw else None,
        "dns": servers,
    }


def subnet_change_warning(config: dict, iface_type: str,
                          current: Optional[List[dict]] = None) -> str:
    """A warning when the new static address is outside every subnet now live
    on that link: a valid config, but whatever is on the other end (the HMI,
    a laptop, the Wi-Fi router) won't reach it until it moves too.
    Must be computed before applying -- the link state changes afterwards."""
    try:
        ifaces = current if current is not None else interfaces()
        iface = next((i for i in ifaces if i["type"] == iface_type), None)
        if not iface:
            return ""
        on_link = [a for a in iface.get("addresses", []) if not a.startswith("169.254.")]
        if not on_link:
            return ""
        new_net = ipaddress.IPv4Network(
            f"{config['address']}/{config['prefix']}", strict=False)
        if any(ipaddress.IPv4Interface(a).network.overlaps(new_net) for a in on_link):
            return ""
        current_net = ipaddress.IPv4Interface(on_link[0]).network.with_prefixlen
        peer = "whatever is on the cable" if iface_type == "ethernet" else "the Wi-Fi network"
        return (f" Note: {peer} currently uses {current_net} -- "
                f"{config['address']} will not be reachable from it until the "
                f"other side is moved to the new subnet.")
    except (ValueError, KeyError):
        return ""


def _activate(uuid: str, wait_s: int) -> subprocess.CompletedProcess:
    """`nmcli connection up`, bounded by nmcli's own --wait so a slow
    activation comes back as a normal non-zero exit instead of us killing
    sudo mid-flight."""
    return _nmcli(["--wait", str(wait_s), "connection", "up", uuid],
                  timeout=wait_s + 10, privileged=True)


def _ethernet_profile(iface: str) -> Optional[str]:
    """UUID of the Ethernet profile: the one active on `iface`, else the first
    wired profile, else a freshly created one."""
    uuid = _first(_device_show(iface, "GENERAL.CON-UUID"), "GENERAL.CON-UUID")
    if uuid:
        return uuid

    result = _nmcli(["-t", "-f", "UUID,TYPE", "connection", "show"], timeout=5)
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            fields = split_terse_fields(line)
            if len(fields) >= 2 and fields[1] == "802-3-ethernet":
                return fields[0]

    name = f"Ethernet {iface}"
    result = _nmcli(["connection", "add", "type", "ethernet",
                     "con-name", name, "ifname", iface], timeout=10, privileged=True)
    if result.returncode != 0:
        return None
    result = _nmcli(["-t", "-f", "UUID,NAME", "connection", "show"], timeout=5)
    for line in result.stdout.splitlines():
        fields = split_terse_fields(line)
        if len(fields) >= 2 and fields[1] == name:
            return fields[0]
    return None


def set_ip_config(iface_type: str, mode: str, address: Optional[str] = None,
                  prefix: Optional[int] = None, gateway: Optional[str] = None,
                  dns: Optional[List[str]] = None) -> Tuple[bool, str]:
    """Switch the wired or Wi-Fi interface between DHCP and a static address.

    Ethernet keeps the rescue address in both modes. Wi-Fi settings belong to
    the currently joined network's profile (each network remembers its own)
    and have no rescue address -- the cable is the way back in.
    Re-activates the profile, which briefly drops that link.
    """
    if not supported():
        return False, NOT_SUPPORTED
    if mode not in ("dhcp", "static"):
        return False, f"Unknown mode '{mode}'"

    try:
        with _mutate_lock:
            if iface_type == "ethernet":
                iface = _interface("ethernet")
                if not iface:
                    return False, "No Ethernet adapter found"
                uuid = _ethernet_profile(iface)
                if not uuid:
                    return False, "No Ethernet connection profile found"
                rescue = RESCUE_ADDRESS
            elif iface_type == "wifi":
                iface = _interface("wifi")
                if not iface:
                    return False, "No Wi-Fi adapter found"
                uuid = _first(_device_show(iface, "GENERAL.CON-UUID"), "GENERAL.CON-UUID")
                if not uuid:
                    return False, "Join a Wi-Fi network first, then set its IP settings"
                rescue = None
            else:
                return False, f"Unknown interface type '{iface_type}'"

            if mode == "static":
                addresses = f"{address}/{prefix}" + (f",{rescue}" if rescue else "")
                props = [
                    "ipv4.method", "manual",
                    "ipv4.addresses", addresses,
                    "ipv4.gateway", gateway or "",
                    "ipv4.dns", ",".join(dns or []),
                ]
            else:
                props = [
                    "ipv4.method", "auto",
                    "ipv4.addresses", rescue or "",
                    "ipv4.gateway", "",
                    "ipv4.dns", "",
                ]
                if iface_type == "ethernet":
                    # No DHCP server on a direct cable: give up quickly, and
                    # let IPv6 link-local hold the connection up so the rescue
                    # address stays put instead of flapping with each retry.
                    props += ["ipv4.dhcp-timeout", "30", "ipv4.may-fail", "yes",
                              "ipv6.method", "link-local"]

            result = _nmcli(["connection", "modify", uuid] + props,
                            timeout=15, privileged=True)
            if result.returncode != 0:
                return False, _error_text(result, "Failed to update the connection profile")

            result = _activate(uuid, 40)
            if result.returncode != 0:
                # e.g. the cable is unplugged: the profile is stored and takes
                # effect the next time the link comes up.
                return False, ("Settings saved, but they could not be activated now: "
                               + _error_text(result, "activation failed"))
            return True, "Network configuration applied"
    except subprocess.TimeoutExpired:
        return False, "Timed out applying the network configuration"
    except OSError as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Wi-Fi
# ---------------------------------------------------------------------------
def _to_int(text: str, default: int = -1) -> int:
    try:
        return int(text)
    except (TypeError, ValueError):
        return default


def scan_networks(rescan: bool = True) -> Tuple[List[dict], Optional[str]]:
    """Visible Wi-Fi networks, one entry per SSID (strongest access point),
    the joined network first. Returns (networks, error_message)."""
    if not supported():
        return [], NOT_SUPPORTED
    try:
        if not _interface("wifi"):
            return [], "No Wi-Fi adapter found"

        if rescan:
            # Best effort: NetworkManager refuses a rescan when one just ran.
            try:
                _nmcli(["dev", "wifi", "rescan"], timeout=8, privileged=True)
            except subprocess.TimeoutExpired:
                pass

        result = _nmcli(["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
                        timeout=15)
        if result.returncode != 0:
            return [], _error_text(result, "Wi-Fi scan failed")

        best: Dict[str, dict] = {}
        for line in result.stdout.splitlines():
            fields = split_terse_fields(line)
            if len(fields) < 4 or not fields[1]:
                continue  # hidden network (empty SSID)
            security = fields[3].strip()
            net = {
                "ssid": fields[1],
                "signal": _to_int(fields[2]),  # percent, 0-100
                "security": security or "Open",
                "open": security in ("", "--"),
                "enterprise": "802.1X" in security,
                "connected": fields[0].strip() == "*",
            }
            seen = best.get(net["ssid"])
            if seen is not None:
                # several access points share the SSID: keep the strongest
                net["connected"] = net["connected"] or seen["connected"]
                if seen["signal"] >= net["signal"]:
                    seen["connected"] = net["connected"]
                    continue
            best[net["ssid"]] = net

        networks = sorted(best.values(), key=lambda n: (not n["connected"], -n["signal"]))
        return networks, None
    except subprocess.TimeoutExpired:
        return [], "Wi-Fi scan timed out"
    except OSError as e:
        return [], str(e)


def _wifi_profile_for(ssid: str) -> Optional[str]:
    """UUID of a saved (client-mode) Wi-Fi profile for `ssid`, matched on the
    profile's real SSID rather than its display name -- profiles written by
    Raspberry Pi Imager or an earlier tool are named differently."""
    result = _nmcli(["-t", "-f", "UUID,TYPE", "connection", "show"], timeout=5)
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        fields = split_terse_fields(line)
        if len(fields) < 2 or fields[1] != "802-11-wireless":
            continue
        props = _connection_show(fields[0], "802-11-wireless.ssid,802-11-wireless.mode")
        if (_first(props, "802-11-wireless.ssid") == ssid
                and _first(props, "802-11-wireless.mode") != "ap"):
            return fields[0]
    return None


def _is_sae_only(security: str) -> bool:
    """WPA3-Personal with no WPA2 fallback needs key-mgmt 'sae'."""
    tokens = (security or "").upper().split()
    return "WPA3" in tokens and not {"WPA1", "WPA2"} & set(tokens) and "802.1X" not in tokens


def _psk_props(password: str, sae: bool = False) -> List[str]:
    return ["wifi-sec.key-mgmt", "sae" if sae else "wpa-psk", "wifi-sec.psk", password]


def _enterprise_props(username: str, password: str,
                      eap_method: str, phase2: str) -> List[str]:
    """nmcli properties for WPA-Enterprise (802.1X).

    anonymous-identity keeps the realm so eduroam can route the request to
    the home institution without exposing the real identity; system-ca-certs
    uses the distro CA store (recent NetworkManager refuses EAP with no CA
    configuration at all)."""
    props = [
        "wifi-sec.key-mgmt", "wpa-eap",
        "802-1x.eap", eap_method,
        "802-1x.phase2-auth", phase2,
        "802-1x.identity", username,
        "802-1x.password", password,
        "802-1x.system-ca-certs", "yes",
    ]
    if "@" in username:
        realm = username.rsplit("@", 1)[1]
        props += ["802-1x.anonymous-identity", f"anonymous@{realm}"]
    return props


def connect_wifi(ssid: str, password: str = "", username: Optional[str] = None,
                 security: str = "", eap_method: Optional[str] = None,
                 phase2: Optional[str] = None) -> Tuple[bool, str]:
    """Join a Wi-Fi network (WPA-PSK, WPA-Enterprise, or open).

    Enterprise is used when a username is given or the scan reported 802.1X.
    A profile created by a failed attempt is deleted again, so a wrong
    password doesn't leave a broken profile for autoconnect to loop on.
    """
    if not supported():
        return False, NOT_SUPPORTED
    ssid = ssid or ""
    if not ssid or len(ssid.encode()) > 32:
        return False, "Network name (SSID) must be 1-32 bytes"

    is_enterprise = bool(username) or "802.1X" in (security or "")
    if is_enterprise and not username:
        return False, "This network needs a username (WPA-Enterprise / 802.1X)"

    eap_method = (eap_method or DEFAULT_EAP_METHOD).lower()
    phase2 = (phase2 or DEFAULT_PHASE2).lower()
    if eap_method not in VALID_EAP_METHODS:
        return False, f"EAP method must be one of: {', '.join(VALID_EAP_METHODS)}"
    if phase2 not in VALID_PHASE2_METHODS:
        return False, f"Inner authentication must be one of: {', '.join(VALID_PHASE2_METHODS)}"

    if is_enterprise:
        props = _enterprise_props(username, password, eap_method, phase2)
    elif password:
        sae = _is_sae_only(security)
        if not sae and not 8 <= len(password) <= 64:
            return False, "Wi-Fi passwords are 8 to 63 characters long"
        props = _psk_props(password, sae=sae)
    else:
        props = []  # open network

    try:
        with _mutate_lock:
            iface = _interface("wifi")
            if not iface:
                return False, "No Wi-Fi adapter found"

            uuid = _wifi_profile_for(ssid)
            created = False
            if uuid:
                # Drop the old auth settings first: reusing a profile across
                # PSK / enterprise / open would otherwise carry stale
                # wifi-sec / 802-1x properties over from the previous mode.
                result = _nmcli(["connection", "modify", uuid,
                                 "remove", "802-11-wireless-security",
                                 "remove", "802-1x"], timeout=15, privileged=True)
                if result.returncode != 0:
                    return False, _error_text(result, "Failed to reset the saved network")
                if props:
                    result = _nmcli(["connection", "modify", uuid] + props,
                                    timeout=15, privileged=True)
                    if result.returncode != 0:
                        return False, _error_text(result, "Failed to update the saved network")
            else:
                result = _nmcli(["connection", "add", "type", "wifi", "con-name", ssid,
                                 "ifname", iface, "ssid", ssid] + props,
                                timeout=15, privileged=True)
                if result.returncode != 0:
                    return False, _error_text(result, "Failed to save the network")
                created = True
                uuid = _wifi_profile_for(ssid)

            # Enterprise auth makes RADIUS round-trips and can be slow.
            result = _activate(uuid or ssid, 60 if is_enterprise else 30)
            if result.returncode == 0:
                return True, f"Connected to {ssid}"

            if created and uuid:
                try:
                    _nmcli(["connection", "delete", uuid], timeout=10, privileged=True)
                except (OSError, subprocess.TimeoutExpired):
                    pass

            stderr = result.stderr or ""
            if "Secrets were required" in stderr or "passwd-file" in stderr:
                if is_enterprise:
                    return False, ("Authentication failed. Check the username and password; "
                                   "if they are right, this network may need a different "
                                   "EAP method (e.g. TTLS + PAP instead of PEAP + MSCHAPv2).")
                return False, "Incorrect password"
            if "not found" in stderr or "could not be found" in stderr:
                return False, "Network not found. It may be out of range."
            if "Timeout" in stderr:
                return False, "Connection attempt timed out"
            return False, _error_text(result, "Failed to connect")
    except subprocess.TimeoutExpired:
        return False, "Connection attempt timed out"
    except OSError as e:
        return False, str(e)
