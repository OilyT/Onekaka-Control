"""Onekaka hydro-power station monitor
Written by Oli T - 4/07/2025"""

import time
from collections import deque
from datetime import datetime
from threading import Lock

import pymodbus.client as ModbusClient
from pymodbus import FramerType, ModbusException
from data_logging import CSV_FILE, append_csv, init_csv

POLL_INTERVAL = 5        # seconds between Modbus polls
HISTORY_LENGTH = 120     # readings to keep for plot (120 × 5 s ≈ 10 min)

station_info_data: dict = {}
connection_status: str = "Connecting..."
history: deque = deque(maxlen=HISTORY_LENGTH)
monitored_registers: dict = {}
register_lock = Lock()


# ---------------------------------------------------------------------------
# Modbus polling thread
# ---------------------------------------------------------------------------
def modbus_station_poller(host="192.168.0.10", port=20263, framer=FramerType.SOCKET):
    global connection_status

    init_csv(CSV_FILE)
    client = ModbusClient.ModbusTcpClient(host, port=port, framer=framer)

    if not client.connect():
        connection_status = "Failed to connect"
        return
    connection_status = "Connected"

    try:
        while True:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            snapshot = {"timestamp": timestamp}
            csv_rows = []

            with register_lock:
                register_items = list(monitored_registers.items())

            for name, info in register_items:
                address = info["address"]
                reg_type = info["type"]
                try:
                    if reg_type == "register":
                        rr = client.read_holding_registers(address, count=1, device_id=1)
                        if rr.isError():
                            station_info_data[name] = "Modbus Error"
                            snapshot[name] = None
                        else:
                            val = (
                                rr.registers[0] - 0x10000
                                if rr.registers[0] >= 0x8000
                                else rr.registers[0]
                            )
                            station_info_data[name] = val
                            snapshot[name] = val
                    else:
                        station_info_data[name] = "Unsupported type"
                        snapshot[name] = None
                except ModbusException as exc:
                    station_info_data[name] = f"Exception: {exc}"
                    snapshot[name] = None

                csv_rows.append(
                    {
                        "timestamp": timestamp,
                        "name": name,
                        "address": address,
                        "value": "" if snapshot[name] is None else snapshot[name],
                        "min": info["min"],
                        "max": info["max"],
                    }
                )

            history.append(snapshot)
            append_csv(csv_rows, CSV_FILE)
            time.sleep(POLL_INTERVAL)
    except Exception as e:
        connection_status = f"Disconnected: {e}"
    finally:
        client.close()

def get_connection_status():
    return connection_status

