"""
Live pH / alarm monitor.

Reads pH values and alarm thresholds straight from the Rika RK600-07C HMI over
its web dashboard's socket.io stream (no RS-485, no Modbus -- those are dead
ends on this unit; see hmi-data-access notes).

The HMI does NOT publish a per-channel alarm boolean, so we compute the alarm
ourselves from the live pH and the min/max thresholds it does publish:
    alarm = pH < min  (LOW)  or  pH > max  (HIGH)

Variable map (discovered by watching the stream while editing the HMI):
    channel 1 pH   = var[51]
    threshold pairs (min, max) for the 8 channels = var[843/844] .. var[857/858]

Only channel 1 currently has a sensor; add channels to CHANNELS as they are
wired and their pH variable id is confirmed (it goes non-zero when connected).
"""
import re
import time
import urllib.request
import socketio

HOST = "http://192.168.2.112"

# channel -> variable ids.
# pH var ids are IRREGULAR (HMI project-design order, not a clean array) and
# must be discovered per channel: connect the sensor, snapshot, find the newly
# non-zero float in 0-14. Confirmed: ch1=51, ch2=71, ch3=157.
# Thresholds are a clean channel-ordered block (843..858 = ch1..ch8 min/max
# pairs); confirmed via ch1 and ch3 (set 4.5/10.5 -> var847/848).
CHANNELS = {
    1: {"ph": "51",  "min": "843", "max": "844"},
    2: {"ph": "71",  "min": "845", "max": "846"},
    3: {"ph": "157", "min": "847", "max": "848"},
    4: {"ph": "220", "min": "849", "max": "850"},
    5: {"ph": "903", "min": "851", "max": "852"},
    6: {"ph": "904", "min": "853", "max": "854"},
    7: {"ph": "905", "min": "855", "max": "856"},
    8: {"ph": "906", "min": "857", "max": "858"},
}

state = {}            # var id -> latest value
alarm_now = {}        # channel -> "LOW"/"HIGH"/None


def conn_id():
    html = urllib.request.urlopen(HOST + "/", timeout=8).read().decode("utf-8", "replace")
    m = re.search(r"Redirecting to (\S+)", html)
    if m:
        html = urllib.request.urlopen(HOST + "/" + m.group(1).lstrip("/"), timeout=8).read().decode("utf-8", "replace")
    mm = re.search(r"connId\s*=\s*'([^']+)'", html)
    return mm.group(1) if mm else None


def evaluate():
    for ch, v in CHANNELS.items():
        ph = state.get(v["ph"])
        lo = state.get(v["min"])
        hi = state.get(v["max"])
        if ph is None or lo is None:
            continue
        if ph < lo:
            new = "LOW"
        elif hi is not None and ph > hi:
            new = "HIGH"
        else:
            new = None
        if alarm_now.get(ch) != new:
            ts = time.strftime("%H:%M:%S")
            if new:
                print(f"  {ts}  ** CH{ch} ALARM {new}: pH {ph:.2f} (limits {lo}-{hi}) **")
            else:
                print(f"  {ts}  -- CH{ch} cleared: pH {ph:.2f} back in range ({lo}-{hi})")
            alarm_now[ch] = new


sio = socketio.Client(reconnection=True, reconnection_delay=2)


@sio.on("return var to browser")
def on_vars(*a):
    if a and isinstance(a[0], dict):
        state.update(a[0])
        evaluate()


@sio.on("connect")
def on_connect():
    cid = conn_id()
    sio.emit("conn", cid)
    sio.emit("conf.env")
    sio.emit("get all variables")
    print(f"connected to HMI ({HOST}); monitoring {len(CHANNELS)} channel(s)... Ctrl-C to stop\n")


def connect_with_retry():
    """Connect, retrying forever -- the HMI's socket.io drops occasionally."""
    while True:
        try:
            sio.connect(HOST)        # default polling->websocket (Socket.IO v2 server)
            return
        except Exception as e:
            print(f"  {time.strftime('%H:%M:%S')}  connect failed ({type(e).__name__}); retrying in 5s...")
            time.sleep(5)


def main():
    connect_with_retry()
    last_status = 0
    try:
        while True:
            time.sleep(1)
            # if the socket dropped and didn't auto-recover, reconnect
            if not sio.connected:
                print(f"  {time.strftime('%H:%M:%S')}  disconnected; reconnecting...")
                connect_with_retry()
            # heartbeat status line every 30s so you can see it's alive
            if time.time() - last_status >= 30:
                last_status = time.time()
                parts = []
                for ch, v in CHANNELS.items():
                    ph = state.get(v["ph"])
                    a = alarm_now.get(ch)
                    parts.append(f"CH{ch}={ph if ph is None else round(ph, 2)}{' ['+a+']' if a else ''}")
                print(f"  {time.strftime('%H:%M:%S')}  status: " + "  ".join(parts))
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        if sio.connected:
            sio.disconnect()


if __name__ == "__main__":
    main()
