import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import netconfig  # noqa: E402
from fake_nmcli import FakeNM  # noqa: E402

# nmcli sub-commands that change state: these must go through sudo, and
# nothing else may (reads run on every status refresh and would flood the
# auth log with sudo entries).
WRITES = ("add", "modify", "up", "delete", "rescan")


class Harness:
    """netconfig wired to a FakeNM instead of real subprocesses."""

    def __init__(self):
        self.nm = FakeNM()
        self.calls = []
        self.sudo_allowed = True
        self.avahi_name = "phcontroller.local"

    def run(self, cmd, timeout):
        self.calls.append(list(cmd))
        argv = list(cmd)
        privileged = argv[:2] == ["sudo", "-n"]
        if privileged:
            if not self.sudo_allowed:
                return subprocess.CompletedProcess(cmd, 1, "", "sudo: a password is required\n")
            argv = argv[2:]
        if argv[0] == "nmcli":
            return self.nm.run(argv[1:])
        if argv[0] == "dbus-send":
            if self.avahi_name is None:
                return subprocess.CompletedProcess(cmd, 1, "", "Error org.freedesktop.DBus.Error.ServiceUnknown\n")
            return subprocess.CompletedProcess(cmd, 0, f"   {self.avahi_name}\n", "")
        raise AssertionError(f"unexpected command: {cmd}")

    # convenience accessors
    def device(self, name):
        return self.nm._dev(name)

    def profile(self, uuid):
        return self.nm.state["connections"][uuid]["props"]

    def nmcli_calls(self):
        out = []
        for c in self.calls:
            privileged = c[:2] == ["sudo", "-n"]
            argv = c[2:] if privileged else c
            if argv[0] == "nmcli":
                out.append((privileged, argv[1:]))
        return out


@pytest.fixture
def net(monkeypatch):
    h = Harness()
    monkeypatch.setattr(netconfig, "supported", lambda: True)
    monkeypatch.setattr(netconfig, "_run", h.run)
    return h
