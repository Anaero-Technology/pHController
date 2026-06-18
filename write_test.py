"""
Verify writing an HMI variable via the 'SetById' socket.io event.

Captured frame from the dashboard:
    42["SetById", 844, "11.69", "WRITE", null]
i.e.  sio.emit("SetById", (id, value_as_string, "WRITE", None))

Test: read CH1 max (var844), write a test value, read back, then restore.
"""
import re
import time
import urllib.request
import socketio

HOST = "http://192.168.2.112"
TARGET = "844"          # CH1 max
state = {}


def conn_id():
    html = urllib.request.urlopen(HOST + "/", timeout=8).read().decode("utf-8", "replace")
    m = re.search(r"Redirecting to (\S+)", html)
    if m:
        html = urllib.request.urlopen(HOST + "/" + m.group(1).lstrip("/"), timeout=8).read().decode("utf-8", "replace")
    mm = re.search(r"connId\s*=\s*'([^']+)'", html)
    return mm.group(1) if mm else None


sio = socketio.Client(reconnection=True)


@sio.on("return var to browser")
def on_vars(*a):
    if a and isinstance(a[0], dict):
        state.update(a[0])


def write_var(var_id, value):
    """value sent as a string, matching the captured frame."""
    sio.emit("SetById", (int(var_id), str(value), "WRITE", None))


def main():
    cid = conn_id()
    sio.connect(HOST, transports=["websocket"], wait_timeout=10)
    sio.emit("conn", cid); sio.emit("conf.env"); sio.emit("get all variables")
    time.sleep(3)
    original = state.get(TARGET)
    print(f"original var[{TARGET}] (CH1 max) = {original}")

    test_val = 9.5
    print(f"writing {test_val} ...")
    write_var(TARGET, test_val)
    time.sleep(1.5)
    after = state.get(TARGET)
    ok = after is not None and abs(after - test_val) < 0.05
    print(f"  read back: var[{TARGET}] = {after}   {'<<< WRITE CONFIRMED' if ok else 'no change'}")

    # restore original
    if original is not None:
        print(f"restoring to {original} ...")
        write_var(TARGET, original)
        time.sleep(1.5)
        print(f"  read back: var[{TARGET}] = {state.get(TARGET)}")
    sio.disconnect()


if __name__ == "__main__":
    main()
