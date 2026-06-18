"""
Converter loopback test. Proves the USB->serial converter + cable + driver work,
independent of the pump.

RS232 converter: jumper DB9 pin 2 (TX) to pin 3 (RX), then run this.
  - if it echoes the bytes back  -> converter is GOOD (problem is pump/power/wiring)
  - if it stays silent           -> converter/USB/driver is the problem

(RS485 cannot be looped this way; this test is for an RS232 converter.)

Usage: .venv/bin/python loopback_test.py [port]   (default /dev/cu.usbserial-1120)
"""
import sys
import serial
import time

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.usbserial-1120"
probe = bytes([0xCC, 0x00, 0x20, 0x00, 0x00, 0xDD, 0xC9, 0x01])

ser = serial.Serial(PORT, 9600, timeout=1)
ser.reset_input_buffer()
ser.write(probe)
time.sleep(0.3)
echo = ser.read(ser.in_waiting or 8)
ser.close()

print(f"sent : {probe.hex(' ')}")
print(f"recv : {echo.hex(' ') if echo else '(silence)'}")
if echo == probe:
    print("RESULT: loopback OK -> converter works. Problem is the pump (power/wiring).")
elif echo:
    print("RESULT: partial echo -> converter works but check wiring/baud.")
else:
    print("RESULT: silence -> jumper not in place, or converter/driver issue.")
