"""
Trigger engine + two-pump manager for the pH controller.

Two identical syringe pumps: one dedicated to ALKALINE, one to ACID. Standard
chemistry routing:
    pH below min (too acidic)  -> LOW  action -> ALKALINE pump (raise pH)
    pH above max (too basic)   -> HIGH action -> ACID pump   (lower pH)

Because the pumps are identical and the OS renames serial ports, each pump is
identified by its **Modbus address** (a stable UID stored in the pump, set once
via Pump.set_address). At runtime we discover which serial port currently hosts
each address. Each pump also has its own refill valve (to draw its reagent when
the syringe is depleted).

SAFETY: starts DISARMED + DRY-RUN. Doses are serialized through one worker;
a queued dose is cancelled if pH recovers before it runs.
"""
import csv
import glob
import os
import queue
import threading
import time

import serial

from Pump import Pump, PumpCommand, SYRINGE_ML

DEFAULT_REFILL_VALVE = 15
N_CHANNELS = 8
# Refill to (full - margin) so a move never targets the exact stroke ceiling --
# the firmware rejects landing on the limit (status 0x08) when the start position
# is over-estimated by counter drift / a stale read.
REFILL_MARGIN_ML = 1.0

# which pump role handles each alarm edge
ROLE_FOR_EDGE = {"low": "alkaline", "high": "acid"}
ROLES = ("acid", "alkaline")


# ---- discovery (identify pumps by Modbus address) ------------------------
def _serial_ports():
    return sorted(glob.glob("/dev/cu.usbserial-*") + glob.glob("/dev/ttyUSB*"))


def pump_address_on(port):
    """Open `port`, ask the pump for its address, return it (int) or None.
    A pump answers a broadcast query (addr 0) and reports its real address in
    the response payload."""
    try:
        ser = serial.Serial(port, 9600, timeout=0.6)
    except Exception:  # noqa: BLE001
        return None
    try:
        q = bytes([0xCC, 0x00, 0x20, 0x00, 0x00, 0xDD])
        s = sum(q) & 0xFFFF
        q += bytes([s & 0xFF, (s >> 8) & 0xFF])
        ser.reset_input_buffer()
        ser.write(q)
        time.sleep(0.35)
        r = ser.read(ser.in_waiting or 8)
        if len(r) >= 8 and r[0] == 0xCC and r[5] == 0xDD and r[2] == 0x00:
            return (r[4] << 8) | r[3]
        return None
    except Exception:  # noqa: BLE001
        return None
    finally:
        ser.close()


def discover_pumps():
    """Return {address: port} for every pump currently reachable (one per port)."""
    found = {}
    for port in _serial_ports():
        addr = pump_address_on(port)
        if addr is not None:
            found[addr] = port
    return found


# ---- two-pump manager ----------------------------------------------------
class PumpManager:
    """Resolves each role (acid/alkaline) to a live pump by its configured
    Modbus address, and performs dosing (with auto-refill)."""

    def __init__(self, get_pump_config):
        self.get_cfg = get_pump_config   # -> {"acid":{address,refill_valve}, "alkaline":{...}}
        self.pumps = {}                  # role -> record dict
        self._lock = threading.RLock()
        self._discovered = {}            # address -> port (last scan)

    def discover(self):
        with self._lock:
            for rec in self.pumps.values():
                try:
                    rec["pump"].disconnect()
                except Exception:  # noqa: BLE001
                    pass
                rec["connected"] = False
            self._discovered = discover_pumps()
            return dict(self._discovered)

    def _ensure(self, role):
        """Return a connected record for `role`, or None. Scans only FREE ports
        so resolving one role never disturbs another already-connected pump."""
        cfg = self.get_cfg().get(role, {})
        address = cfg.get("address")
        refill = int(cfg.get("refill_valve", DEFAULT_REFILL_VALVE))
        if address is None:
            return None
        with self._lock:
            rec = self.pumps.get(role)
            if rec and rec.get("connected"):
                rec["refill_valve"] = refill
                return rec
            held = {r["port"] for r in self.pumps.values()
                    if r.get("connected") and r.get("port")}
            port = None
            for p in _serial_ports():
                if p in held:
                    continue
                if pump_address_on(p) == address:
                    port = p
                    break
            if not port:
                return None
            pump = Pump(address=address)
            if not pump.connect(port):
                return None
            # Home on connect: a syringe pump reports moves as "done" but won't
            # actually execute them (and position reads are garbage) until it has
            # been reset to a known origin. Select the refill port FIRST so the
            # home's draw/expel sweep cycles reagent to/from the bottle and never
            # dispenses into the process tank (RESET preserves the valve).
            try:
                pump.select_valve(refill)
                pump.send_command_and_wait(PumpCommand.RESET_PUMP, 0x0000, timeout=30)
                pump.send_command(PumpCommand.CLEAR_POSITION, 0x0000)
            except Exception:  # noqa: BLE001
                pass
            rec = {"pump": pump, "port": port, "address": address,
                   "refill_valve": refill, "connected": True, "last_remaining": 0.0}
            self.pumps[role] = rec
            return rec

    def ensure_all(self):
        """Keep every assigned pump connected/ready (called periodically)."""
        for role in ROLES:
            if self.get_cfg().get(role, {}).get("address") is not None:
                try:
                    self._ensure(role)
                except Exception:  # noqa: BLE001
                    pass

    def assign(self, role, current_address, new_address, refill_valve=None):
        """Set the pump currently at `current_address` to `new_address` (its new
        UID) and free it for `role`. Returns {ok, port, ...}."""
        with self._lock:
            for rec in self.pumps.values():
                try:
                    rec["pump"].disconnect()
                except Exception:  # noqa: BLE001
                    pass
                rec["connected"] = False
            self.pumps.pop(role, None)
            port = discover_pumps().get(current_address)
            if not port:
                return {"ok": False, "error": f"no pump found at address {current_address}"}
            p = Pump(address=current_address)
            if not p.connect(port):
                return {"ok": False, "error": f"cannot open {port}"}
            resp = p.set_address(new_address)
            try:
                p.disconnect()
            except Exception:  # noqa: BLE001
                pass
            ok = bool(resp) and len(resp) >= 3 and resp[2] == 0x00
            return {
                "ok": ok,
                "port": port,
                "new_address": new_address,
                "resp": resp.hex(" ") if resp else None,
                "error": None if ok else "pump did not acknowledge the address change",
            }

    def _remaining_ml(self, pump):
        try:
            v = pump.read_pump_position()
        except Exception:  # noqa: BLE001
            return None
        # read_pump_position returns a float (ml) or None; guard against bool too
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return float(v)

    def _rehome(self, pump):
        """Drive to physical home and re-zero the position counter."""
        pump.send_command_and_wait(PumpCommand.RESET_PUMP, 0x0000, timeout=30)
        pump.send_command(PumpCommand.CLEAR_POSITION, 0x0000)

    def _refill(self, pump, refill_valve, remaining):
        """Fill toward (full - margin) from the reagent port. Robust against
        position drift: if the relative withdraw is rejected for over-running the
        stroke, re-home to re-zero the datum and refill from a known origin.
        Returns the new remaining (ml) or None on failure."""
        target = SYRINGE_ML - REFILL_MARGIN_ML
        if not pump.select_valve(refill_valve):
            return None
        fill = target - remaining
        if fill > 0 and not pump.withdraw_volume(fill):
            # over-ran the stroke (counter drifted from physical) -> re-zero and
            # refill from physical home. The refill valve is still selected and
            # RESET preserves it, so the home sweep expels back to the reagent
            # bottle, NOT the process tank.
            print("[refill] withdraw rejected; re-homing and retrying from origin")
            self._rehome(pump)
            if not pump.select_valve(refill_valve):
                return None
            if not pump.withdraw_volume(target):
                return None
        v = self._remaining_ml(pump)
        return v if v is not None else target

    def dose(self, role, valve, volume_ml, dry_run):
        if dry_run:
            return "simulated"
        rec = self._ensure(role)
        if not rec:
            a = self.get_cfg().get(role, {}).get("address")
            return f"error: {role} pump (addr {a}) not found"
        pump, refill_valve = rec["pump"], rec["refill_valve"]
        try:
            with self._lock:
                refilled = False
                remaining = self._remaining_ml(pump)
                if remaining is None:
                    # Don't guess -- a bad read previously made us inject from an
                    # empty syringe (firmware rejected it) and silently log "done".
                    return "error: could not read syringe position"
                rec["last_remaining"] = remaining
                if remaining < volume_ml:
                    # select_valve BLOCKS until the valve finishes rotating --
                    # otherwise the withdraw is issued mid-rotation and silently
                    # dropped. _refill self-corrects an over-run via re-home.
                    new_remaining = self._refill(pump, refill_valve, remaining)
                    if new_remaining is None:
                        return "error: refill (withdraw) rejected by pump"
                    rec["last_remaining"] = new_remaining
                    refilled = True
                if not pump.select_valve(int(valve)):
                    return "error: dose valve select failed"
                if not pump.inject_volume(float(volume_ml)):
                    return "error: dose (inject) rejected by pump"
                # Re-read the real position rather than trusting arithmetic.
                after = self._remaining_ml(pump)
                if after is not None:
                    rec["last_remaining"] = after
                elif rec["last_remaining"] is not None:
                    rec["last_remaining"] = max(0.0, rec["last_remaining"] - volume_ml)
            return "refilled, done" if refilled else "done"
        except Exception as e:  # noqa: BLE001
            rec["connected"] = False
            return f"error: {e}"

    def pump_status(self):
        cfg = self.get_cfg()
        out = {}
        for role in ROLES:
            c = cfg.get(role, {})
            rec = self.pumps.get(role)
            out[role] = {
                "address": c.get("address"),
                "refill_valve": c.get("refill_valve", DEFAULT_REFILL_VALVE),
                "connected": bool(rec and rec.get("connected")),
                "port": rec["port"] if rec else None,
                "syringe_ml": rec["last_remaining"] if rec else None,
            }
        return out


# ---- trigger engine ------------------------------------------------------
class TriggerEngine:
    def __init__(self, hmi, get_config, manager=None, poll_s=2.0, log_path=None):
        self.hmi = hmi
        self.get_config = get_config
        self.manager = manager or PumpManager(lambda: get_config().get("pumps", {}))
        self.poll_s = poll_s
        self.log_path = log_path   # CSV file appended on every dose (None = off)
        self.armed = False
        self.dry_run = True
        self._stop = False
        self._q: "queue.Queue" = queue.Queue()
        self._last_dose = {}
        self._pending = set()
        self._breached = {}
        self.events = []
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._eval_loop, daemon=True).start()
        threading.Thread(target=self._dose_worker, daemon=True).start()
        threading.Thread(target=self._resolve_loop, daemon=True).start()

    def _resolve_loop(self):
        """Keep assigned pumps connected so status is accurate and they're ready."""
        while not self._stop:
            try:
                self.manager.ensure_all()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(8)

    def stop(self):
        self._stop = True

    def set(self, armed=None, dry_run=None):
        if armed is not None:
            self.armed = bool(armed)
        if dry_run is not None:
            self.dry_run = bool(dry_run)
        return self.status()

    def status(self):
        return {
            "armed": self.armed,
            "dry_run": self.dry_run,
            "queue_depth": self._q.qsize(),
            "pumps": self.manager.pump_status(),
            "breached": [f"CH{ch}.{edge}" for (ch, edge), v in sorted(self._breached.items()) if v],
            "events": self.events[-25:],
        }

    # ---- evaluation ----
    def _is_breached(self, ch, edge):
        ph = self.hmi.ph(ch)
        lo, hi = self.hmi.thresholds(ch)
        if edge == "low":
            return ph is not None and lo is not None and ph < lo
        return ph is not None and hi is not None and ph > hi

    def _eval_loop(self):
        while not self._stop:
            try:
                self._evaluate()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(self.poll_s)

    def _evaluate(self):
        cfg = self.get_config().get("channels", {})
        now = time.time()
        for ch in range(1, N_CHANNELS + 1):
            for edge in ("low", "high"):
                key = (ch, edge)
                breached = self._is_breached(ch, edge)
                self._breached[key] = breached
                if not breached:
                    self._last_dose.pop(key, None)
                    continue
                if not self.armed or key in self._pending:
                    continue
                action = cfg.get(str(ch), {}).get(edge, {})
                if not action.get("enabled") or float(action.get("volume_ml", 0) or 0) <= 0:
                    continue
                interval = float(action.get("interval_s", 0) or 0)
                last = self._last_dose.get(key)
                if last is None or (interval > 0 and now - last >= interval):
                    self._last_dose[key] = now
                    self._pending.add(key)
                    self._q.put((ch, edge, ROLE_FOR_EDGE[edge],
                                 int(action.get("valve", 1)), float(action.get("volume_ml", 0))))

    # ---- dosing worker (serialized) ----
    def _process_one(self, ch, edge, role, valve, vol):
        if not self._is_breached(ch, edge):
            return "cancelled (recovered)"
        if not self.armed:
            return "skipped (disarmed)"
        return self.manager.dose(role, valve, vol, self.dry_run)

    def _dose_worker(self):
        while not self._stop:
            try:
                try:
                    ch, edge, role, valve, vol = self._q.get(timeout=1)
                except queue.Empty:
                    continue
                try:
                    status = self._process_one(ch, edge, role, valve, vol)
                finally:
                    self._pending.discard((ch, edge))
                self._record(ch, edge, role, vol, valve, status)
            except Exception as e:  # noqa: BLE001
                print(f"[dose worker] recovered from error: {e}")
                time.sleep(0.5)

    def _record(self, ch, edge, role, vol, valve, status):
        ev = {
            "ts": time.time(),
            "time": time.strftime("%H:%M:%S"),
            "channel": ch,
            "edge": edge,
            "role": role,
            "volume_ml": vol,
            "valve": valve,
            "status": status,
        }
        with self._lock:
            self.events.append(ev)
            self.events = self.events[-100:]
        self._append_log(ev)
        print(f"[dose] CH{ch} {edge}->{role}: {vol}ml @valve{valve} -> {status}")

    _LOG_HEADER = ["datetime", "channel", "edge", "role", "volume_ml", "valve", "status"]

    def _append_log(self, ev):
        """Append the dose event to the CSV log (persists across restarts)."""
        if not self.log_path:
            return
        try:
            new_file = not os.path.exists(self.log_path)
            with open(self.log_path, "a", newline="") as f:
                w = csv.writer(f)
                if new_file:
                    w.writerow(self._LOG_HEADER)
                w.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ev["ts"])),
                    ev["channel"], ev["edge"], ev["role"],
                    ev["volume_ml"], ev["valve"], ev["status"],
                ])
        except Exception:  # noqa: BLE001
            pass
