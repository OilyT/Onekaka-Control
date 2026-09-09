from threading import Thread

from client import (
    CSV_FILE,
    POLL_INTERVAL,
    HISTORY_LENGTH,
    data_logger_worker,
    get_connection_status,
    history,
    initialize_plotted_fields,
    initialize_log_state,
    initialize_plot_buffers,
    is_plot_enabled,
    modbus_station_poller,
    monitored_registers,
    plot_buffer_lock,
    plot_buffers,
    plot_timestamps,
    register_lock,
    set_plot_enabled,
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
    init_registers_csv(REGISTERS_FILE)
    load_station_registers(monitored_registers, REGISTERS_FILE)
    snapshots = load_history_from_csv(CSV_FILE, max_points=HISTORY_LENGTH)
    for snapshot in snapshots:
        history.append(snapshot)

    initialize_plotted_fields(monitored_registers)
    initialize_log_state(monitored_registers)
    initialize_plot_buffers(snapshots, monitored_registers)

    poll_thread = Thread(target=modbus_station_poller, daemon=True)
    poll_thread.start()

    log_thread = Thread(target=data_logger_worker, daemon=True)
    log_thread.start()

    app = StationMonitor(
        station_info_data=station_info_data,
        monitored_registers=monitored_registers,
        register_lock=register_lock,
        history=history,
        plot_timestamps=plot_timestamps,
        plot_buffers=plot_buffers,
        plot_buffer_lock=plot_buffer_lock,
        poll_interval=POLL_INTERVAL,
        csv_file=CSV_FILE,
        get_connection_status=get_connection_status,
        is_plot_enabled=is_plot_enabled,
        set_plot_enabled=set_plot_enabled,
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
