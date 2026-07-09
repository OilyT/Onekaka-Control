"""Onekaka hydro-power station monitor
Written by Oli T - 4/07/2025"""

import csv
import os
import time
from collections import deque
from datetime import datetime
from threading import Thread

import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import pymodbus.client as ModbusClient
from pymodbus import FramerType, ModbusException
from memory_addr import STATION_INFO

POLL_INTERVAL = 5        # seconds between Modbus polls
HISTORY_LENGTH = 120     # readings to keep for plot (120 × 5 s ≈ 10 min)
CSV_FILE = "station_log.csv"

# ---------------------------------------------------------------------------
# Shared state (written by polling thread, read by UI thread)
# ---------------------------------------------------------------------------
station_info_data: dict = {}
connection_status: str = "Connecting..."
history: deque = deque(maxlen=HISTORY_LENGTH)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------
def _init_csv():
    """Create CSV with header row if it does not already exist."""
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            csv.writer(f).writerow(["timestamp"] + list(STATION_INFO.keys()))


def _append_csv(row: dict):
    with open(CSV_FILE, "a", newline="") as f:
        csv.DictWriter(
            f, fieldnames=["timestamp"] + list(STATION_INFO.keys())
        ).writerow(row)


# ---------------------------------------------------------------------------
# Modbus polling thread
# ---------------------------------------------------------------------------
def modbus_station_poller(host="192.168.0.10", port=20263, framer=FramerType.SOCKET):
    global connection_status

    _init_csv()
    client = ModbusClient.ModbusTcpClient(host, port=port, framer=framer)

    if not client.connect():
        connection_status = "Failed to connect"
        return
    connection_status = "Connected"

    try:
        while True:
            snapshot = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

            for name, info in STATION_INFO.items():
                address = info["address"]
                reg_type = info["type"]
                try:
                    if reg_type == "register":
                        rr = client.read_holding_registers(address, count=1, device_id=1)
                        if rr.isError():
                            station_info_data[name] = "Modbus Error"
                            snapshot[name] = ""
                        else:
                            val = (
                                rr.registers[0] - 0x10000
                                if rr.registers[0] >= 0x8000
                                else rr.registers[0]
                            )
                            station_info_data[name] = val
                            snapshot[name] = val
                    elif reg_type == "coil":
                        rr = client.read_coils(address, count=1, device_id=1)
                        if rr.isError():
                            station_info_data[name] = "Modbus Error"
                            snapshot[name] = ""
                        else:
                            station_info_data[name] = rr.bits[0]
                            snapshot[name] = int(rr.bits[0])
                    else:
                        station_info_data[name] = "Unsupported type"
                        snapshot[name] = ""
                except ModbusException as exc:
                    station_info_data[name] = f"Exception: {exc}"
                    snapshot[name] = ""

            history.append(snapshot)
            _append_csv(snapshot)
            time.sleep(POLL_INTERVAL)
    except Exception as e:
        connection_status = f"Disconnected: {e}"
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Tkinter UI
# ---------------------------------------------------------------------------
class StationMonitor(tk.Tk):
    _BG = "#1e1e2e"
    _FG = "#cdd6f4"
    _ACCENT = "#89b4fa"
    _DIM = "#6c7086"
    _SEP = "#45475a"
    _PLOT_BG = "#181825"

    def __init__(self):
        super().__init__()
        self.title("Onekaka Station Monitor")
        self.configure(bg=self._BG)
        self.resizable(True, True)

        # ---- Left panel: live values ----------------------------------------
        left = tk.Frame(self, bg=self._BG, padx=20, pady=20)
        left.grid(row=0, column=0, sticky="ns")

        tk.Label(
            left, text="Onekaka Hydro Station",
            font=("Helvetica", 15, "bold"), bg=self._BG, fg=self._FG,
        ).grid(row=0, column=0, columnspan=2, pady=(0, 8))

        self.status_var = tk.StringVar(value="Connecting...")
        tk.Label(
            left, textvariable=self.status_var,
            font=("Helvetica", 9, "italic"), bg=self._BG, fg="#a6e3a1",
        ).grid(row=1, column=0, columnspan=2, pady=(0, 12))

        tk.Frame(left, bg=self._SEP, height=1).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(0, 10)
        )

        self.value_vars: dict[str, tk.StringVar] = {}
        for i, name in enumerate(STATION_INFO):
            tk.Label(
                left, text=name, font=("Helvetica", 11),
                bg=self._BG, fg=self._FG, anchor="w", width=22,
            ).grid(row=i + 3, column=0, sticky="w", pady=4)

            var = tk.StringVar(value="---")
            self.value_vars[name] = var
            tk.Label(
                left, textvariable=var, font=("Helvetica", 11, "bold"),
                bg=self._BG, fg=self._ACCENT, anchor="e", width=14,
            ).grid(row=i + 3, column=1, sticky="e", pady=4)

        self.updated_var = tk.StringVar(value="")
        tk.Label(
            left, textvariable=self.updated_var,
            font=("Helvetica", 8), bg=self._BG, fg=self._DIM,
        ).grid(row=len(STATION_INFO) + 3, column=0, columnspan=2, pady=(14, 2))

        tk.Label(
            left, text=f"Logging \u2192 {CSV_FILE}",
            font=("Helvetica", 8), bg=self._BG, fg=self._DIM,
        ).grid(row=len(STATION_INFO) + 4, column=0, columnspan=2)

        # ---- Right panel: plot ----------------------------------------------
        right = tk.Frame(self, bg=self._BG, padx=10, pady=20)
        right.grid(row=0, column=1, sticky="nsew")
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self._numeric_fields = [
            name for name, info in STATION_INFO.items() if info["type"] == "register"
        ]
        n = max(len(self._numeric_fields), 1)

        self._fig = Figure(figsize=(6, n * 2.8), facecolor=self._BG)
        self._axes = [self._fig.add_subplot(n, 1, i + 1) for i in range(n)]
        self._fig.subplots_adjust(hspace=0.65, left=0.13, right=0.97, top=0.95, bottom=0.07)

        self._canvas = FigureCanvasTkAgg(self._fig, master=right)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self._plot_tick = 0
        self._refresh()

    def _refresh(self):
        # Update live value labels
        self.status_var.set(connection_status)
        for name, var in self.value_vars.items():
            var.set(str(station_info_data.get(name, "---")))
        self.updated_var.set(f"Last updated: {time.strftime('%H:%M:%S')}")

        # Redraw plot in sync with the poll interval
        self._plot_tick += 1
        if self._plot_tick >= POLL_INTERVAL:
            self._plot_tick = 0
            self._update_plot()

        self.after(1000, self._refresh)

    def _update_plot(self):
        snaps = list(history)
        xs = list(range(len(snaps)))

        for ax, name in zip(self._axes, self._numeric_fields):
            ax.clear()
            ys = [
                s[name] if isinstance(s.get(name), (int, float)) else None
                for s in snaps
            ]
            vx = [x for x, y in zip(xs, ys) if y is not None]
            vy = [y for y in ys if y is not None]

            if vx:
                ax.plot(vx, vy, color=self._ACCENT, linewidth=1.5)
                ax.fill_between(vx, vy, alpha=0.15, color=self._ACCENT)

            ax.set_title(name, color=self._FG, fontsize=9, pad=3, loc="left")
            ax.set_facecolor(self._PLOT_BG)
            ax.tick_params(colors=self._DIM, labelsize=7)
            for spine in ax.spines.values():
                spine.set_color(self._SEP)

            if len(snaps) >= 2:
                t0 = snaps[0]["timestamp"].split(" ")[1]
                t1 = snaps[-1]["timestamp"].split(" ")[1]
                ax.set_xlabel(f"{t0}  \u2192  {t1}", color=self._DIM, fontsize=7)

        self._canvas.draw()


if __name__ == "__main__":
    poll_thread = Thread(target=modbus_station_poller, daemon=True)
    poll_thread.start()

    app = StationMonitor()
    app.mainloop()

