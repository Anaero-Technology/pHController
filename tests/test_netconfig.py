"""netconfig.py against the fake nmcli (see fake_nmcli.py)."""
import pytest

import netconfig
from conftest import WRITES

RESCUE = netconfig.RESCUE_ADDRESS


def iface(kind):
    return next(i for i in netconfig.interfaces() if i["type"] == kind)


# ---- parsing --------------------------------------------------------------
def test_split_terse_fields_respects_escapes():
    assert netconfig.split_terse_fields(r"*:Guest\: Lobby:38:") == ["*", "Guest: Lobby", "38", ""]
    assert netconfig.split_terse_fields(r"a\\b:c") == ["a\\b", "c"]


def test_status_reports_both_interfaces(net):
    eth, wifi = iface("ethernet"), iface("wifi")
    assert eth["device"] == "eth0"
    assert eth["state"] == "connected"
    assert eth["method"] == "auto"
    assert eth["addresses"] == [RESCUE]
    assert eth["mac"] == "DC:A6:32:01:02:03"      # escaped colons restored
    assert eth["gateway"] is None
    assert wifi["state"] == "disconnected"
    assert wifi["addresses"] == [] and wifi["ssid"] is None
    # loopback and friends are not listed
    assert {i["type"] for i in netconfig.interfaces()} == {"ethernet", "wifi"}


def test_mdns_name_comes_from_avahi(net):
    net.avahi_name = "phcontroller-2.local"       # Avahi renamed us after a clash
    assert netconfig.mdns_hostname() == "phcontroller-2.local"
    net.avahi_name = None                         # Avahi not running
    assert netconfig.mdns_hostname() is None


# ---- Ethernet: the rescue address survives every mode ---------------------
def test_static_ethernet_keeps_rescue_address(net):
    ok, msg = netconfig.set_ip_config("ethernet", "static", address="192.168.2.50",
                                      prefix=24, gateway=None, dns=[])
    assert ok, msg
    eth = iface("ethernet")
    assert eth["method"] == "manual"
    assert eth["addresses"] == ["192.168.2.50/24", RESCUE]


def test_back_to_dhcp_keeps_rescue_and_fast_fail_settings(net):
    netconfig.set_ip_config("ethernet", "static", address="10.0.0.5", prefix=8,
                            gateway="10.0.0.1", dns=["10.0.0.1", "1.1.1.1"])
    eth = iface("ethernet")
    assert eth["gateway"] == "10.0.0.1" and eth["dns"] == ["10.0.0.1", "1.1.1.1"]

    ok, _ = netconfig.set_ip_config("ethernet", "dhcp")
    assert ok
    eth = iface("ethernet")
    assert eth["method"] == "auto"
    assert eth["addresses"] == [RESCUE]           # no DHCP server on this link
    assert eth["gateway"] is None and eth["dns"] == []
    props = net.profile(net.device("eth0")["uuid"])
    assert props["ipv4.dhcp-timeout"] == "30"
    assert props["ipv4.may-fail"] == "yes"
    assert props["ipv6.method"] == "link-local"


def test_dhcp_lease_sits_next_to_rescue(net):
    net.nm.state["dhcp"]["eth0"] = {"address": "192.168.1.40/24", "gateway": "192.168.1.1"}
    netconfig.set_ip_config("ethernet", "dhcp")
    eth = iface("ethernet")
    assert eth["addresses"] == ["192.168.1.40/24", RESCUE]
    assert eth["gateway"] == "192.168.1.1"


def test_ethernet_profile_is_created_when_missing(net):
    net.nm.state["connections"].clear()
    net.device("eth0").update(uuid=None, state="disconnected", addresses=[])
    ok, msg = netconfig.set_ip_config("ethernet", "static", address="192.168.2.50",
                                      prefix=24, gateway=None, dns=[])
    assert ok, msg
    assert iface("ethernet")["addresses"] == ["192.168.2.50/24", RESCUE]


def test_wifi_ip_config_needs_a_joined_network_and_has_no_rescue(net):
    ok, msg = netconfig.set_ip_config("wifi", "static", address="192.168.1.9",
                                      prefix=24, gateway=None, dns=[])
    assert not ok and "Join a Wi-Fi network first" in msg

    assert netconfig.connect_wifi("LabNet", "correct-horse", security="WPA2")[0]
    ok, msg = netconfig.set_ip_config("wifi", "static", address="192.168.1.9",
                                      prefix=24, gateway="192.168.1.1", dns=[])
    assert ok, msg
    assert iface("wifi")["addresses"] == ["192.168.1.9/24"]


def test_only_state_changes_use_sudo(net):
    netconfig.interfaces()
    netconfig.scan_networks()
    netconfig.set_ip_config("ethernet", "dhcp")
    netconfig.connect_wifi("LabNet", "correct-horse", security="WPA2")
    for privileged, argv in net.nmcli_calls():
        is_write = any(w in argv for w in WRITES)
        assert privileged == is_write, argv


def test_missing_sudo_rule_is_explained(net):
    net.sudo_allowed = False
    ok, msg = netconfig.set_ip_config("ethernet", "dhcp")
    assert not ok and "re-run deploy/install.sh" in msg


def test_unsupported_platform_degrades_quietly(monkeypatch):
    monkeypatch.setattr(netconfig, "supported", lambda: False)
    assert netconfig.interfaces() == []
    assert netconfig.scan_networks() == ([], netconfig.NOT_SUPPORTED)
    assert netconfig.set_ip_config("ethernet", "dhcp") == (False, netconfig.NOT_SUPPORTED)
    assert netconfig.connect_wifi("x", "password1") == (False, netconfig.NOT_SUPPORTED)


# ---- static config validation ---------------------------------------------
def test_parse_static_config_normalises():
    cfg = netconfig.parse_static_config(" 192.168.2.50 ", 24, "192.168.2.1", ["8.8.8.8", " "])
    assert cfg == {"address": "192.168.2.50", "prefix": 24,
                   "gateway": "192.168.2.1", "dns": ["8.8.8.8"]}
    assert netconfig.parse_static_config("10.1.2.3", 8, "", [])["gateway"] is None


@pytest.mark.parametrize("kwargs, fragment", [
    (dict(address="not-an-ip"), "Invalid IP address"),
    (dict(address=None), "Invalid IP address"),
    (dict(address="192.168.2.50", prefix=0), "Prefix length"),
    (dict(address="192.168.2.50", prefix=33), "Prefix length"),
    (dict(address="127.0.0.1"), "usable host address"),
    (dict(address="224.0.0.5"), "usable host address"),
    (dict(address="169.254.9.9"), "direct-cable"),
    (dict(address="192.168.2.0"), "network or broadcast"),
    (dict(address="192.168.2.255"), "network or broadcast"),
    (dict(address="192.168.2.50", gateway="192.168.3.1"), "same subnet"),
    (dict(address="192.168.2.50", gateway="192.168.2.50"), "own address"),
    (dict(address="192.168.2.50", gateway="nope"), "Invalid gateway"),
    (dict(address="192.168.2.50", dns=["8.8.8"]), "Invalid DNS"),
    (dict(address="192.168.2.50", dns=["1.1.1.1", "8.8.8.8", "9.9.9.9", "8.8.4.4"]), "At most 3"),
])
def test_parse_static_config_rejects(kwargs, fragment):
    args = {"prefix": 24, **kwargs}
    with pytest.raises(ValueError, match=fragment):
        netconfig.parse_static_config(**args)


def test_subnet_change_warning():
    live = [{"type": "ethernet", "addresses": ["192.168.2.50/24", RESCUE]}]
    same = {"address": "192.168.2.60", "prefix": 24}
    moved = {"address": "10.0.0.5", "prefix": 24}
    assert netconfig.subnet_change_warning(same, "ethernet", live) == ""
    assert "192.168.2.0/24" in netconfig.subnet_change_warning(moved, "ethernet", live)
    # only the rescue address is live: nothing to warn about
    only_rescue = [{"type": "ethernet", "addresses": [RESCUE]}]
    assert netconfig.subnet_change_warning(moved, "ethernet", only_rescue) == ""


# ---- Wi-Fi ----------------------------------------------------------------
def test_scan_dedupes_and_flags(net):
    networks, error = netconfig.scan_networks()
    assert error is None
    by_ssid = {n["ssid"]: n for n in networks}
    assert list(by_ssid) == ["LabNet", "eduroam", "Guest: Lobby"]   # strongest first, hidden dropped
    assert by_ssid["LabNet"]["signal"] == 82                        # strongest AP of the two
    assert by_ssid["eduroam"]["enterprise"] and not by_ssid["eduroam"]["open"]
    assert by_ssid["Guest: Lobby"]["open"] and by_ssid["Guest: Lobby"]["security"] == "Open"
    assert not any(n["connected"] for n in networks)


def test_scan_without_adapter(net):
    net.nm.state["devices"] = [d for d in net.nm.state["devices"] if d["type"] != "wifi"]
    assert netconfig.scan_networks() == ([], "No Wi-Fi adapter found")


def test_join_psk_network(net):
    ok, msg = netconfig.connect_wifi("LabNet", "correct-horse", security="WPA2")
    assert ok and msg == "Connected to LabNet"
    wifi = iface("wifi")
    assert wifi["state"] == "connected" and wifi["ssid"] == "LabNet"
    assert wifi["addresses"] == ["192.168.1.73/24"] and wifi["gateway"] == "192.168.1.1"
    networks, _ = netconfig.scan_networks()
    assert networks[0]["ssid"] == "LabNet" and networks[0]["connected"]


def test_wrong_password_leaves_no_profile_behind(net):
    before = set(net.nm.state["connections"])
    ok, msg = netconfig.connect_wifi("LabNet", "wrong-password", security="WPA2")
    assert not ok and msg == "Incorrect password"
    assert set(net.nm.state["connections"]) == before
    assert iface("wifi")["state"] == "disconnected"


def test_password_length_is_checked_before_touching_nmcli(net):
    ok, msg = netconfig.connect_wifi("LabNet", "short", security="WPA2")
    assert not ok and "8 to 63" in msg
    assert net.nmcli_calls() == []


def test_join_enterprise_network(net):
    ok, msg = netconfig.connect_wifi("eduroam", "s3cret", username="fabio@uni.ac.uk",
                                     security="WPA2 802.1X")
    assert ok, msg
    props = net.profile(net.device("wlan0")["uuid"])
    assert props["802-1x.eap"] == "peap" and props["802-1x.phase2-auth"] == "mschapv2"
    assert props["802-1x.anonymous-identity"] == "anonymous@uni.ac.uk"
    assert props["802-1x.system-ca-certs"] == "yes"


def test_enterprise_needs_username_and_valid_methods(net):
    assert "username" in netconfig.connect_wifi("eduroam", "s3cret", security="WPA2 802.1X")[1]
    assert "EAP method" in netconfig.connect_wifi("eduroam", "s3cret", username="u", eap_method="leap")[1]
    ok, msg = netconfig.connect_wifi("eduroam", "bad", username="fabio@uni.ac.uk",
                                     security="WPA2 802.1X")
    assert not ok and "Authentication failed" in msg


def test_join_open_network_with_colon_in_name(net):
    ok, msg = netconfig.connect_wifi("Guest: Lobby", security="")
    assert ok, msg
    assert iface("wifi")["ssid"] == "Guest: Lobby"


def test_out_of_range_network(net):
    ok, msg = netconfig.connect_wifi("Nowhere", "password123", security="WPA2")
    assert not ok and "out of range" in msg


def test_saved_profile_is_reused_by_ssid_and_old_auth_is_dropped(net):
    # a profile for the SSID already exists under another name, with a stale PSK
    assert netconfig.connect_wifi("LabNet", "correct-horse", security="WPA2")[0]
    uuid = net.device("wlan0")["uuid"]
    net.nm.state["connections"][uuid]["name"] = "preconfigured"
    # the network is reconfigured as open
    for ap in net.nm.state["air"]:
        if ap["ssid"] == "LabNet":
            ap["security"] = ""
    ok, msg = netconfig.connect_wifi("LabNet", security="")
    assert ok, msg
    assert net.device("wlan0")["uuid"] == uuid                     # same profile, not a duplicate
    assert not any(k.startswith("wifi-sec.") for k in net.profile(uuid))
    wifi_profiles = [c for c in net.nm.state["connections"].values() if c["type"] == "802-11-wireless"]
    assert len(wifi_profiles) == 1


def test_wpa3_only_network_uses_sae(net):
    net.nm.state["air"].append({"ssid": "Modern", "signal": 70, "security": "WPA3", "psk": "pw"})
    ok, msg = netconfig.connect_wifi("Modern", "pw", security="WPA3")
    assert ok, msg
    assert net.profile(net.device("wlan0")["uuid"])["wifi-sec.key-mgmt"] == "sae"
    assert not netconfig._is_sae_only("WPA2 WPA3")                 # transition mode stays PSK
