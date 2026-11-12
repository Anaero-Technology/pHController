"""
FastAPI backend for the pH controller appliance.

- Reads live pH + min/max thresholds from the HMI (via hmi.HMIClient).
- Writes min/max thresholds back to the HMI.
- Stores, per pH channel, a LOW-trip dose and a HIGH-trip dose. Each dose is
  "pump <volume_ml> from valve port <valve>" (the syringe pump's 15-port valve).
  These are stored in config.json; the pump trigger layer consumes them later.
- Exposes the appliance's own network settings (api/network.py): Ethernet with
  a fixed direct-cable address, optional Wi-Fi joined from the UI.
- Serves the built React UI (web/dist) as static files.

Run (dev):   .venv/bin/uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
"""
import json
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import netconfig
from api.network import build_router as build_network_router
from hmi import HMIClient
from controller import TriggerEngine, DEFAULT_REFILL_VALVE, ROLES

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
DOSE_LOG_PATH = Path(__file__).resolve().parent / "dose_log.csv"
WEB_DIST = ROOT / "web" / "dist"

N_CHANNELS = 8
N_VALVES = 15          # syringe pump valve ports (1..15)

client = HMIClient()
engine = TriggerEngine(client, lambda: config, log_path=str(DOSE_LOG_PATH))


# ---- local config: per-channel low/high dose actions ---------------------
def default_action():
    # interval_s: 0 = dose once when pH crosses the boundary;
    #            >0 = re-dose every interval_s seconds while pH stays past it.
    return {"enabled": False, "volume_ml": 0.0, "valve": 1, "interval_s": 0.0}


def default_config():
    return {
        # two pumps identified by Modbus address (UID). LOW doses use alkaline,
        # HIGH doses use acid. Address None = not yet assigned.
        "pumps": {
            "acid": {"address": None, "refill_valve": DEFAULT_REFILL_VALVE},
            "alkaline": {"address": None, "refill_valve": DEFAULT_REFILL_VALVE},
        },
        "channels": {
            str(ch): {"low": default_action(), "high": default_action()}
            for ch in range(1, N_CHANNELS + 1)
        },
    }


def load_config():
    base = default_config()
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            saved = data.get("channels", {})
            for ch in base["channels"]:
                sc = saved.get(ch, {})
                for edge in ("low", "high"):
                    if isinstance(sc.get(edge), dict):
                        base["channels"][ch][edge] = {**default_action(), **sc[edge]}
            for role in ROLES:
                if isinstance(data.get("pumps", {}).get(role), dict):
                    base["pumps"][role] = {**base["pumps"][role], **data["pumps"][role]}
        except Exception:
            pass
    return base


_save_lock = threading.Lock()


def save_config(cfg):
    # Write-then-rename: the appliance gets unplugged without warning, and a
    # half-written config.json would silently reset every pump assignment and
    # dose setting to defaults on the next boot. The lock keeps two requests
    # from interleaving in the temp file.
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with _save_lock:
        with open(tmp, "w") as f:
            f.write(json.dumps(cfg, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)


config = load_config()


def _bound_port():
    """Port uvicorn was started with (parsed from argv); default 80."""
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith("--port="):
            return a.split("=", 1)[1]
    return "80"


def _log_access_urls():
    """Print every address the UI answers on (see `journalctl -u phcontroller`).
    Addresses that appear later (Wi-Fi joined from the UI, DHCP lease) are
    listed live on the UI's Network page."""
    port = _bound_port()
    suffix = "" if port in ("80", "http") else f":{port}"
    rescue = netconfig.RESCUE_ADDRESS.split("/")[0]
    hosts = [h for h in netconfig.local_addresses() if h != rescue]
    name = netconfig.mdns_hostname()
    if name:
        hosts.insert(0, name)
    lines = [f"    http://{h}{suffix}" for h in hosts]
    lines.append(f"    http://{rescue}{suffix}   (direct Ethernet cable, always available)")
    bar = "=" * 60
    print(f"\n{bar}\n  pH Controller UI:\n" + "\n".join(lines) + f"\n{bar}\n", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        client.start()
    except Exception as e:
        print(f"[api] HMI connect failed at startup: {e} (will keep retrying)")
    engine.start()
    _log_access_urls()
    yield
    engine.stop()
    client.stop()


app = FastAPI(title="pH Controller API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- models --------------------------------------------------------------
class Action(BaseModel):
    enabled: bool = False
    volume_ml: float = Field(default=0.0, ge=0)
    valve: int = Field(default=1, ge=1, le=N_VALVES)
    interval_s: float = Field(default=0.0, ge=0)  # 0 = once on crossing; >0 = repeat every N s while breached


class ChannelUpdate(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None
    low: Optional[Action] = None
    high: Optional[Action] = None


class ControllerSettings(BaseModel):
    armed: Optional[bool] = None
    dry_run: Optional[bool] = None


class PumpUpdate(BaseModel):
    address: Optional[int] = Field(default=None, ge=0, le=255)
    refill_valve: Optional[int] = Field(default=None, ge=1, le=N_VALVES)


class PumpAssign(BaseModel):
    current_address: int = Field(ge=0, le=255)   # the pump as found now
    new_address: int = Field(ge=0, le=255)        # the UID to give it for this role
    refill_valve: Optional[int] = Field(default=None, ge=1, le=N_VALVES)


# ---- helpers -------------------------------------------------------------
def alarm_state(ph, lo, hi):
    if ph is None:
        return None
    if lo is not None and ph < lo:
        return "LOW"
    if hi is not None and ph > hi:
        return "HIGH"
    return None


def channel_row(ch: int):
    lo, hi = client.thresholds(ch)
    ph = client.ph(ch)
    cfg = config["channels"][str(ch)]
    return {
        "channel": ch,
        "ph": ph,
        "min": lo,
        "max": hi,
        "alarm": alarm_state(ph, lo, hi),
        "low": cfg["low"],
        "high": cfg["high"],
    }


# ---- API -----------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"connected": client.connected, "channels": N_CHANNELS}


@app.get("/api/meta")
def meta():
    refill_valves = sorted({p.get("refill_valve") for p in config["pumps"].values()
                            if p.get("refill_valve")})
    return {
        "connected": client.connected,
        "channels": N_CHANNELS,
        "valves": N_VALVES,
        "refill_valves": refill_valves,
        "role_for_edge": {"low": "alkaline", "high": "acid"},
    }


@app.get("/api/controller")
def get_controller():
    return engine.status()


@app.post("/api/controller")
def set_controller(body: ControllerSettings):
    return engine.set(armed=body.armed, dry_run=body.dry_run)


@app.get("/api/controller/log")
def download_dose_log():
    """Download the full dose history as a CSV file."""
    if DOSE_LOG_PATH.exists():
        return FileResponse(str(DOSE_LOG_PATH), media_type="text/csv", filename="dose_log.csv")
    header = ",".join(TriggerEngine._LOG_HEADER) + "\n"
    return Response(
        content=header,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=dose_log.csv"},
    )


# ---- pumps (two pumps, identified by Modbus address) ---------------------
@app.get("/api/pumps")
def get_pumps():
    return {"config": config["pumps"], "status": engine.manager.pump_status()}


@app.put("/api/pumps/{role}")
def update_pump(role: str, body: PumpUpdate):
    if role not in ROLES:
        raise HTTPException(404, f"role must be one of {ROLES}")
    if body.address is not None:
        config["pumps"][role]["address"] = body.address
    if body.refill_valve is not None:
        config["pumps"][role]["refill_valve"] = body.refill_valve
    save_config(config)
    return {"config": config["pumps"], "status": engine.manager.pump_status()}


@app.post("/api/pumps/discover")
def pumps_discover():
    # manager.discover() closes held ports and scans atomically under its lock
    found = engine.manager.discover()
    return {"found": {str(a): p for a, p in found.items()}}


@app.post("/api/pumps/{role}/assign")
def assign_pump(role: str, body: PumpAssign):
    """Give the pump currently at `current_address` a new UID and bind it to
    `role`. The address change is written to the pump's firmware (persistent)."""
    if role not in ROLES:
        raise HTTPException(404, f"role must be one of {ROLES}")
    result = engine.manager.assign(role, body.current_address, body.new_address)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "set address failed"))
    config["pumps"][role]["address"] = body.new_address
    if body.refill_valve is not None:
        config["pumps"][role]["refill_valve"] = body.refill_valve
    save_config(config)
    return {"config": config["pumps"], "status": engine.manager.pump_status(), "assign": result}


@app.get("/api/channels")
def get_channels():
    return [channel_row(ch) for ch in range(1, N_CHANNELS + 1)]


@app.put("/api/channels/{ch}")
def update_channel(ch: int, body: ChannelUpdate):
    if ch < 1 or ch > N_CHANNELS:
        raise HTTPException(404, "channel out of range")

    cfg = config["channels"][str(ch)]
    if body.low is not None:
        cfg["low"] = body.low.model_dump()
    if body.high is not None:
        cfg["high"] = body.high.model_dump()
    if body.low is not None or body.high is not None:
        save_config(config)

    if body.min is not None or body.max is not None:
        if not client.connected:
            raise HTTPException(503, "HMI not connected")
        client.set_threshold(ch, lo=body.min, hi=body.max)

    return channel_row(ch)


app.include_router(build_network_router(client))


# ---- static UI (built React app) -- mounted last so /api wins ------------
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="ui")
else:
    @app.get("/")
    def no_ui():
        return {"message": "UI not built yet. Run `npm run build` in web/. API is at /api/*"}
