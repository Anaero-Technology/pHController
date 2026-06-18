"""
Read-only test for the Runze SY-03 syringe pump.

Sends ONLY query commands (no motion) to confirm communication, decode the
device's reported state, and validate response checksums. Run this before any
movement test.

Usage: .venv/bin/python test_pump_safe.py [port]   (default /dev/cu.usbserial-1120)
"""
import sys
from Pump import Pump, PumpCommand

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-1120"

STATUS = {
    0x00: "normal", 0x01: "frame error", 0x02: "parameter error",
    0x03: "optocoupler error", 0x04: "motor busy", 0x05: "motor stalling/blocked",
    0x06: "unknown position", 0xfe: "task suspension/running", 0xff: "unknown error",
}


def check(frame):
    """Validate an 8-byte response frame's checksum (sum of B0..B5, little-endian)."""
    if not frame or len(frame) != 8:
        return False
    s = sum(frame[:6]) & 0xFFFF
    return frame[6] == (s & 0xFF) and frame[7] == (s >> 8)


def query(pump, cmd, label, decode=None):
    resp = pump.send_command(cmd, 0x0000)
    if not resp:
        print(f"  {label:24s}: NO RESPONSE")
        return None
    hexs = resp.hex(" ")
    if len(resp) != 8:
        print(f"  {label:24s}: unexpected ({hexs})")
        return resp
    ok = "ok" if check(resp) else "BAD-CRC"
    status = STATUS.get(resp[2], f"0x{resp[2]:02x}")
    val = (resp[4] << 8) | resp[3]   # B3B4 little-endian
    extra = f" -> {decode(val)}" if decode and resp[2] == 0x00 else ""
    print(f"  {label:24s}: [{hexs}] crc={ok} status={status} B3B4={val}{extra}")
    return resp


def main():
    pump = Pump()
    if not pump.connect(PORT):
        print(f"Could not open {PORT}. Try the other adapter (usbserial-1140).")
        return
    print(f"\n--- read-only queries on {PORT} ---")
    query(pump, PumpCommand.QUERY_ADDRESS, "address", lambda v: f"addr {v}")
    query(pump, PumpCommand.QUERY_RS485_BAUD, "RS485 baud",
          lambda v: ["9600", "19200", "38400", "57600", "115200"][v] if v < 5 else v)
    query(pump, PumpCommand.QUERY_MAX_SPEED, "max speed")
    query(pump, PumpCommand.QUERY_RESET_SPEED, "reset speed")
    query(pump, PumpCommand.QUERY_PUMP_STATUS, "pump status")
    query(pump, PumpCommand.QUERY_VALVE_STATUS, "valve status")
    query(pump, PumpCommand.QUERY_PUMP_STOP_EVENT, "last stop event")
    query(pump, PumpCommand.READ_POSITION, "piston position (steps)",
          lambda v: f"{v} steps ~= {v/12000*50:.2f} ml")
    pump.disconnect()
    print("\n(no motion was commanded)")


if __name__ == "__main__":
    main()
