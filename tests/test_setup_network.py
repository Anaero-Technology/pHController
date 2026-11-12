"""
deploy/setup_network.sh, run for real against the fake nmcli.

Everything else the script touches on a Pi (systemd, apt, /etc) is replaced by
stub commands on PATH, so this checks the part with actual logic: what happens
to the Ethernet profile, and the Comitup clean-up.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fake_nmcli import RESCUE, default_state

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "setup_network.sh"
ETH = "11111111-1111-4111-8111-111111111111"

STUBS = {
    # privileged / system commands: succeed and do nothing
    "systemctl": "exit 0",
    "hostnamectl": "exit 0",
    "apt-get": "exit 0",
    "avahi-daemon": "exit 0",
    "visudo": "exit 0",
    "rfkill": "exit 0",
    "sed": "exit 0",                      # only ever used with -i on /etc files
    "raspi-config": 'echo GB',
    "id": '[ "$1" = "-u" ] && echo 0; exit 0',
    "dpkg": 'exit "${STUB_COMITUP_INSTALLED:-1}"',
    # keep the sudoers rule where the test can read it
    "install": 'for a; do last2="$prev"; prev="$a"; done; cp "$last2" "$STUB_OUT/sudoers"',
    # pretend /etc/hosts already has a 127.0.1.1 line; otherwise the real grep
    "grep": 'for a; do last="$a"; done; [ "$last" = /etc/hosts ] && exit 0; exec /usr/bin/grep "$@"',
}


@pytest.fixture
def setup(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in STUBS.items():
        f = bindir / name
        f.write_text(f"#!/bin/sh\n{body}\n")
        f.chmod(0o755)
    nmcli = bindir / "nmcli"
    nmcli.write_text(f'#!/bin/sh\nexec {sys.executable} {ROOT / "tests" / "fake_nmcli.py"} "$@"\n')
    nmcli.chmod(0o755)
    state_file = tmp_path / "nm.json"

    def run(state=None, **env):
        state_file.write_text(json.dumps(state or default_state()))
        result = subprocess.run(
            ["bash", str(SCRIPT), "pi"], capture_output=True, text=True,
            env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
                 "FAKE_NM_STATE": str(state_file), "STUB_OUT": str(tmp_path), **env},
        )
        return result, json.loads(state_file.read_text())

    run.tmp = tmp_path
    run.again = lambda **env: run(json.loads(state_file.read_text()), **env)
    return run


def addresses(state):
    return [a.strip() for a in state["connections"][ETH]["props"]["ipv4.addresses"].split(",")]


def test_fresh_profile_gets_dhcp_plus_rescue(setup):
    state = default_state()
    state["connections"][ETH]["props"] = {"ipv4.method": "auto"}   # as shipped by the OS
    result, state = setup(state)
    assert result.returncode == 0, result.stderr
    props = state["connections"][ETH]["props"]
    assert props["ipv4.method"] == "auto"
    assert addresses(state) == [RESCUE]
    assert props["ipv4.dhcp-timeout"] == "30"
    assert props["ipv4.may-fail"] == "yes"
    assert props["ipv6.method"] == "link-local"
    assert props["connection.autoconnect"] == "yes"
    assert "http://169.254.50.1" in result.stdout


def test_rerun_is_idempotent(setup):
    setup()
    result, state = setup.again()
    assert result.returncode == 0, result.stderr
    assert addresses(state) == [RESCUE]                            # not duplicated


def test_existing_static_config_is_preserved(setup):
    """An already-deployed unit has eth0 pinned to the HMI's subnet by hand.
    Installing the update must not wipe that (it would cut off the HMI)."""
    state = default_state()
    state["connections"][ETH]["props"] = {
        "ipv4.method": "manual", "ipv4.addresses": "192.168.2.50/24", "ipv4.gateway": ""}
    result, state = setup(state)
    assert result.returncode == 0, result.stderr
    assert state["connections"][ETH]["props"]["ipv4.method"] == "manual"
    assert addresses(state) == ["192.168.2.50/24", RESCUE]
    assert "ipv4.dhcp-timeout" not in state["connections"][ETH]["props"]


def test_static_address_can_be_set_at_install_time(setup):
    result, state = setup(ETH_STATIC_ADDRESS="192.168.2.50/24")
    assert result.returncode == 0, result.stderr
    assert state["connections"][ETH]["props"]["ipv4.method"] == "manual"
    assert addresses(state) == ["192.168.2.50/24", RESCUE]


def test_bad_static_address_is_refused_before_anything_changes(setup):
    result, state = setup(ETH_STATIC_ADDRESS="192.168.2.50")
    assert result.returncode == 1
    assert "ETH_STATIC_ADDRESS" in result.stderr
    assert state["log"] == []                                      # nmcli never called


def test_profile_is_created_when_there_is_none(setup):
    state = default_state()
    state["connections"].clear()
    state["devices"][0].update(uuid=None, state="unavailable", addresses=[])   # cable unplugged
    result, state = setup(state)
    assert result.returncode == 0, result.stderr
    (profile,) = state["connections"].values()
    assert profile["name"] == "Ethernet eth0"
    assert profile["props"]["ipv4.addresses"] == RESCUE


def test_sudo_rule_is_scoped_to_nmcli(setup):
    result, _ = setup()
    assert result.returncode == 0, result.stderr
    rule = (setup.tmp / "sudoers").read_text().strip()
    assert rule == f"pi ALL=(root) NOPASSWD: {setup.tmp / 'bin' / 'nmcli'}"


def test_comitup_hotspot_is_removed_but_joined_wifi_is_kept(setup):
    state = default_state()
    state["connections"]["hotspot-uuid"] = {
        "name": "pHController-1234", "type": "802-11-wireless",
        "props": {"802-11-wireless.ssid": "pHController-1234", "802-11-wireless.mode": "ap"}}
    state["connections"]["client-uuid"] = {
        "name": "LabNet", "type": "802-11-wireless",
        "props": {"802-11-wireless.ssid": "LabNet", "802-11-wireless.mode": "infrastructure"}}
    result, state = setup(state, STUB_COMITUP_INSTALLED="0")
    assert result.returncode == 0, result.stderr
    assert "removing Comitup" in result.stdout
    assert "hotspot-uuid" not in state["connections"]
    assert "client-uuid" in state["connections"]
