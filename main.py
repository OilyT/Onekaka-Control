from threading import Thread

from client import (
    LOG_DIR,
    POLL_INTERVAL,
    HISTORY_LENGTH,
    data_logger_worker,
    get_connection_status,
    history,
    initialize_plotted_fields,
    initialize_log_state,
    initialize_plot_buffers,
    is_plot_enabled,
    is_offline_mode,
    modbus_station_poller,
    monitored_registers,
    plot_buffer_lock,
    plot_buffers,
    plot_timestamps,
    register_lock,
    set_plot_enabled,
    set_offline_mode,
    station_info_data,
)
from data_logging import (
    REGISTERS_FILE,
    init_registers_csv,
    load_history_from_csv,
    load_station_registers,
    upsert_station_register,
)
from station_ui import StationMonitor


if __name__ == "__main__":
    print("Initializing station registers file...", flush=True)
    init_registers_csv(REGISTERS_FILE)
    print("Loading station registers...", flush=True)
    load_station_registers(monitored_registers, REGISTERS_FILE)
    print(f"Loading log history from '{LOG_DIR}'...", flush=True)
    snapshots = load_history_from_csv(LOG_DIR, max_points=HISTORY_LENGTH)
    for snapshot in snapshots:
        history.append(snapshot)

    print("Initializing plotted fields...", flush=True)
    initialize_plotted_fields(monitored_registers)
    print("Initializing log directory...", flush=True)
    initialize_log_state(monitored_registers)
    print("Initializing plot buffers...", flush=True)
    initialize_plot_buffers(snapshots, monitored_registers)

    print("Starting Modbus poller thread...", flush=True)
    poll_thread = Thread(target=modbus_station_poller, daemon=True)
    poll_thread.start()

    print("Starting data logger thread...", flush=True)
    log_thread = Thread(target=data_logger_worker, daemon=True)
    log_thread.start()

    print("Starting user interface...", flush=True)
    app = StationMonitor(
        station_info_data=station_info_data,
        monitored_registers=monitored_registers,
        register_lock=register_lock,
        history=history,
        plot_timestamps=plot_timestamps,
        plot_buffers=plot_buffers,
        plot_buffer_lock=plot_buffer_lock,
        poll_interval=POLL_INTERVAL,
        csv_file=LOG_DIR,
        get_connection_status=get_connection_status,
        is_plot_enabled=is_plot_enabled,
        set_plot_enabled=set_plot_enabled,
        set_offline_mode=set_offline_mode,
        is_offline_mode=is_offline_mode,
        persist_register=lambda name, info: upsert_station_register(
            name=name,
            address=info["address"],
            reg_type=info.get("type", "MI"),
            registers_file=REGISTERS_FILE,
        ),
    )
    app.mainloop()
