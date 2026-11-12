"""
/api/network -- status and configuration of the appliance's own networking.

Thin HTTP layer over netconfig.py (which holds the strategy and the nmcli
calls). Applying a change re-activates the link, so when the browser is
connected through the interface being changed the response may never arrive;
the UI treats a dropped request as "probably applied" and tells the user where
to reconnect.
"""
import ipaddress
from typing import List, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import netconfig


class IpConfig(BaseModel):
    mode: Literal["dhcp", "static"]
    address: Optional[str] = None
    prefix: int = 24
    gateway: Optional[str] = None
    dns: List[str] = Field(default_factory=list)


class WifiJoin(BaseModel):
    ssid: str
    password: str = ""
    username: Optional[str] = None      # WPA-Enterprise (802.1X) only
    security: str = ""                  # as reported by the scan
    eap_method: Optional[str] = None    # default peap
    phase2: Optional[str] = None        # default mschapv2


def _hmi_link(hmi, interfaces):
    """Where the HMI is and whether this host can plausibly reach it.
    `on_subnet` is None when that can't be judged (hostname, no interfaces)."""
    host = urlparse(hmi.host).hostname or hmi.host
    on_subnet = None
    try:
        hmi_ip = ipaddress.IPv4Address(host)
        networks = [ipaddress.IPv4Interface(a).network
                    for i in interfaces for a in i.get("addresses", [])]
        if networks:
            on_subnet = any(hmi_ip in n for n in networks)
    except ValueError:
        pass
    return {"host": host, "connected": hmi.connected, "on_subnet": on_subnet}


def build_router(hmi) -> APIRouter:
    router = APIRouter(prefix="/api/network", tags=["network"])

    @router.get("")
    def status():
        interfaces = netconfig.interfaces()
        return {
            "supported": netconfig.supported(),
            "hostname": netconfig.mdns_hostname(),
            "rescue_address": netconfig.RESCUE_ADDRESS,
            "interfaces": interfaces,
            "hmi": _hmi_link(hmi, interfaces),
        }

    @router.get("/wifi/networks")
    def wifi_networks():
        networks, error = netconfig.scan_networks()
        return {"networks": networks, "error": error}

    @router.post("/wifi/connect")
    def wifi_connect(body: WifiJoin):
        ok, message = netconfig.connect_wifi(
            body.ssid, body.password,
            username=body.username or None,
            security=body.security,
            eap_method=body.eap_method,
            phase2=body.phase2,
        )
        if not ok:
            raise HTTPException(400, message)
        return {"message": message}

    @router.put("/{iface_type}")
    def configure(iface_type: Literal["ethernet", "wifi"], body: IpConfig):
        if body.mode == "dhcp":
            ok, message = netconfig.set_ip_config(iface_type, "dhcp")
        else:
            try:
                cfg = netconfig.parse_static_config(
                    body.address, body.prefix, body.gateway, body.dns)
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
            warning = netconfig.subnet_change_warning(cfg, iface_type)
            ok, message = netconfig.set_ip_config(iface_type, "static", **cfg)
            if ok:
                message += warning
        if not ok:
            raise HTTPException(502, message)
        return {"message": message}

    return router
