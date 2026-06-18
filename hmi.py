"""
Shared HMI client: one persistent socket.io connection to the Rika RK600-07C
that keeps a live mirror of all variables, and can read pH / read+write the
min/max thresholds.

Used by the FastAPI backend (and usable standalone). Requires python-socketio
4.x (the HMI is a Socket.IO v2 / EIO3 server) connected with default transports.
"""
import os
import re
import threading
import time
import urllib.request
import socketio

# Override on the Pi (which may reach the HMI on a different IP) via env var.
HOST = os.environ.get("PHTEST_HMI_HOST", "http://192.168.2.112")

# confirmed variable maps (see project memory hmi-data-access)
PH_VARS = {1: "51", 2: "71", 3: "157", 4: "220",
           5: "903", 6: "904", 7: "905", 8: "906"}
THRESH = {ch: (str(843 + (ch - 1) * 2), str(844 + (ch - 1) * 2)) for ch in range(1, 9)}


class HMIClient:
    def __init__(self, host=HOST):
        self.host = host
        self.state = {}
        self._lock = threading.Lock()
        self.sio = socketio.Client(reconnection=True, reconnection_delay=2)

        @self.sio.on("connect")
        def _on_connect():
            self._handshake()

        @self.sio.on("return var to browser")
        def _on_vars(*args):
            for x in args:
                if isinstance(x, dict):
                    with self._lock:
                        self.state.update(x)

    # ---- connection -----------------------------------------------------
    def _conn_id(self):
        try:
            html = urllib.request.urlopen(self.host + "/", timeout=8).read().decode("utf-8", "replace")
            m = re.search(r"Redirecting to (\S+)", html)
            if m:
                html = urllib.request.urlopen(self.host + "/" + m.group(1).lstrip("/"), timeout=8).read().decode("utf-8", "replace")
            mm = re.search(r"connId\s*=\s*'([^']+)'", html)
            return mm.group(1) if mm else None
        except Exception:
            return None

    def _handshake(self):
        cid = self._conn_id()
        if cid:
            self.sio.emit("conn", cid)
        self.sio.emit("conf.env")
        self.sio.emit("get all variables")

    def start(self):
        """Non-blocking: retry the initial connect in the background until it
        succeeds (the HMI may be down at boot). Once connected, python-socketio's
        own reconnection handles any later drops."""
        self._stop = False

        def _runner():
            while not self._stop:
                try:
                    self.sio.connect(self.host)
                    return  # connected; socketio takes over reconnects
                except Exception:
                    time.sleep(5)

        threading.Thread(target=_runner, daemon=True).start()

    def stop(self):
        self._stop = True
        try:
            self.sio.disconnect()
        except Exception:
            pass

    @property
    def connected(self):
        return self.sio.connected

    # ---- reads ----------------------------------------------------------
    def ph(self, ch):
        v = self.state.get(PH_VARS[ch])
        return round(v, 2) if isinstance(v, (int, float)) else None

    def thresholds(self, ch):
        lo, hi = THRESH[ch]
        return self.state.get(lo), self.state.get(hi)

    def snapshot(self):
        out = []
        for ch in range(1, 9):
            lo, hi = self.thresholds(ch)
            out.append({"channel": ch, "ph": self.ph(ch), "min": lo, "max": hi})
        return out

    # ---- writes ---------------------------------------------------------
    def set_threshold(self, ch, lo=None, hi=None):
        """Write min and/or max for a channel; returns (min, max) after write."""
        lo_var, hi_var = THRESH[ch]
        if lo is not None:
            self.sio.emit("SetById", (int(lo_var), str(lo), "WRITE", None))
        if hi is not None:
            self.sio.emit("SetById", (int(hi_var), str(hi), "WRITE", None))
        time.sleep(1.2)   # let the HMI echo the new value back
        return self.thresholds(ch)


if __name__ == "__main__":
    c = HMIClient()
    c.start()
    time.sleep(3)
    print("connected:", c.connected)
    for row in c.snapshot():
        print(row)
    c.stop()
