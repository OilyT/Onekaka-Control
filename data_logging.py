import csv
import os
from datetime import datetime, timedelta

LOG_DIR = "logs"
LOG_FIELDS = ["timestamp", "name", "address", "type", "value"]
REGISTERS_FILE = "station_registers.csv"
REGISTER_FIELDS = ["name", "address", "type", "min", "max"]
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_INTERVAL_SECONDS = 30
LOG_DAYS = 8
SLOTS_PER_DAY = (24 * 60 * 60) // LOG_INTERVAL_SECONDS
LOG_TOTAL_SLOTS = LOG_DAYS * SLOTS_PER_DAY


def _format_timestamp(dt: datetime) -> str:
    return dt.strftime(TIMESTAMP_FORMAT)


def _log_path(log_dir: str, day: datetime) -> str:
    return os.path.join(log_dir, f"{day.strftime('%Y-%m-%d')}.csv")


def _slot_timestamp(now: datetime) -> str:
    rounded = now - timedelta(
        seconds=now.second % LOG_INTERVAL_SECONDS,
        microseconds=now.microsecond,
    )
    return _format_timestamp(rounded)


def init_log_dir(log_dir: str = LOG_DIR):
    os.makedirs(log_dir, exist_ok=True)


def update_time_series_log(
    registers: dict,
    current_values: dict,
    log_dir: str = LOG_DIR,
    now: datetime | None = None,
):
    """Append one row per register to today's log file (logs/YYYY-MM-DD.csv).

    Files are only ever opened in append mode so existing records are never overwritten.
    """
    if not registers:
        return

    current_time = now or datetime.now()
    init_log_dir(log_dir)
    path = _log_path(log_dir, current_time)
    slot = _slot_timestamp(current_time)

    write_header = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(LOG_FIELDS)
        for name, info in registers.items():
            value = current_values.get(name)
            writer.writerow(
                [
                    slot,
                    name,
                    info["address"],
                    info.get("type", "register"),
                    value if isinstance(value, (int, float)) else 0,
                ]
            )


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


def load_history_from_csv(log_dir: str = LOG_DIR, max_points: int | None = None) -> list[dict]:
    """Rebuild timestamp snapshots from the most recent daily log files."""
    if not os.path.isdir(log_dir):
        return []

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    wanted_days = {
        (today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(LOG_DAYS)
    }

    snapshots_by_timestamp: dict[str, dict] = {}
    names: list[str] = []

    for filename in sorted(os.listdir(log_dir)):
        stem, ext = os.path.splitext(filename)
        if ext != ".csv" or stem not in wanted_days:
            continue

        with open(os.path.join(log_dir, filename), "r", newline="") as f:
            for row in csv.DictReader(f):
                name = (row.get("name") or "").strip()
                timestamp = (row.get("timestamp") or "").strip()
                if not name or not timestamp:
                    continue

                if name not in names:
                    names.append(name)
                snapshot = snapshots_by_timestamp.setdefault(timestamp, {"timestamp": timestamp})
                value = _parse_number(row.get("value"))
                snapshot[name] = 0 if value is None else value

    timestamps_sorted = sorted(
        snapshots_by_timestamp.keys(),
        key=lambda ts: datetime.strptime(ts, TIMESTAMP_FORMAT),
    )
    snapshots = [snapshots_by_timestamp[ts] for ts in timestamps_sorted]
    for snapshot in snapshots:
        for name in names:
            snapshot.setdefault(name, 0)

    if max_points is not None and max_points > 0:
        snapshots = snapshots[-max_points:]
    return snapshots
