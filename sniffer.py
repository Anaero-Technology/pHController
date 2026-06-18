"""
Passive Modbus-RTU sniffer for the pH controller bus.

The HMI is the bus master and owns the alarm-threshold logic. This script does
NOT transmit anything -- it only listens on the same A/B pair and decodes the
HMI <-> controller traffic, so there is no second master and no contention.

It reports:
  * coil reads  (fn 01/02) -> the 8 alarm states (K1..K8 relay outputs)
  * register reads (fn 03/04) -> live pH values

Framing is done by walking the byte stream and accepting any CRC-valid frame,
which is robust against USB latency batching (no reliance on inter-frame gaps).

Run:  .venv/bin/python sniffer.py [seconds]   (default 15)
"""
import sys
import time
import serial

PORT = "/dev/cu.usbserial-1140"
BAUD = 9600
SCALE = 100.0          # pH ~= raw / 100
DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


def crc_ok(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    body, lo, hi = frame[:-2], frame[-2], frame[-1]
    c = crc16(body)
    return (c & 0xFF) == lo and (c >> 8) == hi


def length_candidates(b: bytes, i: int, n: int):
    """Plausible frame lengths starting at index i, most-specific first."""
    if i + 2 > n:
        return []
    fn = b[i + 1]
    if fn & 0x80:                       # exception response
        return [5]
    cands = []
    if fn in (1, 2, 3, 4):
        if i + 3 <= n:
            cands.append(3 + b[i + 2] + 2)   # response: addr,fn,bc,data,crc
        cands.append(8)                       # request: addr,fn,start,qty,crc
    elif fn in (5, 6):
        cands.append(8)
    elif fn in (15, 16):
        cands.append(8)                       # response
        if i + 7 <= n:
            cands.append(7 + b[i + 6] + 2)    # request
    else:
        cands.append(8)
    return [c for c in cands if c >= 4]


def extract_frames(buf: bytearray):
    """Pull all CRC-valid frames from the front of buf; return (frames, leftover)."""
    frames = []
    i, n = 0, len(buf)
    while i < n:
        matched = False
        for length in length_candidates(buf, i, n):
            if i + length <= n and crc_ok(buf[i:i + length]):
                frames.append(bytes(buf[i:i + length]))
                i += length
                matched = True
                break
        if not matched:
            i += 1                       # resync: skip a junk/partial byte
            # but if we're near the end, the tail may be a partial frame -> stop
            if n - i < 8:
                break
    return frames, buf[i:]


# ---- decoded state -------------------------------------------------------
pending = {}            # (addr, fn) -> (start, qty)  awaiting a response
seen_polls = set()      # request signatures already announced
alarms = {}             # coil index -> 0/1
regs = {}               # register index -> raw value


def handle(frame: bytes):
    addr, fn = frame[0], frame[1]

    if fn & 0x80:
        print(f"  ! exception from dev {addr}: fn 0x{fn & 0x7f:02x} code {frame[2]}")
        return

    if fn not in (1, 2, 3, 4):
        return  # not a read; ignore (writes, etc.)

    bc = frame[2]
    resp_len = 3 + bc + 2
    is_resp = len(frame) == resp_len and len(frame) != 8
    is_req = len(frame) == 8 and resp_len != 8
    if not is_resp and not is_req:                  # ambiguous 8-byte (bc==3)
        is_resp = (addr, fn) in pending
        is_req = not is_resp

    if is_req:
        start = (frame[2] << 8) | frame[3]
        qty = (frame[4] << 8) | frame[5]
        pending[(addr, fn)] = (start, qty)
        sig = (addr, fn, start, qty)
        if sig not in seen_polls:
            seen_polls.add(sig)
            kind = {1: "coils", 2: "discrete inputs",
                    3: "holding regs", 4: "input regs"}[fn]
            print(f"  -> HMI polls dev {addr}: {kind} {start}..{start + qty - 1}")
        return

    # response
    start, qty = pending.pop((addr, fn), (0, None))
    data = frame[3:3 + bc]

    if fn in (1, 2):                                # coils / alarm bits
        changed = []
        for byte_ofs, byte in enumerate(data):
            for bit in range(8):
                idx = start + byte_ofs * 8 + bit
                val = (byte >> bit) & 1
                if alarms.get(idx) != val:
                    if idx in alarms:
                        changed.append((idx, val))
                    alarms[idx] = val
        for idx, val in changed:
            state = "ALARM" if val else "clear"
            print(f"  ** channel coil[{idx}] -> {state}")
    else:                                           # registers / pH values
        for k in range(bc // 2):
            idx = start + k
            raw = (data[2 * k] << 8) | data[2 * k + 1]
            if regs.get(idx) != raw:
                regs[idx] = raw


def main():
    print(f"Listening on {PORT} @ {BAUD} for {DURATION:.0f}s (no transmit)...\n")
    ser = serial.Serial(PORT, BAUD, bytesize=8, parity="N", stopbits=1, timeout=0.1)
    buf = bytearray()
    end = time.monotonic() + DURATION
    try:
        while time.monotonic() < end:
            chunk = ser.read(512)
            if chunk:
                buf += chunk
                frames, buf = extract_frames(buf)
                for f in frames:
                    handle(f)
            if len(buf) > 1024:                     # cap runaway junk
                buf = buf[-256:]
    finally:
        ser.close()

    print("\n=== summary ===")
    if alarms:
        bits = " ".join(f"c{idx}={v}" for idx, v in sorted(alarms.items()))
        print(f"alarm coils : {bits}")
    else:
        print("alarm coils : (none seen)")
    if regs:
        print("registers seen (raw / as pH = raw/100):")
        for idx, raw in sorted(regs.items()):
            ph = raw / SCALE
            flag = "  <- plausible pH" if 0 <= ph <= 14 else ""
            print(f"  reg[{idx:2d}] = {raw:6d}  (pH {ph:6.2f}){flag}")
    else:
        print("registers   : (HMI did not poll any registers in this window)")


if __name__ == "__main__":
    main()
