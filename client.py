"""Onekaka hydro-power station monitor
Written by Oli T - 4/07/2025"""

import time
from collections import deque
from datetime import datetime
from threading import Lock

import pymodbus.client as ModbusClient
from pymodbus import FramerType, ModbusException
from data_logging import (
    CSV_FILE,
    LOG_INTERVAL_SECONDS,
    LOG_TOTAL_SLOTS,
    TIMESTAMP_FORMAT,
    update_time_series_log,
)

POLL_INTERVAL = 5        # seconds between Modbus polls
HISTORY_LENGTH = LOG_TOTAL_SLOTS

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

    client = ModbusClient.ModbusTcpClient(host, port=port, framer=framer)

    if not client.connect():
        connection_status = "Failed to connect"
        return
    connection_status = "Connected"

    try:
        while True:
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
                        else:
                            val = (
                                rr.registers[0] - 0x10000
                                if rr.registers[0] >= 0x8000
                                else rr.registers[0]
                            )
                            station_info_data[name] = val
                    else:
                        station_info_data[name] = "Unsupported type"
                except ModbusException as exc:
                    station_info_data[name] = f"Exception: {exc}"

            time.sleep(POLL_INTERVAL)
    except Exception as e:
        connection_status = f"Disconnected: {e}"
    finally:
        client.close()

def get_connection_status():
    return connection_status


def data_logger_worker():
    """Log current in-memory values every 30 seconds, independent of poll cadence."""
    while True:
        now = datetime.now()
        slot_dt = now.replace(
            second=(now.second // LOG_INTERVAL_SECONDS) * LOG_INTERVAL_SECONDS,
            microsecond=0,
        )
        slot_ts = slot_dt.strftime(TIMESTAMP_FORMAT)

        with register_lock:
            register_copy = {name: dict(info) for name, info in monitored_registers.items()}

        current_values = {
            name: station_info_data.get(name)
            for name in register_copy
        }

        update_time_series_log(register_copy, current_values, csv_file=CSV_FILE, now=now)

        snapshot = {"timestamp": slot_ts}
        for name in register_copy:
            value = current_values.get(name)
            snapshot[name] = value if isinstance(value, (int, float)) else 0
        history.append(snapshot)

        sleep_for = LOG_INTERVAL_SECONDS - (time.time() % LOG_INTERVAL_SECONDS)
        if sleep_for <= 0:
            sleep_for = LOG_INTERVAL_SECONDS
        time.sleep(sleep_for)

