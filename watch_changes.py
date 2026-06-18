"""
Watch the HMI socket.io variable stream and print any variable that CHANGES.
Used to identify which variable IDs are pH values vs alarm flags: trigger an
alarm on the HMI while this runs and see what toggles.
"""
import re
import sys
import time
import urllib.request
import socketio

HOST = "http://192.168.2.112"
DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0

# clock / uptime / per-second counters that change every tick -- ignore as noise
NOISE = {7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 167, 108, 188, 190}


def conn_id():
    html = urllib.request.urlopen(HOST + "/", timeout=8).read().decode("utf-8", "replace")
    m = re.search(r"Redirecting to (\S+)", html)
    if m:
        html = urllib.request.urlopen(HOST + "/" + m.group(1).lstrip("/"), timeout=8).read().decode("utf-8", "replace")
    mm = re.search(r"connId\s*=\s*'([^']+)'", html)
    return mm.group(1) if mm else None


state = {}
sio = socketio.Client(reconnection=True)


@sio.on("return var to browser")
def on_vars(*a):
    if not a or not isinstance(a[0], dict):
        return
    for k, v in a[0].items():
        try:
            ki = int(k)
        except ValueError:
            continue
        if ki in NOISE:
            state[k] = v
            continue
        if k in state and state[k] != v:
            ts = time.strftime("%H:%M:%S")
            print(f"  {ts}  var[{k:>4}] : {state[k]!r}  ->  {v!r}", flush=True)
        state[k] = v


def main():
    cid = conn_id()
    print(f"watching for {DURATION:.0f}s (connId={cid}); trigger an alarm now...\n", flush=True)
    sio.connect(HOST, transports=["websocket"], wait_timeout=10)
    sio.emit("conn", cid)
    sio.emit("conf.env")
    sio.emit("get all variables")
    time.sleep(DURATION)
    sio.disconnect()
    print("\n=== watch ended ===")


if __name__ == "__main__":
    main()
