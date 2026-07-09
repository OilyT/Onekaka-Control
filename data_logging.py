import csv
import os

CSV_FILE = "station_log.csv"
CSV_FIELDS = ["timestamp", "name", "address", "value", "min", "max"]
REGISTERS_FILE = "station_registers.csv"
REGISTER_FIELDS = ["name", "address", "type", "min", "max"]


def init_csv(csv_file: str = CSV_FILE):
    """Create CSV with header row if it does not already exist."""
    if not os.path.exists(csv_file):
        with open(csv_file, "w", newline="") as f:
            csv.writer(f).writerow(CSV_FIELDS)


def append_csv(rows: list[dict], csv_file: str = CSV_FILE):
    if not rows:
        return

    with open(csv_file, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writerows(rows)


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


def load_registers_from_csv(registers: dict, csv_file: str = CSV_FILE):
    """Merge register metadata found in historical logs into the current register config."""
    if not os.path.exists(csv_file):
        return

    with open(csv_file, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name or name in registers:
                continue

            try:
                address = int((row.get("address") or "").strip())
            except ValueError:
                continue

            registers[name] = {
                "address": address,
                "type": "register",
                "min": _parse_number(row.get("min")),
                "max": _parse_number(row.get("max")),
            }


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
    """Rebuild timestamp snapshots from row-based log records."""
    if not os.path.exists(csv_file):
        return []

    snapshots_by_timestamp: dict[str, dict] = {}

    with open(csv_file, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            timestamp = (row.get("timestamp") or "").strip()
            name = (row.get("name") or "").strip()
            if not timestamp or not name:
                continue

            snapshot = snapshots_by_timestamp.get(timestamp)
            if snapshot is None:
                snapshot = {"timestamp": timestamp}
                snapshots_by_timestamp[timestamp] = snapshot

            snapshot[name] = _parse_number(row.get("value"))

    snapshots = list(snapshots_by_timestamp.values())
    if max_points is not None and max_points > 0:
        snapshots = snapshots[-max_points:]
    return snapshots
