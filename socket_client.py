"""
Socket.IO client for the RK600-07C HMI web dashboard.

The HMI streams its live screen variables (pH values, alarm states) over
socket.io. Handshake (from Hai.js):
    on connect -> emit "conn", connId
                  emit "conf.env"
                  emit "get all variables"
    data arrives on event "return var to browser"
    initial dump ends with "get all variables end"

This connects, asks for all variables, and logs whatever the server sends so we
can see the data structure and locate the pH / alarm tags.
"""
import re
import sys
import time
import urllib.request
import socketio

HOST = "http://192.168.2.112"
DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0


def get_conn_id():
    try:
        html = urllib.request.urlopen(HOST + "/", timeout=8).read().decode("utf-8", "replace")
        # follow the redirect chain manually if needed
        m = re.search(r"connId\s*=\s*'([^']+)'", html)
        if m:
            return m.group(1)
        # the root redirects; fetch the app page
        m2 = re.search(r"Redirecting to (\S+)", html)
        if m2:
            url = HOST + "/" + m2.group(1).lstrip("/")
            html = urllib.request.urlopen(url, timeout=8).read().decode("utf-8", "replace")
            m = re.search(r"connId\s*=\s*'([^']+)'", html)
            if m:
                return m.group(1)
    except Exception as e:
        print(f"  (could not scrape connId: {e})")
    return None


sio = socketio.Client(reconnection=False, logger=False, engineio_logger=False)
seen = 0


def show(event, data):
    global seen
    seen += 1
    s = repr(data)
    if len(s) > 800:
        s = s[:800] + f"... [+{len(s) - 800} chars]"
    print(f"\n[{event}] {s}")


@sio.on("return var to browser")
def on_vars(*args):
    show("return var to browser", args[0] if len(args) == 1 else args)


@sio.on("get all variables end")
def on_end(*args):
    print("\n[get all variables end] (initial dump complete)")


@sio.on("conf.env")
def on_env(*args):
    show("conf.env", args[0] if len(args) == 1 else args)


@sio.on("*")
def catch_all(event, *args):
    if event not in ("return var to browser", "get all variables end", "conf.env"):
        show(event, args[0] if len(args) == 1 else args)


def main():
    conn_id = get_conn_id()
    print(f"connId = {conn_id}")
    print(f"connecting to {HOST} ...")
    sio.connect(HOST, transports=["websocket", "polling"], wait_timeout=10)
    print("connected; requesting variables...")
    if conn_id:
        sio.emit("conn", conn_id)
    sio.emit("conf.env")
    sio.emit("get all variables")
    time.sleep(DURATION)
    sio.disconnect()
    print(f"\n=== done, {seen} payloads received ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        sys.exit(1)
