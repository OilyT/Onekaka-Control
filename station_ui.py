import time
import tkinter as tk
from datetime import datetime, timedelta
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class StationMonitor(tk.Tk):
    _BG = "#1e1e2e"
    _FG = "#cdd6f4"
    _ACCENT = "#89b4fa"
    _DIM = "#6c7086"
    _SEP = "#45475a"
    _PLOT_BG = "#181825"
    _PLOT_HEIGHT_PER_AXIS = 30.0
    _PLOT_LOOKBACK_DAYS = 7

    def __init__(
        self,
        station_info_data,
        monitored_registers,
        register_lock,
        history,
        plot_timestamps,
        plot_buffers,
        plot_buffer_lock,
        poll_interval,
        csv_file,
        get_connection_status,
        persist_register=None,
    ):
        super().__init__()
        self._station_info_data = station_info_data
        self._monitored_registers = monitored_registers
        self._register_lock = register_lock
        self._history = history
        self._plot_timestamps = plot_timestamps
        self._plot_buffers = plot_buffers
        self._plot_buffer_lock = plot_buffer_lock
        self._poll_interval = poll_interval
        self._csv_file = csv_file
        self._get_connection_status = get_connection_status
        self._persist_register = persist_register

        self.title("Onekaka Station Monitor")
        self.configure(bg=self._BG)
        self.resizable(True, True)

        # ---- Left panel: live values ----------------------------------------
        left = tk.Frame(self, bg=self._BG, padx=20, pady=20)
        left.grid(row=0, column=0, sticky="ns")

        tk.Label(
            left,
            text="Onekaka Hydro Station",
            font=("Helvetica", 15, "bold"),
            bg=self._BG,
            fg=self._FG,
        ).grid(row=0, column=0, columnspan=2, pady=(0, 8))

        self.status_var = tk.StringVar(value="Connecting...")
        tk.Label(
            left,
            textvariable=self.status_var,
            font=("Helvetica", 9, "italic"),
            bg=self._BG,
            fg="#a6e3a1",
        ).grid(row=1, column=0, columnspan=2, pady=(0, 12))

        tk.Frame(left, bg=self._SEP, height=1).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(0, 10)
        )

        self.name_var = tk.StringVar()
        self.address_var = tk.StringVar()
        self.min_var = tk.StringVar()
        self.max_var = tk.StringVar()
        self.end_time_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.window_hours_var = tk.StringVar(value="4")
        self.use_now_var = tk.BooleanVar(value=True)
        self.form_status_var = tk.StringVar(value="")
        self.range_status_var = tk.StringVar(value="")
        self._active_use_now = True
        self._active_end_time: datetime | None = None
        self._active_window_hours = 4.0

        tk.Label(
            left,
            text="Add Register",
            font=("Helvetica", 11, "bold"),
            bg=self._BG,
            fg=self._FG,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 8))

        tk.Label(left, text="Name", bg=self._BG, fg=self._FG).grid(row=4, column=0, sticky="w")
        tk.Entry(left, textvariable=self.name_var, width=18).grid(row=4, column=1, sticky="e")

        tk.Label(left, text="Address", bg=self._BG, fg=self._FG).grid(row=5, column=0, sticky="w")
        tk.Entry(left, textvariable=self.address_var, width=18).grid(row=5, column=1, sticky="e")

        tk.Label(left, text="Min", bg=self._BG, fg=self._FG).grid(row=6, column=0, sticky="w")
        tk.Entry(left, textvariable=self.min_var, width=18).grid(row=6, column=1, sticky="e")

        tk.Label(left, text="Max", bg=self._BG, fg=self._FG).grid(row=7, column=0, sticky="w")
        tk.Entry(left, textvariable=self.max_var, width=18).grid(row=7, column=1, sticky="e")

        tk.Button(
            left,
            text="Add / Update",
            command=self._add_or_update_register,
            bg=self._ACCENT,
            fg="#11111b",
            activebackground="#74c7ec",
            relief="flat",
            padx=8,
            pady=4,
        ).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(6, 4))

        tk.Label(
            left,
            textvariable=self.form_status_var,
            font=("Helvetica", 8),
            bg=self._BG,
            fg="#f9e2af",
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(0, 8))

        tk.Frame(left, bg=self._SEP, height=1).grid(
            row=10, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )

        tk.Label(
            left,
            text="Plot Display",
            font=("Helvetica", 11, "bold"),
            bg=self._BG,
            fg=self._FG,
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=(0, 6))

        tk.Label(left, text="End Time (YYYY-MM-DD HH:MM:SS)", bg=self._BG, fg=self._FG).grid(row=12, column=0, sticky="w")
        self.end_time_entry = tk.Entry(left, textvariable=self.end_time_var, width=18)
        self.end_time_entry.grid(row=12, column=1, sticky="e")

        tk.Label(left, text="Window Hours", bg=self._BG, fg=self._FG).grid(row=13, column=0, sticky="w")
        tk.Entry(left, textvariable=self.window_hours_var, width=18).grid(row=13, column=1, sticky="e")

        tk.Checkbutton(
            left,
            text="Most Recent",
            variable=self.use_now_var,
            command=self._on_toggle_use_now,
            bg=self._BG,
            fg=self._FG,
            selectcolor=self._PLOT_BG,
            activebackground=self._BG,
            activeforeground=self._FG,
        ).grid(row=14, column=0, columnspan=2, sticky="w", pady=(4, 0))

        tk.Button(
            left,
            text="Apply Window",
            command=self._apply_window_settings,
            bg=self._ACCENT,
            fg="#11111b",
            activebackground="#74c7ec",
            relief="flat",
            padx=8,
            pady=4,
        ).grid(row=15, column=0, columnspan=2, sticky="ew", pady=(6, 4))

        tk.Label(
            left,
            textvariable=self.range_status_var,
            font=("Helvetica", 8),
            bg=self._BG,
            fg="#f9e2af",
        ).grid(row=16, column=0, columnspan=2, sticky="w", pady=(0, 8))

        tk.Frame(left, bg=self._SEP, height=1).grid(
            row=17, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )

        tk.Label(
            left,
            text="Live Values",
            font=("Helvetica", 11, "bold"),
            bg=self._BG,
            fg=self._FG,
        ).grid(row=18, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self.values_frame = tk.Frame(left, bg=self._BG)
        self.values_frame.grid(row=19, column=0, columnspan=2, sticky="ew")
        self.value_vars = {}

        self.updated_var = tk.StringVar(value="")
        tk.Label(
            left,
            textvariable=self.updated_var,
            font=("Helvetica", 8),
            bg=self._BG,
            fg=self._DIM,
        ).grid(row=20, column=0, columnspan=2, pady=(14, 2))

        tk.Label(
            left,
            text=f"Logging -> {self._csv_file}",
            font=("Helvetica", 8),
            bg=self._BG,
            fg=self._DIM,
        ).grid(row=21, column=0, columnspan=2)

        # ---- Right panel: scrollable plots ---------------------------------
        right = tk.Frame(self, bg=self._BG, padx=10, pady=20)
        right.grid(row=0, column=1, sticky="nsew")
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        plot_container = tk.Frame(right, bg=self._BG)
        plot_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._plot_scroll_canvas = tk.Canvas(
            plot_container,
            bg=self._BG,
            highlightthickness=0,
            bd=0,
        )
        self._plot_scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        plot_scrollbar = tk.Scrollbar(
            plot_container,
            orient="vertical",
            command=self._plot_scroll_canvas.yview,
        )
        plot_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._plot_scroll_canvas.configure(yscrollcommand=plot_scrollbar.set)

        self._plot_inner = tk.Frame(self._plot_scroll_canvas, bg=self._BG)
        self._plot_inner_window = self._plot_scroll_canvas.create_window(
            (0, 0),
            window=self._plot_inner,
            anchor="nw",
        )
        self._plot_inner.bind("<Configure>", self._on_plot_inner_configure)
        self._plot_scroll_canvas.bind("<Configure>", self._on_plot_canvas_configure)

        self._numeric_fields = []
        self._fig = Figure(figsize=(8, self._PLOT_HEIGHT_PER_AXIS), facecolor=self._BG)
        self._axes = []
        self._fig.subplots_adjust(hspace=0.65, left=0.13, right=0.97, top=0.95, bottom=0.07)

        self._canvas = FigureCanvasTkAgg(self._fig, master=self._plot_inner)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._canvas.mpl_connect("motion_notify_event", self._on_plot_hover)
        self._canvas.mpl_connect("figure_leave_event", self._on_plot_leave)

        self._series_cache = {}
        self._hover_annotation = None

        self._plot_tick = 0
        self._on_toggle_use_now()
        self._apply_window_settings()
        self._rebuild_value_rows()
        self._rebuild_plot_axes()
        self._refresh()

    def _on_toggle_use_now(self):
        if self.use_now_var.get():
            self.end_time_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self.end_time_entry.configure(state="disabled")
        else:
            self.end_time_entry.configure(state="normal")

    def _on_plot_inner_configure(self, _event):
        self._plot_scroll_canvas.configure(scrollregion=self._plot_scroll_canvas.bbox("all"))

    def _on_plot_canvas_configure(self, event):
        self._plot_scroll_canvas.itemconfigure(self._plot_inner_window, width=event.width)

    def _rebuild_value_rows(self):
        for widget in self.values_frame.winfo_children():
            widget.destroy()

        with self._register_lock:
            names = list(self._monitored_registers.keys())

        self.value_vars = {}
        if not names:
            tk.Label(
                self.values_frame,
                text="No registers configured",
                font=("Helvetica", 9, "italic"),
                bg=self._BG,
                fg=self._DIM,
                anchor="w",
            ).grid(row=0, column=0, columnspan=2, sticky="w")
            return

        for i, name in enumerate(names):
            tk.Label(
                self.values_frame,
                text=name,
                font=("Helvetica", 11),
                bg=self._BG,
                fg=self._FG,
                anchor="w",
                width=22,
            ).grid(row=i, column=0, sticky="w", pady=3)

            var = tk.StringVar(value="---")
            self.value_vars[name] = var
            tk.Label(
                self.values_frame,
                textvariable=var,
                font=("Helvetica", 11, "bold"),
                bg=self._BG,
                fg=self._ACCENT,
                anchor="e",
                width=14,
            ).grid(row=i, column=1, sticky="e", pady=3)

    def _rebuild_plot_axes(self):
        with self._register_lock:
            self._numeric_fields = [
                name
                for name, info in self._monitored_registers.items()
                if info["type"] == "register"
            ]

        self._fig.clear()
        n = max(len(self._numeric_fields), 1)
        self._fig.set_size_inches(8, n * self._PLOT_HEIGHT_PER_AXIS, forward=True)
        self._axes = [self._fig.add_subplot(n, 1, i + 1) for i in range(n)]
        self._canvas.draw()

    def _add_or_update_register(self):
        name = self.name_var.get().strip()
        address_text = self.address_var.get().strip()
        min_text = self.min_var.get().strip()
        max_text = self.max_var.get().strip()

        if not name:
            self.form_status_var.set("Name is required")
            return

        try:
            address = int(address_text)
        except ValueError:
            self.form_status_var.set("Address must be an integer")
            return

        try:
            min_value = float(min_text)
            max_value = float(max_text)
        except ValueError:
            self.form_status_var.set("Min and max must be numbers")
            return

        if min_value >= max_value:
            self.form_status_var.set("Min must be less than max")
            return

        with self._register_lock:
            self._monitored_registers[name] = {
                "address": address,
                "type": "register",
                "min": min_value,
                "max": max_value,
            }

        if self._persist_register is not None:
            self._persist_register(
                name,
                {
                    "address": address,
                    "type": "register",
                    "min": min_value,
                    "max": max_value,
                },
            )

        self._station_info_data[name] = "---"
        self.form_status_var.set(f"Saved register '{name}'")
        self._rebuild_value_rows()
        self._rebuild_plot_axes()

    def _parse_window_hours(self):
        text = self.window_hours_var.get().strip()
        try:
            hours = float(text)
            if hours <= 0:
                raise ValueError
            if hours > self._PLOT_LOOKBACK_DAYS * 24:
                raise ValueError
            self.range_status_var.set("")
            return hours
        except ValueError:
            self.range_status_var.set(
                f"Window hours must be > 0 and <= {self._PLOT_LOOKBACK_DAYS * 24}"
            )
            return None

    def _parse_end_time(self):
        if self.use_now_var.get():
            return datetime.now()

        text = self.end_time_var.get().strip()
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            self.range_status_var.set("End time must match YYYY-MM-DD HH:MM:SS")
            return None

        now = datetime.now()
        earliest = now - timedelta(days=self._PLOT_LOOKBACK_DAYS)
        if dt > now:
            self.range_status_var.set("End time cannot be in the future")
            return None
        if dt < earliest:
            self.range_status_var.set(
                f"End time must be within the last {self._PLOT_LOOKBACK_DAYS} days"
            )
            return None

        return dt

    def _apply_window_settings(self):
        hours = self._parse_window_hours()
        if hours is None:
            return

        end_time = self._parse_end_time()
        if end_time is None:
            return

        self._active_window_hours = hours
        self._active_use_now = self.use_now_var.get()
        self._active_end_time = None if self._active_use_now else end_time
        self.range_status_var.set("Window settings applied")

    def _get_window_data(self):
        hours = self._active_window_hours
        end_time = datetime.now() if self._active_use_now else self._active_end_time
        if end_time is None:
            return None

        with self._plot_buffer_lock:
            timestamps = list(self._plot_timestamps)
            series_by_name = {
                name: list(values)
                for name, values in self._plot_buffers.items()
            }

        latest_log_dt = end_time
        cutoff = latest_log_dt - timedelta(hours=hours)

        now = datetime.now()
        earliest_allowed = now - timedelta(days=self._PLOT_LOOKBACK_DAYS)
        if cutoff < earliest_allowed:
            cutoff = earliest_allowed
            self.range_status_var.set(
                f"Window start capped to {self._PLOT_LOOKBACK_DAYS}-day history limit"
            )
        else:
            self.range_status_var.set("")

        first_idx = 0
        while first_idx < len(timestamps) and timestamps[first_idx] < cutoff:
            first_idx += 1

        return cutoff, latest_log_dt, timestamps, series_by_name, first_idx

    def _on_plot_leave(self, _event):
        if self._hover_annotation is not None:
            self._hover_annotation.set_visible(False)
            self._canvas.draw_idle()

    def _on_plot_hover(self, event):
        ax = event.inaxes
        if ax is None or event.xdata is None:
            self._on_plot_leave(event)
            return

        series = self._series_cache.get(ax)
        if not series or not series["xs"]:
            self._on_plot_leave(event)
            return

        xs = series["xs"]
        ys = series["ys"]
        idx = min(range(len(xs)), key=lambda i: abs(xs[i] - event.xdata))
        x_val = xs[idx]
        y_val = ys[idx]
        dt_text = mdates.num2date(x_val).strftime("%Y-%m-%d %H:%M:%S")
        tip_text = f"{series['name']}\n{dt_text}\n{y_val:.2f}"

        # Axes are recreated during plot updates, so discard stale annotations.
        if self._hover_annotation is not None and self._hover_annotation.axes not in self._fig.axes:
            self._hover_annotation = None

        if self._hover_annotation is None or self._hover_annotation.axes is not ax:
            self._hover_annotation = ax.annotate(
                "",
                xy=(x_val, y_val),
                xytext=(10, 12),
                textcoords="offset points",
                fontsize=10,
                color=self._FG,
                bbox={"boxstyle": "round,pad=0.3", "fc": self._PLOT_BG, "ec": self._SEP, "alpha": 0.95},
                arrowprops={"arrowstyle": "->", "color": self._DIM},
            )

        self._hover_annotation.xy = (x_val, y_val)
        self._hover_annotation.set_text(tip_text)
        self._hover_annotation.set_visible(True)
        self._canvas.draw_idle()

    def _refresh(self):
        # Update live value labels
        self.status_var.set(self._get_connection_status())
        if self.use_now_var.get():
            self.end_time_var.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        for name, var in self.value_vars.items():
            var.set(str(self._station_info_data.get(name, "---")))
        self.updated_var.set(f"Last updated: {time.strftime('%H:%M:%S')}")

        # Redraw plot in sync with the poll interval
        self._plot_tick += 1
        if self._plot_tick >= self._poll_interval:
            self._plot_tick = 0
            self._update_plot()

        self.after(1000, self._refresh)

    def _update_plot(self):
        window_data = self._get_window_data()
        if window_data is None:
            return

        cutoff, latest_log_dt, timestamps, series_by_name, first_idx = window_data
        self._series_cache = {}
        self._hover_annotation = None

        with self._register_lock:
            config_by_name = dict(self._monitored_registers)

        if not self._numeric_fields:
            ax = self._axes[0]
            ax.clear()
            ax.set_facecolor(self._PLOT_BG)
            ax.text(
                0.5,
                0.5,
                "Add a register to start plotting",
                color=self._DIM,
                fontsize=14,
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_color(self._SEP)
            self._canvas.draw()
            return

        for ax, name in zip(self._axes, self._numeric_fields):
            ax.clear()
            vx = []
            vy = []

            values = series_by_name.get(name, [])
            if timestamps and first_idx < len(timestamps):
                for idx in range(first_idx, len(timestamps)):
                    if idx >= len(values):
                        continue
                    vx.append(mdates.date2num(timestamps[idx]))
                    vy.append(float(values[idx]))

                if vx and timestamps[first_idx] > cutoff:
                    vx.insert(0, mdates.date2num(cutoff))
                    vy.insert(0, vy[0])

                if vx and timestamps[-1] < latest_log_dt:
                    vx.append(mdates.date2num(latest_log_dt))
                    vy.append(vy[-1])

            if vx:
                ax.plot(vx, vy, color=self._ACCENT, linewidth=1.5)
            else:
                ax.text(
                    0.5,
                    0.5,
                    "No data in selected range",
                    color=self._DIM,
                    fontsize=10,
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                )

            ax.set_xlim(mdates.date2num(cutoff), mdates.date2num(latest_log_dt))

            self._series_cache[ax] = {"name": name, "xs": vx, "ys": vy}

            cfg = config_by_name.get(name, {})
            min_y = cfg.get("min")
            max_y = cfg.get("max")
            if isinstance(min_y, (int, float)) and isinstance(max_y, (int, float)) and min_y < max_y:
                ax.set_ylim(min_y, max_y)

            ax.set_title(name, color=self._FG, fontsize=14, pad=6, loc="left")
            ax.set_facecolor(self._PLOT_BG)
            ax.tick_params(axis="y", colors=self._DIM, labelsize=11)
            ax.tick_params(axis="x", colors=self._DIM, labelsize=11, labelbottom=True, rotation=20)
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            for spine in ax.spines.values():
                spine.set_color(self._SEP)

            ax.set_xlabel("Time", color=self._DIM, fontsize=10)

        self._canvas.draw()
