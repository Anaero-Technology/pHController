"""
Set pH alarm thresholds (min/max) on the HMI from the laptop, over socket.io.

Writing uses the dashboard's own mechanism, discovered by capturing a browser
frame:  emit("SetById", (var_id, "<value>", "WRITE", None))
The HMI is a Socket.IO v2 server, so this needs python-socketio 4.x (EIO3) and
a default polling->websocket connection (a websocket-only v5 client is ignored).

Channel -> (min var, max var):
    ch1 843/844  ch2 845/846  ch3 847/848  ch4 849/850
    ch5 851/852  ch6 853/854  ch7 855/856  ch8 857/858

CLI:  .venv/bin/python set_thresholds.py <channel> [min] [max]
      (omit a value or pass '-' to leave it unchanged)
  e.g .venv/bin/python set_thresholds.py 1 8 10
      .venv/bin/python set_thresholds.py 3 - 10.5
"""
import re
import sys
import time
import urllib.request
import socketio

HOST = "http://192.168.2.112"
THRESH = {ch: (843 + (ch - 1) * 2, 844 + (ch - 1) * 2) for ch in range(1, 9)}


def conn_id():
    html = urllib.request.urlopen(HOST + "/", timeout=8).read().decode("utf-8", "replace")
    m = re.search(r"Redirecting to (\S+)", html)
    if m:
        html = urllib.request.urlopen(HOST + "/" + m.group(1).lstrip("/"), timeout=8).read().decode("utf-8", "replace")
    mm = re.search(r"connId\s*=\s*'([^']+)'", html)
    return mm.group(1) if mm else None


def connect():
    state = {}
    sio = socketio.Client()

    @sio.on("return var to browser")
    def _v(*a):
        for x in a:
            if isinstance(x, dict):
                state.update(x)

    sio.connect(HOST)                      # default polling->websocket (v2 session)
    sio.emit("conn", conn_id())
    sio.emit("conf.env")
    sio.emit("get all variables")
    time.sleep(2.5)
    return sio, state


def write_var(sio, state, var_id, value):
    sio.emit("SetById", (int(var_id), str(value), "WRITE", None))
    time.sleep(1.2)
    return state.get(str(var_id))


def set_threshold(sio, state, ch, lo=None, hi=None):
    lo_var, hi_var = THRESH[ch]
    if lo is not None:
        got = write_var(sio, state, lo_var, lo)
        ok = got is not None and abs(got - float(lo)) < 0.05
        print(f"  CH{ch} min(var{lo_var}) -> {got}  {'OK' if ok else 'FAILED'}")
    if hi is not None:
        got = write_var(sio, state, hi_var, hi)
        ok = got is not None and abs(got - float(hi)) < 0.05
        print(f"  CH{ch} max(var{hi_var}) -> {got}  {'OK' if ok else 'FAILED'}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    ch = int(sys.argv[1])
    if ch not in THRESH:
        print("channel must be 1-8"); return

    def parse(i):
        if len(sys.argv) <= i or sys.argv[i] == "-":
            return None
        return float(sys.argv[i])

    lo, hi = parse(2), parse(3)
    sio, state = connect()
    lo_var, hi_var = THRESH[ch]
    print(f"CH{ch} before: min={state.get(str(lo_var))} max={state.get(str(hi_var))}")
    set_threshold(sio, state, ch, lo, hi)
    sio.disconnect()


if __name__ == "__main__":
    main()
