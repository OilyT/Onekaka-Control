"""Onekaka hydro-power station monitor
Written by Oli T - 4/07/2025"""

from __future__ import annotations

import struct
import time
from collections import deque
from datetime import datetime
from threading import Event, Lock

import pymodbus.client as ModbusClient
from pymodbus import FramerType, ModbusException
from data_logging import (
    LOG_DIR,
    LOG_INTERVAL_SECONDS,
    LOG_TOTAL_SLOTS,
    REGISTER_TYPE_OFFSETS,
    COIL_TYPE,
    TIMESTAMP_FORMAT,
    init_log_dir,
    update_time_series_log,
)

POLL_INTERVAL = 10        # seconds between Modbus polls
RECONNECT_INTERVAL = 30  # seconds between reconnect attempts
MODBUS_TIMEOUT_SECONDS = 5
MODBUS_RETRIES = 2
MAX_HOLDING_REGISTERS_PER_READ = 125
MAX_COILS_PER_READ = 2000
POLL_QUALITY_WINDOW = 128
HISTORY_LENGTH = LOG_TOTAL_SLOTS
WIDE_TYPES = ("ML", "MF")  # types stored as two consecutive 16-bit registers

station_info_data: dict = {}
connection_status: str = "Connecting..."
history: deque = deque(maxlen=HISTORY_LENGTH)
plot_timestamps: deque = deque(maxlen=HISTORY_LENGTH)
plot_buffers: dict[str, deque] = {}
plotted_fields: set[str] = set()
monitored_registers: dict = {}
register_lock = Lock()
plot_buffer_lock = Lock()
poll_quality_lock = Lock()
read_state_lock = Lock()
offline_event = Event()
last_successful_values: dict[str, float | int] = {}
successful_since_last_log: set[str] = set()
poll_quality_history: deque[bool] = deque(maxlen=POLL_QUALITY_WINDOW)


def _decode_register_value(reg_type: str, registers: list[int]):
    """Decode raw 16-bit registers: MI = signed 16-bit, ML = signed 32-bit, MF = 32-bit float."""
    if reg_type in WIDE_TYPES:
        low, high = registers[0], registers[1]

        if reg_type == "MF":
            raw = struct.pack(">I", (low << 16) | high)
            return round(struct.unpack(">f", raw)[0], 4)
        
        raw = struct.pack(">I", (high << 16) | low)
        return struct.unpack(">i", raw)[0]

    value = registers[0]
    return value - 0x10000 if value >= 0x8000 else value


def _build_type_batches(register_items: list[tuple[str, dict]]) -> dict[str, dict]:
    """Build one contiguous read range per register type."""
    batches: dict[str, dict] = {}

    for name, info in register_items:
        reg_type = info.get("type")
        offset = REGISTER_TYPE_OFFSETS.get(reg_type)
        if offset is None:
            continue

        base_address = info["address"] + offset
        width = 2 if reg_type in WIDE_TYPES else 1

        batch = batches.get(reg_type)
        if batch is None:
            batches[reg_type] = {
                "start": base_address,
                "end": base_address + width - 1,
                "items": [(name, base_address, width)],
            }
            continue

        batch["start"] = min(batch["start"], base_address)
        batch["end"] = max(batch["end"], base_address + width - 1)
        batch["items"].append((name, base_address, width))

    return batches


def _record_poll_result(success: bool):
    with poll_quality_lock:
        poll_quality_history.append(bool(success))


def get_connection_quality_percent() -> float | None:
    with poll_quality_lock:
        if not poll_quality_history:
            return None
        successful = sum(1 for ok in poll_quality_history if ok)
        return (successful / len(poll_quality_history)) * 100.0


def _read_holding_register_range(client, start: int, count: int, device_id: int = 1):
    """Read a holding-register range in chunks and return a contiguous buffer."""
    values: list[int] = []
    remaining = count
    address = start

    while remaining > 0:
        chunk_size = min(remaining, MAX_HOLDING_REGISTERS_PER_READ)
        rr = client.read_holding_registers(address, count=chunk_size, device_id=device_id)
        if rr.isError() or len(rr.registers) < chunk_size:
            return None
        values.extend(rr.registers[:chunk_size])
        address += chunk_size
        remaining -= chunk_size

    return values


def _read_coils_range(client, start: int, count: int, device_id: int = 1):
    """Read a coil range in chunks and return a contiguous buffer."""
    values: list[bool] = []
    remaining = count
    address = start

    while remaining > 0:
        chunk_size = min(remaining, MAX_COILS_PER_READ)
        rr = client.read_coils(address, count=chunk_size, device_id=device_id)
        if rr.isError() or len(rr.bits) < chunk_size:
            return None
        values.extend(rr.bits[:chunk_size])
        address += chunk_size
        remaining -= chunk_size

    return values


def set_offline_mode(enabled: bool):
    if enabled:
        offline_event.set()
    else:
        offline_event.clear()


def is_offline_mode() -> bool:
    return offline_event.is_set()


def _sleep_unless_offline(seconds: float):
    """Sleep up to `seconds`, returning early if offline mode is enabled."""
    offline_event.wait(seconds)


def _ensure_plot_field(name: str):
    series = plot_buffers.get(name)
    if series is None:
        series = deque([float("nan")] * len(plot_timestamps), maxlen=HISTORY_LENGTH)
        plot_buffers[name] = series
    return series


def initialize_plotted_fields(registers: dict):
    with plot_buffer_lock:
        plotted_fields.clear()


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


def initialize_plot_buffers(snapshots: list[dict], registers: dict):
    now = datetime.now()
    with plot_buffer_lock:
        plot_timestamps.clear()
        plot_buffers.clear()

        # Keep buffers for all configured registers; plotted_fields only controls visibility.
        for name in registers.keys():
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
                plot_buffers[name].append(
                    float(value) if isinstance(value, (int, float)) else float("nan")
                )


def initialize_log_state(registers: dict, now: datetime | None = None):
    init_log_dir(LOG_DIR)


def append_plot_buffers(slot_ts: str, register_names: list[str], current_values: dict):
    try:
        ts_dt = datetime.strptime(slot_ts, TIMESTAMP_FORMAT)
    except ValueError:
        return

    with plot_buffer_lock:
        # Always keep series updated for every configured register.
        for name in register_names:
            _ensure_plot_field(name)

        # Replace values when writing the same logging slot to avoid duplicate points.
        if plot_timestamps and plot_timestamps[-1] == ts_dt:
            for name in register_names:
                series = plot_buffers.get(name)
                if not series:
                    continue
                value = current_values.get(name)
                if isinstance(value, (int, float)):
                    series[-1] = float(value)
                else:
                    series[-1] = float("nan")
        else:
            plot_timestamps.append(ts_dt)
            for name in register_names:
                series = plot_buffers.get(name)
                if series is None:
                    continue
                value = current_values.get(name)
                if isinstance(value, (int, float)):
                    series.append(float(value))
                else:
                    series.append(float("nan"))


# ---------------------------------------------------------------------------
# Modbus polling thread
# ---------------------------------------------------------------------------
def modbus_station_poller(host="192.168.0.10", port=20263, framer=FramerType.SOCKET):
    global connection_status

    while True:
        if offline_event.is_set():
            connection_status = "Offline mode"
            time.sleep(0.5)
            continue

        client = ModbusClient.ModbusTcpClient(
            host,
            port=port,
            framer=framer,
            timeout=MODBUS_TIMEOUT_SECONDS,
            retries=MODBUS_RETRIES,
        )

        try:
            connection_status = "Connecting..."
            if not client.connect():
                connection_status = (
                    f"Disconnected: connect failed (retrying in {RECONNECT_INTERVAL}s)"
                )
            else:
                connection_status = "Connected"

                while not offline_event.is_set():
                    with register_lock:
                        register_items = list(monitored_registers.items())

                    poll_success = True

                    for name, info in register_items:
                        reg_type = info.get("type")
                        if REGISTER_TYPE_OFFSETS.get(reg_type) is None:
                            station_info_data[name] = "Unsupported type"
                            poll_success = False

                    type_batches = _build_type_batches(register_items)

                    for reg_type, batch in type_batches.items():
                        if offline_event.is_set():
                            break

                        start = batch["start"]
                        count = batch["end"] - batch["start"] + 1
                        items = batch["items"]

                        try:
                            if reg_type == COIL_TYPE:
                                coil_values = _read_coils_range(client, start, count, device_id=1)
                                if coil_values is None:
                                    poll_success = False
                                    for name, _base_address, _width in items:
                                        station_info_data[name] = "Modbus Error"
                                    continue

                                for name, base_address, _width in items:
                                    idx = base_address - start
                                    value = int(bool(coil_values[idx]))
                                    station_info_data[name] = value
                                    with read_state_lock:
                                        last_successful_values[name] = value
                                        successful_since_last_log.add(name)
                            else:
                                register_values = _read_holding_register_range(
                                    client,
                                    start,
                                    count,
                                    device_id=1,
                                )
                                if register_values is None:
                                    poll_success = False
                                    for name, _base_address, _width in items:
                                        station_info_data[name] = "Modbus Error"
                                    continue

                                for name, base_address, width in items:
                                    idx = base_address - start
                                    raw_values = register_values[idx: idx + width]
                                    if len(raw_values) < width:
                                        poll_success = False
                                        station_info_data[name] = "Modbus Error"
                                        continue
                                    value = _decode_register_value(
                                        reg_type,
                                        raw_values,
                                    )
                                    station_info_data[name] = value
                                    with read_state_lock:
                                        last_successful_values[name] = value
                                        successful_since_last_log.add(name)
                        except ModbusException as exc:
                            poll_success = False
                            for name, _base_address, _width in items:
                                station_info_data[name] = f"Exception: {exc}"

                    _record_poll_result(poll_success)

                    _sleep_unless_offline(POLL_INTERVAL)
        except Exception as e:
            connection_status = f"Disconnected: {e} (retrying in {RECONNECT_INTERVAL}s)"
        finally:
            client.close()

        if offline_event.is_set():
            connection_status = "Offline mode"
        else:
            _sleep_unless_offline(RECONNECT_INTERVAL)

def get_connection_status():
    return connection_status


def data_logger_worker():
    """Log current in-memory values every 30 seconds, independent of poll cadence."""
    while True:
        if offline_event.is_set():
            time.sleep(0.5)
            continue

        now = datetime.now()
        slot_dt = now.replace(
            second=(now.second // LOG_INTERVAL_SECONDS) * LOG_INTERVAL_SECONDS,
            microsecond=0,
        )
        slot_ts = slot_dt.strftime(TIMESTAMP_FORMAT)

        with register_lock:
            register_copy = {name: dict(info) for name, info in monitored_registers.items()}

        current_values: dict[str, float | int | None] = {}
        with read_state_lock:
            for name in register_copy:
                if name in successful_since_last_log:
                    current_values[name] = last_successful_values.get(name)
                else:
                    current_values[name] = None
            successful_since_last_log.clear()

        update_time_series_log(
            register_copy,
            current_values,
            log_dir=LOG_DIR,
            now=now,
        )

        snapshot = {"timestamp": slot_ts}
        for name in register_copy:
            value = current_values.get(name)
            snapshot[name] = value if isinstance(value, (int, float)) else None
        history.append(snapshot)
        append_plot_buffers(slot_ts, list(register_copy.keys()), current_values)

        sleep_for = LOG_INTERVAL_SECONDS - (time.time() % LOG_INTERVAL_SECONDS)
        if sleep_for <= 0:
            sleep_for = LOG_INTERVAL_SECONDS
        time.sleep(sleep_for)

