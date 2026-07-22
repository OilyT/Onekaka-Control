from threading import Thread

from client import (
    CSV_FILE,
    POLL_INTERVAL,
    HISTORY_LENGTH,
    data_logger_worker,
    get_connection_status,
    history,
    modbus_station_poller,
    monitored_registers,
    register_lock,
    station_info_data,
)
from data_logging import (
    REGISTERS_FILE,
    init_csv,
    init_registers_csv,
    load_history_from_csv,
    load_station_registers,
    upsert_station_register,
)
from station_ui import StationMonitor


if __name__ == "__main__":
    init_registers_csv(REGISTERS_FILE)
    load_station_registers(monitored_registers, REGISTERS_FILE)
    init_csv(monitored_registers, CSV_FILE)

    for snapshot in load_history_from_csv(CSV_FILE, max_points=HISTORY_LENGTH):
        history.append(snapshot)

    poll_thread = Thread(target=modbus_station_poller, daemon=True)
    poll_thread.start()

    log_thread = Thread(target=data_logger_worker, daemon=True)
    log_thread.start()

    app = StationMonitor(
        station_info_data=station_info_data,
        monitored_registers=monitored_registers,
        register_lock=register_lock,
        history=history,
        poll_interval=POLL_INTERVAL,
        csv_file=CSV_FILE,
        get_connection_status=get_connection_status,
        persist_register=lambda name, info: upsert_station_register(
            name=name,
            address=info["address"],
            reg_type=info.get("type", "register"),
            min_value=info.get("min"),
            max_value=info.get("max"),
            registers_file=REGISTERS_FILE,
        ),
    )
    app.mainloop()
