import serial
import time
from enum import Enum

# Syringe geometry. The full 60mm stroke is 12000 steps and holds SYRINGE_ML.
# This rig uses 25ml syringes (2x 25ml pumps).
SYRINGE_ML = 25.0
STROKE_STEPS = 12000


class PumpCommand(Enum):
    """Enum for syringe pump commands"""
    INJECT = 0x42  # Motor moves CW (injection)
    WITHDRAW = 0x43  # Motor moves CCW (suction/withdrawal)
    VALVE_SELECT = 0x44  # Valve selection by coded disc
    RESET_PUMP = 0x45  # Pump reset
    STOP = 0x49  # Strong stop (pump+valve)
    SET_SPEED = 0x4B  # Dynamically set speed
    RESET_VALVE = 0x4C  # Valve reset
    MOS_OPEN = 0x60  # MOS open (24V power supply open)
    MOS_CLOSE = 0x61  # MOS close (24V power supply close)
    READ_POSITION = 0x66  # Read piston position
    CLEAR_POSITION = 0x67  # Clear piston position

    # Query commands
    QUERY_ADDRESS = 0x20  # Query device address
    QUERY_RS232_BAUD = 0x21  # Query RS232 baud rate
    QUERY_RS485_BAUD = 0x22  # Query RS485 baud rate
    QUERY_CAN_BAUD = 0x23  # Query CAN baud rate
    QUERY_MAX_SPEED = 0x27  # Query maximum speed
    QUERY_RESET_SPEED = 0x2B  # Query reset speed
    QUERY_CAN_DEST_ADDR = 0x30  # Query CAN destination address
    QUERY_PUMP_STATUS = 0x4A  # Query pump status
    QUERY_PUMP_STOP_EVENT = 0x65  # Query pump stop events
    QUERY_MOTOR_DIRECTION = 0x68  # Query motor direction
    QUERY_VALVE_STATUS = 0x4D  # Query valve status
    QUERY_VALVE_CURRENT = 0x94  # Query valve working current


class Pump:
    """Class for controlling the pump"""

    def __init__(self, address=0x00):
        self.serial = None
        self.is_connected = False
        self.address = address & 0xFF  # Modbus device address (UID, set via set_address)

    def connect(self, port):
        """Connect to the pump"""
        try:
            self.serial = serial.Serial(port, 9600, timeout=1)
            self.is_connected = True
            print(f"Connected to pump on {port}")
            return True
        except serial.SerialException as e:
            print(f"Failed to connect to pump: {e}")
            self.is_connected = False
            return False

    def disconnect(self):
        """Disconnect from the pump"""
        if self.serial and self.serial.is_open:
            self.serial.close()
            self.is_connected = False

    def send_command(self, command, parameter):
        """Send a raw command byte sequence to the pump"""
        if not self.serial or not self.serial.is_open:
            print("Pump is not connected")
            return False

        try:
            if not isinstance(command, PumpCommand):
                raise TypeError(f"Command must be a PumpCommand enum, got {type(command)}")

            if not (0 <= parameter <= 0xFFFF):
                raise ValueError(f"Parameter value must be between 0 and 65535, got {parameter}")

            start_code = 0xCC
            address = self.address
            command_code = command.value
            param_low = parameter & 0xFF
            param_high = (parameter >> 8) & 0xFF
            end_code = 0xDD

            command_frame = bytes([start_code, address, command_code, param_low, param_high, end_code])
            checksum = sum(command_frame) & 0xFFFF
            checksum_low = checksum & 0xFF
            checksum_high = (checksum >> 8) & 0xFF

            command_frame += bytes([checksum_low, checksum_high])
            self.serial.write(command_frame)
            # Read response
            time.sleep(0.5)
            if self.serial.in_waiting:
                response = self.serial.read(self.serial.in_waiting)
                return response
        except Exception as e:
            print(f"Error sending command: {e}")
            return False

    def send_command_and_wait(self, command, parameter, timeout=30, poll_interval=0.5):
        """
        Sends a command and automatically polls until the operation completes or timeout occurs.

        Args:
            command (PumpCommand): Command enum to send.
            parameter (int): Command parameter.
            timeout (int): Timeout in seconds.

        Returns:
            bool: True if command completed successfully, False if an error or timeout occurred.
        """
        # Send the initial command
        response = self.send_command(command, parameter)
        if not response:
            print("No response to initial command.")
            return False

        # Polling loop to check status
        start_time = time.time()
        while time.time() - start_time < timeout:
            poll_response = self.send_command(PumpCommand.QUERY_PUMP_STATUS, 0x0000)
            if poll_response:
                status = poll_response[2]
                if status == 0x00:
                    print(f"{command.name} completed successfully.")
                    return True
                else:
                    # Task still ongoing; wait and poll again
                    print("Task ongoing...")
                    time.sleep(poll_interval)

        print(f"Timeout: {command.name} did not complete within {timeout} seconds.")
        return False

    def reset_pump(self):
        """Reset the pump and clear position"""
        success = self.send_command_and_wait(PumpCommand.RESET_PUMP, 0x0000)
        if success:
            print("Clearing position.")
            return self.send_command(PumpCommand.CLEAR_POSITION, 0x0000)
        return False

    def fully_retract_pump(self):
        """Fully retract the pump (full syringe)"""
        return self.withdraw_volume(SYRINGE_ML)

    def set_speed(self, speed):
        """Set the pump speed (1-255)"""
        if speed < 1 or speed > 255:
            print(f"Invalid speed {speed}. Must be 1-255.")
            return False
        return self.send_command(PumpCommand.SET_SPEED, speed)

    def select_valve(self, channel):
        """Select a valve channel (1-15)"""
        if channel < 1 or channel > 15:
            print(f"Invalid channel {channel}. Must be 1-15.")
            return False
        return self.send_command(PumpCommand.VALVE_SELECT, channel)

    def withdraw_volume(self, volume_ml, wait_until_done=True):
        """
        Withdraw a specific volume in ml.
        For a SYRINGE_ML syringe over the 60mm stroke (STROKE_STEPS steps):
        1ml = STROKE_STEPS / SYRINGE_ML steps.
        """
        # Ensure volume is within limits
        if volume_ml <= 0 or volume_ml > SYRINGE_ML:
            print(f"Invalid volume count {volume_ml}. Must be 0-{SYRINGE_ML}ml.")
            return False

        # Calculate steps for this volume
        steps_per_ml = STROKE_STEPS / SYRINGE_ML
        steps = int(volume_ml * steps_per_ml)

        if wait_until_done:
            return self.send_command_and_wait(PumpCommand.WITHDRAW, steps, timeout=300)
        else:
            return self.send_command(PumpCommand.WITHDRAW, steps)

    def inject_volume(self, volume_ml, wait_until_done=True):
        """
        Inject a specific volume in ml.
        For a SYRINGE_ML syringe over the 60mm stroke (STROKE_STEPS steps):
        1ml = STROKE_STEPS / SYRINGE_ML steps.
        """
        # Ensure volume is within limits
        if volume_ml <= 0 or volume_ml > SYRINGE_ML:
            print(f"Invalid volume count {volume_ml}. Must be 0-{SYRINGE_ML}ml.")
            return False

        # Calculate steps for this volume
        steps_per_ml = STROKE_STEPS / SYRINGE_ML
        steps = int(volume_ml * steps_per_ml)

        if wait_until_done:
            return self.send_command_and_wait(PumpCommand.INJECT, steps, timeout=300)
        else:
            return self.send_command(PumpCommand.INJECT, steps)

    def read_pump_position(self):
        """Read the current position of the pump in steps"""
        response = self.send_command(PumpCommand.READ_POSITION, 0x0000)

        if not response or len(response) < 8:
            print("Failed to get valid response from pump")
            return False

        # Check response format and status
        if response[2] == 0x00:  # Status OK
            # Extract position value from bytes 3 and 4
            # In the SY-03 protocol, B3 is low byte, B4 is high byte
            position = (response[4] << 8) | response[3]

            # Calculate equivalent volume for a SYRINGE_ML syringe
            volume_ml = (position / STROKE_STEPS) * SYRINGE_ML

            print(f"Pump position: {position} steps (approx. {volume_ml:.2f}ml)")
            return volume_ml
        else:
            print(f"Invalid response format: {response.hex()}")
            return False

    def query_address(self):
        """Return the pump's stored Modbus address (its UID), or None."""
        resp = self.send_command(PumpCommand.QUERY_ADDRESS, 0x0000)
        if not resp or len(resp) < 8 or resp[2] != 0x00:
            return None
        return (resp[4] << 8) | resp[3]

    def set_address(self, new_address):
        """Set the pump's Modbus address (factory command 0x00, 14-byte frame).
        Persists in the pump firmware; a power-cycle may be needed to take full
        effect. On success, updates self.address. Returns the response bytes."""
        if not self.serial or not self.serial.is_open:
            print("Pump is not connected")
            return False
        if not (0 <= new_address <= 0xFF):
            raise ValueError("address must be 0-255")
        start, end = 0xCC, 0xDD
        password = [0xFF, 0xEE, 0xBB, 0xAA]               # B3-B6 = 0xaabbeeff little-endian
        param = [new_address & 0xFF, 0x00, 0x00, 0x00]    # B7-B10 little-endian
        body = bytes([start, self.address, 0x00] + password + param + [end])
        chk = sum(body) & 0xFFFF
        frame = body + bytes([chk & 0xFF, (chk >> 8) & 0xFF])
        self.serial.reset_input_buffer()
        self.serial.write(frame)
        time.sleep(1.5)  # factory-command reply is delayed (~1-2s)
        resp = self.serial.read(self.serial.in_waiting or 8)
        if resp and len(resp) >= 3 and resp[2] == 0x00:
            self.address = new_address & 0xFF
        return resp

    def test_connection(self):
        """Test the connection to the pump"""
        print("\nTesting pump connection...")
        # Test some basic commands
        self.read_pump_position()

        print("1. Testing valve selection...")
        success = self.select_valve(1)
        if not success:
            print("Failed to select valve 1")
            return False

        time.sleep(1)

        print("2. Testing pump speed setting...")
        success = self.set_speed(255)
        if not success:
            print("Failed to set speed")
            return False

        time.sleep(1)

        print("3. Testing pump withdrawal...")
        self.withdraw_volume(20)
        self.read_pump_position()

        print("4. Testing pump reset...")
        success = self.reset_pump()
        if not success:
            print("Failed to reset pump")
            return False

        print("pump test completed successfully!")
        return True
