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
    TimeSeriesLogState,
    build_time_series_log_state,
    update_time_series_log,
)

POLL_INTERVAL = 5        # seconds between Modbus polls
RECONNECT_INTERVAL = 30  # seconds between reconnect attempts
HISTORY_LENGTH = LOG_TOTAL_SLOTS

station_info_data: dict = {}
connection_status: str = "Connecting..."
history: deque = deque(maxlen=HISTORY_LENGTH)
plot_timestamps: deque = deque(maxlen=HISTORY_LENGTH)
plot_buffers: dict[str, deque] = {}
plotted_fields: set[str] = set()
monitored_registers: dict = {}
register_lock = Lock()
plot_buffer_lock = Lock()
log_state: TimeSeriesLogState = TimeSeriesLogState()


def _ensure_plot_field(name: str):
    series = plot_buffers.get(name)
    if series is None:
        series = deque([0.0] * len(plot_timestamps), maxlen=HISTORY_LENGTH)
        plot_buffers[name] = series
    return series


def initialize_plotted_fields(registers: dict):
    with plot_buffer_lock:
        plotted_fields.clear()
        plotted_fields.update(registers.keys())


def is_plot_enabled(name: str) -> bool:
    with plot_buffer_lock:
        return name in plotted_fields


def set_plot_enabled(name: str, enabled: bool):
    with plot_buffer_lock:
        if enabled:
            plotted_fields.add(name)
            _ensure_plot_field(name)
        else:
            plotted_fields.discard(name)
            plot_buffers.pop(name, None)


def initialize_plot_buffers(snapshots: list[dict], registers: dict):
    now = datetime.now()
    with plot_buffer_lock:
        plot_timestamps.clear()
        plot_buffers.clear()

        for name in plotted_fields:
            if name in registers:
                plot_buffers[name] = deque(maxlen=HISTORY_LENGTH)

        for snapshot in snapshots:
            ts = snapshot.get("timestamp")
            if not isinstance(ts, str):
                continue

            try:
                ts_dt = datetime.strptime(ts, TIMESTAMP_FORMAT)
            except ValueError:
                continue

            if ts_dt > now:
                continue

            plot_timestamps.append(ts_dt)
            for name in list(plot_buffers.keys()):
                value = snapshot.get(name)
                plot_buffers[name].append(float(value) if isinstance(value, (int, float)) else 0.0)


def initialize_log_state(registers: dict, now: datetime | None = None):
    global log_state
    log_state = build_time_series_log_state(registers, csv_file=CSV_FILE, now=now)


def append_plot_buffers(slot_ts: str, register_names: list[str], current_values: dict):
    try:
        ts_dt = datetime.strptime(slot_ts, TIMESTAMP_FORMAT)
    except ValueError:
        return

    with plot_buffer_lock:
        active_names = [name for name in register_names if name in plotted_fields]
        for name in active_names:
            _ensure_plot_field(name)

        # Replace values when writing the same logging slot to avoid duplicate points.
        if plot_timestamps and plot_timestamps[-1] == ts_dt:
            for name in active_names:
                series = plot_buffers.get(name)
                if not series:
                    continue
                value = current_values.get(name)
                if isinstance(value, (int, float)):
                    series[-1] = float(value)
        else:
            plot_timestamps.append(ts_dt)
            for name in active_names:
                series = plot_buffers.get(name)
                if series is None:
                    continue
                value = current_values.get(name)
                if isinstance(value, (int, float)):
                    series.append(float(value))
                elif series:
                    series.append(series[-1])
                else:
                    series.append(0.0)


# ---------------------------------------------------------------------------
# Modbus polling thread
# ---------------------------------------------------------------------------
def modbus_station_poller(host="192.168.0.10", port=20263, framer=FramerType.SOCKET):
    global connection_status

    while True:
        client = ModbusClient.ModbusTcpClient(host, port=port, framer=framer)

        try:
            connection_status = "Connecting..."
            if not client.connect():
                connection_status = (
                    f"Disconnected: connect failed (retrying in {RECONNECT_INTERVAL}s)"
                )
            else:
                connection_status = "Connected"

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
            connection_status = f"Disconnected: {e} (retrying in {RECONNECT_INTERVAL}s)"
        finally:
            client.close()

        time.sleep(RECONNECT_INTERVAL)

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

        update_time_series_log(
            register_copy,
            current_values,
            csv_file=CSV_FILE,
            now=now,
            state=log_state,
        )

        snapshot = {"timestamp": slot_ts}
        for name in register_copy:
            value = current_values.get(name)
            snapshot[name] = value if isinstance(value, (int, float)) else 0
        history.append(snapshot)
        append_plot_buffers(slot_ts, list(register_copy.keys()), current_values)

        sleep_for = LOG_INTERVAL_SECONDS - (time.time() % LOG_INTERVAL_SECONDS)
        if sleep_for <= 0:
            sleep_for = LOG_INTERVAL_SECONDS
        time.sleep(sleep_for)

