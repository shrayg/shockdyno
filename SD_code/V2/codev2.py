import sys
import threading
import time
import csv
import os
from datetime import datetime

try:
    import serial
except ImportError:
    print("Install pyserial: pip install pyserial")
    sys.exit(1)


class SerialLogger:
    """Reads lines from a serial port and appends them to a CSV file.

    Expected Arduino line format: "millis,load_cell,linear_pot[,temperature]"
    Lines are preceded by a sync byte 0xAA. Temperature is optional.
    This logger inserts three extra columns: Smoothed_Velocity, Velocity, Highpass_Velocity,
    and preserves the original temperature as the final column.
    """

    def __init__(self, ser: serial.Serial, csv_path: str) -> None:
        self.ser = ser
        self.csv_path = csv_path
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

        # state for velocity computation and smoothing
        self.prev_time = None
        self.prev_pos = None
        self.history = []  # list of (time, position)

    def start(self) -> None:
        # Open file and write header
        self._file = open(self.csv_path, 'w', newline='')
        self._writer = csv.writer(self._file)
        self._writer.writerow([
            'Millis', 'Load_Cell', 'Linear_Pot (scaled)',
            'Smoothed_Velocity', 'Velocity', 'Highpass_Velocity', 'Temperature (C)'
        ])
        self._file.flush()

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"Logging to {self.csv_path}")

    def stop(self, join_timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=join_timeout)
        try:
            self._file.close()
        except Exception:
            pass

    def log_message(self, message: str) -> None:
        with self._lock:
            self._writer.writerow(["", message, '', '', '', '', ''])
            self._file.flush()

    def _safe_float(self, s: str, fallback: float = float('nan')) -> float:
        try:
            return float(s)
        except Exception:
            return fallback

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                # Wait for sync byte 0xAA
                b = self.ser.read(1)
                if not b:
                    # timeout
                    continue
                if b != b'\xAA':
                    # skip until we find a sync
                    continue

                raw = self.ser.readline()
                if not raw:
                    continue
                line = raw.decode('utf-8', errors='ignore').strip()
                if not line or ',' not in line:
                    continue

                parts = [p.strip() for p in line.split(',')]
                if len(parts) < 3:
                    continue

                # Capture fields from incoming Arduino line
                millis_str = parts[0]
                load_cell_str = parts[1] if len(parts) > 1 else ''
                lin_pot_raw = parts[2] if len(parts) > 2 else ''
                temp_raw = parts[3] if len(parts) > 3 else ''

                # Parse time and linear potentiometer
                try:
                    current_time = float(millis_str) / 1000.0
                except Exception:
                    current_time = None

                try:
                    lin_pot_val = float(lin_pot_raw) / 1023.0 * 7.43
                    lin_pot_str = f"{lin_pot_val:.3f}"
                except Exception:
                    lin_pot_val = float('nan')
                    lin_pot_str = "NaN"

                # Update history for smoothing
                if current_time is not None:
                    self.history.append((current_time, lin_pot_val))
                    if len(self.history) > 6:
                        self.history.pop(0)

                # Compute instantaneous velocity
                if self.prev_time is not None and current_time is not None:
                    dt = current_time - self.prev_time
                    if dt > 0:
                        velocity = (lin_pot_val - (self.prev_pos if self.prev_pos is not None else lin_pot_val)) / dt
                    else:
                        velocity = 0.0
                else:
                    velocity = 0.0

                # Compute smoothed velocity (average of 5 velocities from t-5..t-1 to t)
                smoothed_velocity = ''
                if len(self.history) == 6:
                    velocities = []
                    # history indices 0..4 are t-5..t-1, index 5 is current t
                    for i in range(0, 5):
                        t0, p0 = self.history[i]
                        t1, p1 = self.history[5]
                        dt = t1 - t0
                        if dt > 0:
                            velocities.append((p1 - p0) / dt)
                    if velocities:
                        smoothed_velocity = sum(velocities) / len(velocities)

                # Highpass filter: blank out any velocity with absolute value > 25
                highpass_velocity = ''
                try:
                    if abs(velocity) <= 25:
                        highpass_velocity = f"{velocity:.3f}"
                except Exception:
                    highpass_velocity = ''

                # Prepare outgoing CSV row
                row = [millis_str, load_cell_str, lin_pot_str,
                       f"{smoothed_velocity:.3f}" if smoothed_velocity != '' else '',
                       f"{velocity:.3f}",
                       highpass_velocity]

                # Append temperature as last column (format if numeric)
                if temp_raw != '':
                    try:
                        tval = float(temp_raw)
                        # Check for DallasDevice disconnected sentinel (-127)
                        if tval <= -120:
                            row.append('')
                        else:
                            row.append(f"{tval:.2f}")
                    except Exception:
                        row.append(temp_raw)
                else:
                    row.append('')

                # Save previous
                self.prev_time = current_time
                self.prev_pos = lin_pot_val

                # Mirror to console and write
                print(row)
                with self._lock:
                    self._writer.writerow(row)
                    self._file.flush()

            except serial.SerialException as e:
                print(f"Serial error: {e}")
                break


def open_serial(port: str, baud: int) -> serial.Serial:
    try:
        ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2)
        print(f"Connected to {port} at {baud} baud.")
        return ser
    except serial.SerialException as e:
        print(f"Error opening {port}: {e}")
        sys.exit(1)


def run_interactive(ser, logger):
    prev_key = None
    try:
        while True:
            user_input = input().strip()
            if user_input.lower() in {'q', 'quit', 'exit'}:
                break
            if user_input and user_input[0].isdigit():
                key = user_input[0]
                ser.write(key.encode('ascii'))
                ser.flush()
                print(f" Sent duty '{key}'")

                if prev_key is not None and key != prev_key:
                    logger.log_message(f"Switched from {prev_key} to {key}")
                prev_key = key
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        try:
            ser.write(b'0')
            ser.flush()
        except Exception:
            pass
        logger.stop()


def main():
    port = "COM8"
    baud = 115200

    # Save CSVs in project csv folder
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    csv_dir = os.path.join(project_root, 'csv')
    os.makedirs(csv_dir, exist_ok=True)
    csv_name = os.path.join(csv_dir, f"Shock_Dyno_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    ser = open_serial(port, baud)
    logger = SerialLogger(ser, csv_name)
    logger.start()
    run_interactive(ser, logger)

    try:
        ser.close()
    except Exception:
        pass
    print(f"Data saved to {csv_name}")


if __name__ == "__main__":
    main()
import sys
import threading
import time
import csv
from datetime import datetime

try:
    import serial
except ImportError:
    print("Install pyserial: pip install pyserial")
    sys.exit(1)


class SerialLogger:
    def __init__(self, ser, csv_path):
        self.ser = ser
        self.csv_path = csv_path
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._writer = None
        self._file = None
        self.last_millis = ''  # holds the last millis value seen
        self.prev_time = None  # previous timestamp in seconds
        self.prev_pos = None   # previous position (linear pot)

        """Start the logging thread and open the CSV file."""
import sys
        self._file = open(self.csv_path, 'w', newline='')
        self._writer = csv.writer(self._file)
        # Update header to include temperature
        self._writer.writerow(['Millis', 'Load_Cell', 'Linear_Pot (scaled)', 'Smoothed_Velocity', 
                             'Velocity', 'Highpass_Velocity', 'Temperature (C)'])
        self._file.flush()

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f" Logging to {self.csv_path}")

    def stop(self):
        """Stop logging and close the CSV file."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._file:
            self._file.close()

    def log_message(self, message):
        """Logs a message aligned with the last known millis value."""
        with self._lock:
            self._writer.writerow([self.last_millis, message, '', '', ''])
            self._file.flush()

    def _run(self):
        """Thread function: continuously read from serial and log data with velocity and smoothed velocity."""
        # Store last 6 (time, lin_pot_val) for smoothing
        history = []  # list of (time, lin_pot_val)
        while not self._stop_event.is_set():
            try:
                # Wait for sync byte 0xAA
                if self.ser.read(1) != b'\xAA':
                    continue

                # Read line of CSV-style data from Arduino
                raw = self.ser.readline()
                line = raw.decode('utf-8', errors='ignore').strip()
                if not line or ',' not in line:
                    continue

                parts = [p.strip() for p in line.split(',')]
                if len(parts) < 3:
                    continue  # expects at least millis, load cell, lin pot

                # Capture raw temperature field (if Arduino sent it) before we insert new columns
                temp_raw = parts[3] if len(parts) > 3 else ''

                # Parse millis and linear potentiometer
                try:
                    current_time = float(parts[0]) / 1000  # convert ms to seconds
                    lin_pot_val = float(parts[2]) / 1023 * 7.43  # scale
                    parts[2] = f"{lin_pot_val:.3f}"
                except ValueError:
                    lin_pot_val = float('nan')
                    current_time = None
                    parts[2] = "NaN"

                # Add to history for smoothing
                if current_time is not None:
                    history.append((current_time, lin_pot_val))
                    if len(history) > 6:
                        history.pop(0)

                # Compute velocity (derivative)
                if self.prev_time is not None and current_time is not None:
                    dt = current_time - self.prev_time
                    if dt > 0:
                        velocity = (lin_pot_val - self.prev_pos) / dt
                    else:
                        velocity = 0
                else:
                    velocity = 0  # first data point

                # Compute smoothed velocity (average of 5 velocities from t-5 to t)
                smoothed_velocity = ''
                if len(history) == 6:
                    velocities = []
                    for i in range(1, 6):
                        t0, p0 = history[i-1]
                        t1, p1 = history[5]
                        dt = t1 - t0
                        if dt > 0:
                            v = (p1 - p0) / dt
                        else:
                            v = 0
                        velocities.append(v)
                    smoothed_velocity = sum(velocities) / len(velocities)
                else:
                    smoothed_velocity = ''  # Not enough data yet

                # Save current values for next iteration
                self.prev_time = current_time
                self.prev_pos = lin_pot_val


                # Insert smoothed velocity as 4th column, original velocity as 5th
                parts.insert(3, f"{smoothed_velocity:.3f}" if smoothed_velocity != '' else '')
                parts.insert(4, f"{velocity:.3f}")  # original velocity

                # Highpass filter: remove velocity values over 25
                try:
                    velocity_val = float(velocity)
                    highpass_velocity = f"{velocity_val:.3f}" if abs(velocity_val) <= 25 else ''
                except Exception:
                    highpass_velocity = ''
                parts.insert(5, highpass_velocity)

                # Append temperature (original Arduino value) as last column, formatted if numeric
                if temp_raw != '':
                    try:
                        temp_f = float(temp_raw)
                        parts.append(f"{temp_f:.2f}")
                    except Exception:
                        parts.append(temp_raw)
                else:
                    parts.append('')

                # Save millis for alignment with switch messages
                self.last_millis = parts[0]

                print(parts)  # Console mirror
                with self._lock:
                    self._writer.writerow(parts)
                    self._file.flush()

            except serial.SerialException as e:
                print(f"Serial error: {e}")
                break


def open_serial(port, baud):
    """Open the serial port safely."""
    try:
        ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2)  # give Arduino time to reset
        print(f" Connected to {port} at {baud} baud.")
        return ser
    except serial.SerialException as e:
        print(f" Error opening {port}: {e}")
        sys.exit(1)


def run_interactive(ser, logger):
    """Interactive loop for sending duty cycle commands."""
    prev_key = None
    try:
        while True:
            user_input = input().strip()
            if user_input.lower() in {'q', 'quit', 'exit'}:
                break
            if user_input and user_input[0].isdigit():
                key = user_input[0]
                ser.write(key.encode('ascii'))
                ser.flush()
                print(f"  Sent duty '{key}'")

                if prev_key is not None and key != prev_key:
                    msg = f"Switched from {prev_key} to {key}"
                    logger.log_message(msg)
                    print(f" {msg}")

                prev_key = key
    except KeyboardInterrupt:
        print("\n Exiting...")
    finally:
        ser.write(b'0')
        ser.flush()
        logger.stop()


def main():
    port = "COM8"   # update for your board
    baud = 115200
    import os
    # Ensure the csv folder exists relative to the project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    csv_dir = os.path.join(project_root, 'csv')
    os.makedirs(csv_dir, exist_ok=True)
    csv_name = os.path.join(csv_dir, f"Shock_Dyno_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    ser = open_serial(port, baud)
    logger = SerialLogger(ser, csv_name)
    logger.start()
    run_interactive(ser, logger)

    ser.close()
    print(f" Data saved to {csv_name}")


if __name__ == "__main__":
    main()
