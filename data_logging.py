import csv
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta

CSV_FILE = "station_log.csv"
REGISTERS_FILE = "station_registers.csv"
REGISTER_FIELDS = ["name", "address", "type", "min", "max"]
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_INTERVAL_SECONDS = 30
LOG_DAYS = 8
SLOTS_PER_DAY = (24 * 60 * 60) // LOG_INTERVAL_SECONDS
LOG_TOTAL_SLOTS = LOG_DAYS * SLOTS_PER_DAY
LOG_METADATA_FIELDS = ["name", "address", "type", "min", "max"]


@dataclass
class TimeSeriesLogState:
    fieldnames: list[str] = field(default_factory=list)
    rows_by_name: dict[str, dict] = field(default_factory=dict)


def _format_timestamp(dt: datetime) -> str:
    return dt.strftime(TIMESTAMP_FORMAT)


def _window_start(now: datetime) -> datetime:
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today_start - timedelta(days=LOG_DAYS - 1)


def _window_columns(now: datetime) -> list[str]:
    start = _window_start(now)
    return [
        _format_timestamp(start + timedelta(seconds=LOG_INTERVAL_SECONDS * i))
        for i in range(LOG_TOTAL_SLOTS)
    ]


def _slot_timestamp(now: datetime) -> str:
    rounded = now - timedelta(
        seconds=now.second % LOG_INTERVAL_SECONDS,
        microseconds=now.microsecond,
    )
    return _format_timestamp(rounded)


def _read_log_state(csv_file: str) -> TimeSeriesLogState:
    state = TimeSeriesLogState()
    if not os.path.exists(csv_file):
        return state

    with open(csv_file, "r", newline="") as f:
        reader = csv.DictReader(f)
        state.fieldnames = list(reader.fieldnames or [])
        for row in reader:
            name = (row.get("name") or "").strip()
            if name:
                state.rows_by_name[name] = row

    return state


def build_time_series_log_state(
    registers: dict,
    csv_file: str = CSV_FILE,
    now: datetime | None = None,
) -> TimeSeriesLogState:
    """Build an in-memory view of the matrix log used for fast incremental updates."""
    init_csv(registers, csv_file=csv_file, now=now)
    return _read_log_state(csv_file)


def _copy_log_state(target: TimeSeriesLogState, source: TimeSeriesLogState):
    target.fieldnames = list(source.fieldnames)
    target.rows_by_name = dict(source.rows_by_name)


def init_csv(registers: dict, csv_file: str = CSV_FILE, now: datetime | None = None):
    """Create/update matrix log with 30 s slots for 8 full day blocks, defaulting to 0."""
    current_time = now or datetime.now()
    time_columns = _window_columns(current_time)
    headers = LOG_METADATA_FIELDS + time_columns

    existing_rows: dict[str, dict] = {}
    existing_time_columns: list[str] = []

    if os.path.exists(csv_file):
        with open(csv_file, "r", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                existing_time_columns = [
                    field for field in reader.fieldnames if field not in LOG_METADATA_FIELDS
                ]
            for row in reader:
                name = (row.get("name") or "").strip()
                if name:
                    existing_rows[name] = row

    output_rows = []
    for name, info in registers.items():
        previous = existing_rows.get(name, {})
        row = {
            "name": name,
            "address": info["address"],
            "type": info.get("type", "register"),
            "min": "" if info.get("min") is None else info.get("min"),
            "max": "" if info.get("max") is None else info.get("max"),
        }

        for ts in time_columns:
            row[ts] = previous.get(ts, "0") if ts in existing_time_columns else "0"

        output_rows.append(row)

    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(output_rows)


def update_time_series_log(
    registers: dict,
    current_values: dict,
    csv_file: str = CSV_FILE,
    now: datetime | None = None,
    state: TimeSeriesLogState | None = None,
):
    if not registers:
        return

    current_time = now or datetime.now()

    if state is None:
        init_csv(registers, csv_file=csv_file, now=current_time)
        active_state = _read_log_state(csv_file)
    else:
        active_state = state
        if not active_state.fieldnames:
            init_csv(registers, csv_file=csv_file, now=current_time)
            _copy_log_state(active_state, _read_log_state(csv_file))

    slot = _slot_timestamp(current_time)
    if slot not in active_state.fieldnames:
        init_csv(registers, csv_file=csv_file, now=current_time)
        _copy_log_state(active_state, _read_log_state(csv_file))

    fieldnames = active_state.fieldnames
    updated_rows = []
    for name, info in registers.items():
        row = dict(active_state.rows_by_name.get(name, {field: "0" for field in fieldnames}))
        row["name"] = name
        row["address"] = info["address"]
        row["type"] = info.get("type", "register")
        row["min"] = "" if info.get("min") is None else info.get("min")
        row["max"] = "" if info.get("max") is None else info.get("max")

        value = current_values.get(name)
        row[slot] = value if isinstance(value, (int, float)) else 0
        active_state.rows_by_name[name] = row
        updated_rows.append(row)

    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(updated_rows)


def init_registers_csv(registers_file: str = REGISTERS_FILE):
    """Create station-register file with header if missing."""
    if not os.path.exists(registers_file):
        with open(registers_file, "w", newline="") as f:
            csv.writer(f).writerow(REGISTER_FIELDS)


def upsert_station_register(
    name: str,
    address: int,
    reg_type: str = "register",
    min_value=None,
    max_value=None,
    registers_file: str = REGISTERS_FILE,
):
    row_data = {
        "name": name,
        "address": address,
        "type": reg_type,
        "min": "" if min_value is None else min_value,
        "max": "" if max_value is None else max_value,
    }

    init_registers_csv(registers_file)

    rows = []
    with open(registers_file, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    "name": (row.get("name") or "").strip(),
                    "address": (row.get("address") or "").strip(),
                    "type": (row.get("type") or "register").strip() or "register",
                    "min": (row.get("min") or "").strip(),
                    "max": (row.get("max") or "").strip(),
                }
            )

    updated = False
    address_text = str(address)
    for idx, row in enumerate(rows):
        same_address = row["address"] == address_text
        same_name = row["name"] == name
        if same_address or same_name:
            rows[idx] = row_data
            updated = True
            break

    if not updated:
        rows.append(row_data)

    with open(registers_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _parse_number(value: str):
    if value is None:
        return None

    text = str(value).strip()
    if text == "":
        return None

    try:
        as_float = float(text)
    except ValueError:
        return None

    if as_float.is_integer():
        return int(as_float)
    return as_float


def load_station_registers(registers: dict, registers_file: str = REGISTERS_FILE):
    """Load station register configuration from station_registers.csv.

    If a register name appears multiple times, the most recent row wins.
    """
    if not os.path.exists(registers_file):
        return

    with open(registers_file, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue

            try:
                address = int((row.get("address") or "").strip())
            except ValueError:
                continue

            reg_type = (row.get("type") or "register").strip() or "register"
            registers[name] = {
                "address": address,
                "type": reg_type,
                "min": _parse_number(row.get("min")),
                "max": _parse_number(row.get("max")),
            }


def load_history_from_csv(csv_file: str = CSV_FILE, max_points: int | None = None) -> list[dict]:
    """Rebuild timestamp snapshots from time-slot matrix log records."""
    if not os.path.exists(csv_file):
        return []

    snapshots_by_timestamp: dict[str, dict] = {}

    with open(csv_file, "r", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        time_columns = [field for field in fieldnames if field not in LOG_METADATA_FIELDS]

        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue

            for timestamp in time_columns:
                snapshot = snapshots_by_timestamp.get(timestamp)
                if snapshot is None:
                    snapshot = {"timestamp": timestamp}
                    snapshots_by_timestamp[timestamp] = snapshot

                value = _parse_number(row.get(timestamp))
                snapshot[name] = 0 if value is None else value

    timestamps_sorted = sorted(
        snapshots_by_timestamp.keys(),
        key=lambda ts: datetime.strptime(ts, TIMESTAMP_FORMAT),
    )
    snapshots = [snapshots_by_timestamp[ts] for ts in timestamps_sorted]

    if max_points is not None and max_points > 0:
        snapshots = snapshots[-max_points:]
    return snapshots
