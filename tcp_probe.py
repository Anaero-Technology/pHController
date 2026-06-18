"""
Modbus-TCP discovery probe for the RK600-07C recorder / HMI.

The HMI is reachable over Ethernet, so we talk to it as a normal TCP client
(no RS-485 master/slave contention). This scans the common Modbus tables across
a few unit IDs to find where pH values and alarm coils live.
"""
import socket
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

HOST = "192.168.2.112"
PORT = 502
SCALE = 100.0
UNIT_IDS = [1, 0, 255]      # try the controller's id, plus broadcast/gateway ids
BLOCK = 16                  # registers per read
SPAN = 64                   # scan registers 0..SPAN-1


def port_open(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError as e:
        print(f"  cannot open {host}:{port} -> {e}")
        return False


def scan_registers(client, unit, label, read_fn):
    found = False
    for base in range(0, SPAN, BLOCK):
        try:
            r = read_fn(address=base, count=BLOCK, device_id=unit)
        except ModbusException:
            continue
        if r.isError() or not getattr(r, "registers", None):
            continue
        found = True
        for i, raw in enumerate(r.registers):
            idx = base + i
            ph = raw / SCALE
            flag = "  <- plausible pH" if 0 < ph <= 14 and raw != 0 else ""
            if raw != 0:
                print(f"    {label}[{idx:3d}] = {raw:6d} (0x{raw:04x})  /100={ph:6.2f}{flag}")
    return found


def scan_bits(client, unit, label, read_fn):
    try:
        r = read_fn(address=0, count=16, device_id=unit)
    except ModbusException:
        return False
    if r.isError() or not getattr(r, "bits", None):
        return False
    bits = r.bits[:16]
    print(f"    {label}[0..15] = {[int(b) for b in bits]}")
    return True


def main():
    print(f"Probing Modbus-TCP at {HOST}:{PORT}\n")
    if not port_open(HOST, PORT):
        print("\nPort 502 is closed. On the HMI, check Application/Settings for a "
              "Modbus-TCP or 'LAN Access' toggle and enable it.")
        return

    client = ModbusTcpClient(HOST, port=PORT, timeout=3)
    if not client.connect():
        print("Connected to port but Modbus session failed.")
        return

    for unit in UNIT_IDS:
        print(f"--- unit id {unit} ---")
        any_hit = False
        any_hit |= scan_registers(client, unit, "holding", client.read_holding_registers)
        any_hit |= scan_registers(client, unit, "input  ", client.read_input_registers)
        any_hit |= scan_bits(client, unit, "coils  ", client.read_coils)
        any_hit |= scan_bits(client, unit, "discr  ", client.read_discrete_inputs)
        if not any_hit:
            print("    (no response)")
        print()

    client.close()


if __name__ == "__main__":
    main()
