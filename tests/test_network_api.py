"""/api/network over HTTP, against the fake nmcli."""
import pytest
from fastapi.testclient import TestClient

import netconfig
from api.app import app, client as hmi_client


@pytest.fixture
def http(net):
    # No lifespan (no `with`): the HMI client and trigger engine stay stopped.
    return TestClient(app)


def test_status_shape(http):
    body = http.get("/api/network").json()
    assert body["supported"] is True
    assert body["hostname"] == "phcontroller.local"
    assert body["rescue_address"] == netconfig.RESCUE_ADDRESS
    assert [i["type"] for i in body["interfaces"]] == ["ethernet", "wifi"]
    assert body["hmi"]["connected"] is False


def test_hmi_subnet_hint_follows_the_ethernet_address(http, monkeypatch):
    monkeypatch.setattr(hmi_client, "host", "http://192.168.2.112")
    hmi = http.get("/api/network").json()["hmi"]
    assert hmi == {"host": "192.168.2.112", "connected": False, "on_subnet": False}

    r = http.put("/api/network/ethernet", json={"mode": "static", "address": "192.168.2.50", "prefix": 24})
    assert r.status_code == 200, r.text
    assert http.get("/api/network").json()["hmi"]["on_subnet"] is True


def test_static_validation_errors_are_400_with_a_message(http):
    r = http.put("/api/network/ethernet", json={"mode": "static", "address": "169.254.1.1"})
    assert r.status_code == 400 and "direct-cable" in r.json()["detail"]
    r = http.put("/api/network/ethernet", json={"mode": "static"})
    assert r.status_code == 400 and r.json()["detail"] == "Invalid IP address"


def test_moving_subnet_returns_a_warning(http):
    http.put("/api/network/ethernet", json={"mode": "static", "address": "192.168.2.50"})
    r = http.put("/api/network/ethernet", json={"mode": "static", "address": "10.0.0.5"})
    assert r.status_code == 200
    assert "192.168.2.0/24" in r.json()["message"]


def test_unknown_interface_or_mode_is_rejected(http):
    assert http.put("/api/network/bluetooth", json={"mode": "dhcp"}).status_code == 422
    assert http.put("/api/network/ethernet", json={"mode": "bridge"}).status_code == 422


def test_apply_failure_is_reported(http, net):
    net.sudo_allowed = False
    r = http.put("/api/network/ethernet", json={"mode": "dhcp"})
    assert r.status_code == 502 and "install.sh" in r.json()["detail"]


def test_wifi_scan_and_join(http):
    networks = http.get("/api/network/wifi/networks").json()["networks"]
    assert [n["ssid"] for n in networks] == ["LabNet", "eduroam", "Guest: Lobby"]

    r = http.post("/api/network/wifi/connect", json={"ssid": "LabNet", "password": "nope-nope", "security": "WPA2"})
    assert r.status_code == 400 and r.json()["detail"] == "Incorrect password"

    r = http.post("/api/network/wifi/connect", json={"ssid": "LabNet", "password": "correct-horse", "security": "WPA2"})
    assert r.status_code == 200 and r.json() == {"message": "Connected to LabNet"}
    wifi = http.get("/api/network").json()["interfaces"][1]
    assert wifi["ssid"] == "LabNet" and wifi["addresses"] == ["192.168.1.73/24"]


def test_wifi_passwords_never_come_back(http):
    http.post("/api/network/wifi/connect", json={"ssid": "LabNet", "password": "correct-horse", "security": "WPA2"})
    assert "correct-horse" not in http.get("/api/network").text
    assert "correct-horse" not in http.get("/api/network/wifi/networks").text
