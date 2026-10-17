"""リソース使用履歴グラフ (CPU / メモリの推移) の Mixin。"""

from __future__ import annotations

import functools
import tkinter as tk
from datetime import datetime
from tkinter import ttk

import wsl_core
from wslmgr_gui.app.base import AppBase


class ResourceHistoryMixin(AppBase):
    """``WSLManager`` に混ぜ込む、リソース履歴グラフの描画とツールチップ。"""

    def _build_resource_history_panel(self, parent: ttk.Frame) -> None:
        """CPU とメモリの最近30分の推移を表示する、折りたたみ可能なパネル。"""
        self._history_frame = ttk.Labelframe(parent, text="リソース履歴（直近30分）")
        self._cpu_history_canvas = tk.Canvas(
            self._history_frame, height=130, highlightthickness=0, background="white"
        )
        self._memory_history_canvas = tk.Canvas(
            self._history_frame, height=130, highlightthickness=0, background="white"
        )
        ttk.Label(self._history_frame, text="CPU 使用率").pack(anchor=tk.W, padx=6, pady=(4, 0))
        self._cpu_history_canvas.pack(fill=tk.X, padx=6)
        ttk.Label(self._history_frame, text="メモリ使用量").pack(anchor=tk.W, padx=6, pady=(2, 0))
        self._memory_history_canvas.pack(fill=tk.X, padx=6, pady=(0, 4))
        for canvas, metric in (
            (self._cpu_history_canvas, "cpu"),
            (self._memory_history_canvas, "memory"),
        ):
            canvas.bind("<Configure>", lambda _event: self._draw_resource_history())
            canvas.bind(
                "<Motion>",
                functools.partial(self._on_history_canvas_motion, canvas, metric),
            )
            canvas.bind("<Leave>", functools.partial(self._on_history_canvas_leave, canvas))

    def _toggle_resource_history(self) -> None:
        self._resource_history_visible = not self._resource_history_visible
        if self._resource_history_visible:
            self._history_frame.pack(fill=tk.X, pady=(6, 0), before=self._statusbar)
            self._history_toggle.configure(text="📈 履歴を隠す")
            self._draw_resource_history()
        else:
            self._clear_history_tooltip(self._cpu_history_canvas)
            self._clear_history_tooltip(self._memory_history_canvas)
            self._history_frame.pack_forget()
            self._history_toggle.configure(text="📈 履歴を表示")

    def _draw_resource_history(self) -> None:
        if not self._resource_history_visible:
            return
        self._draw_history_canvas(self._cpu_history_canvas, "cpu")
        self._draw_history_canvas(self._memory_history_canvas, "memory")

    def _draw_history_canvas(self, canvas: tk.Canvas, metric: str) -> None:
        """Canvas に1メトリックの系列・軸・凡例を安全に描画します。"""
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width <= 2 or height <= 2:
            self._history_layouts.pop(str(canvas), None)
            return
        layout = wsl_core.prepare_chart_layout(self._resource_history, metric, width, height)
        self._history_layouts[str(canvas)] = layout
        for tick in layout.y_ticks:
            canvas.create_line(layout.plot_x0, tick.pos, layout.plot_x1, tick.pos, fill="#e6e6e6")
            canvas.create_text(
                layout.plot_x0 - 4, tick.pos, text=tick.label, anchor=tk.E, fill="#555"
            )
        for tick in layout.x_ticks:
            canvas.create_line(tick.pos, layout.plot_y0, tick.pos, layout.plot_y1, fill="#f0f0f0")
            canvas.create_text(
                tick.pos,
                layout.plot_y1 + 12,
                text=tick.label,
                anchor=tk.N,
                fill="#555",
            )
        canvas.create_rectangle(
            layout.plot_x0, layout.plot_y0, layout.plot_x1, layout.plot_y1, outline="#bdbdbd"
        )
        for series in layout.series:
            for segment in series.segments:
                if len(segment) > 1:
                    coordinates = [coordinate for point in segment for coordinate in point]
                    canvas.create_line(*coordinates, fill=series.color, width=2)
                elif segment:
                    x, y = segment[0]
                    canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=series.color, outline="")
        if layout.empty:
            canvas.create_text(
                (layout.plot_x0 + layout.plot_x1) / 2,
                (layout.plot_y0 + layout.plot_y1) / 2,
                text="有効な履歴データはありません",
                fill="#666",
            )
        legend_x = layout.plot_x0 + 6
        for series in layout.series:
            canvas.create_line(
                legend_x,
                layout.plot_y0 + 8,
                legend_x + 12,
                layout.plot_y0 + 8,
                fill=series.color,
                width=2,
            )
            canvas.create_text(
                legend_x + 16,
                layout.plot_y0 + 8,
                text=series.name,
                anchor=tk.W,
                fill="#333",
            )
            legend_x += 22 + len(series.name) * 7

    def _on_history_canvas_motion(self, canvas: tk.Canvas, metric: str, event: tk.Event) -> None:
        """Show the nearest resource-history observation while the cursor is over a graph."""
        layout = self._history_layouts.get(str(canvas))
        if not self._resource_history_visible or layout is None:
            return
        nearest = wsl_core.find_nearest_chart_point(layout, event.x, event.y)
        if nearest is None:
            self._clear_history_tooltip(canvas)
            return
        series, point = nearest
        self._draw_history_tooltip(canvas, metric, series, point, event.x, event.y)

    @staticmethod
    def _resource_value_label(metric: str, value: float) -> str:
        """Format an exact sampled value for a resource-history tooltip."""
        return f"{value:.1f}%" if metric == "cpu" else f"{value:.1f} MB"

    def _draw_history_tooltip(
        self,
        canvas: tk.Canvas,
        metric: str,
        series: wsl_core.ChartSeries,
        point: wsl_core.ChartPoint,
        cursor_x: float,
        cursor_y: float,
    ) -> None:
        self._clear_history_tooltip(canvas)
        timestamp = datetime.fromtimestamp(point.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        value = self._resource_value_label(metric, point.value)
        label = f"{series.name}\n{timestamp}\n{value}"
        text_item = canvas.create_text(
            cursor_x + 12,
            cursor_y - 12,
            text=label,
            anchor=tk.SW,
            justify=tk.LEFT,
            fill="#111",
            tags="history-tooltip",
        )
        bbox = canvas.bbox(text_item)
        if bbox is None:
            return
        width, height = canvas.winfo_width(), canvas.winfo_height()
        dx = max(4 - bbox[0], min(0, width - 4 - bbox[2]))
        dy = max(4 - bbox[1], min(0, height - 4 - bbox[3]))
        if dx or dy:
            canvas.move(text_item, dx, dy)
        bbox = canvas.bbox(text_item)
        if bbox is not None:
            rectangle = canvas.create_rectangle(
                bbox[0] - 4,
                bbox[1] - 3,
                bbox[2] + 4,
                bbox[3] + 3,
                fill="#ffffe0",
                outline="#777",
                tags="history-tooltip",
            )
            canvas.tag_lower(rectangle, text_item)
        canvas.create_oval(
            point.x - 4,
            point.y - 4,
            point.x + 4,
            point.y + 4,
            outline=series.color,
            width=2,
            tags="history-tooltip",
        )

    def _on_history_canvas_leave(self, canvas: tk.Canvas, _event: tk.Event) -> None:
        self._clear_history_tooltip(canvas)

    @staticmethod
    def _clear_history_tooltip(canvas: tk.Canvas) -> None:
        canvas.delete("history-tooltip")
