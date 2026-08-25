"""In-memory resource history and chart-layout calculations."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class ResourceSample:
    timestamp: float
    cpu: float | None
    memory: float | None
    state: str = "Running"


@dataclass
class ChartPoint:
    x: float
    y: float
    timestamp: float
    value: float


@dataclass
class ChartSeries:
    name: str
    color: str
    points: list[ChartPoint]
    segments: list[list[tuple[float, float]]]
    last_value: float | None = None


@dataclass
class ChartAxisTick:
    pos: float
    label: str
    value: float


@dataclass
class ChartLayout:
    plot_x0: float
    plot_y0: float
    plot_x1: float
    plot_y1: float
    y_min: float
    y_max: float
    t_min: float
    t_max: float
    y_ticks: list[ChartAxisTick]
    x_ticks: list[ChartAxisTick]
    series: list[ChartSeries]
    empty: bool = False


def find_nearest_chart_point(
    layout: ChartLayout, x: float, y: float, max_distance: float = 12.0
) -> tuple[ChartSeries, ChartPoint] | None:
    """Return the plotted point nearest to a canvas coordinate.

    ``None`` is returned when the cursor is outside the requested hit radius.
    Keeping this calculation independent from tkinter makes hover behaviour
    deterministic and testable on every supported platform.
    """
    try:
        cursor_x, cursor_y, radius = float(x), float(y), float(max_distance)
    except (TypeError, ValueError):
        return None
    if (
        not all(math.isfinite(value) for value in (cursor_x, cursor_y, radius))
        or radius < 0
    ):
        return None

    nearest: tuple[ChartSeries, ChartPoint] | None = None
    nearest_distance_squared = radius * radius
    for series in layout.series:
        for point in series.points:
            distance_squared = (
                (point.x - cursor_x) ** 2 + (point.y - cursor_y) ** 2
            )
            if distance_squared <= nearest_distance_squared:
                nearest = (series, point)
                nearest_distance_squared = distance_squared
    return nearest


DEFAULT_PALETTE: list[str] = [
    "#2080f0",
    "#f05050",
    "#10b981",
    "#f59e0b",
    "#8b5cf6",
    "#06b6d4",
    "#ec4899",
    "#f97316",
    "#14b8a6",
    "#6366f1",
]


def get_distro_color(index_or_name: int | str, known_names: list[str] | None = None) -> str:
    if isinstance(index_or_name, int) and not isinstance(index_or_name, bool):
        return DEFAULT_PALETTE[index_or_name % len(DEFAULT_PALETTE)]
    name = str(index_or_name)
    if known_names and name in known_names:
        return DEFAULT_PALETTE[known_names.index(name) % len(DEFAULT_PALETTE)]
    return DEFAULT_PALETTE[sum(ord(char) for char in name) % len(DEFAULT_PALETTE)]


def parse_numeric_resource(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        cleaned = value.strip().removesuffix("%").strip()
        if cleaned.lower().endswith("mb"):
            cleaned = cleaned[:-2].strip()
        if not cleaned or cleaned == "-":
            return None
        try:
            result = float(cleaned)
        except (TypeError, ValueError):
            return None
    else:
        return None
    return result if math.isfinite(result) and result >= 0 else None


def calculate_nice_ceiling(max_val: float, min_ceiling: float = 100.0) -> float:
    if max_val <= 0 or not math.isfinite(max_val):
        return float(min_ceiling)
    target = max(float(min_ceiling), max_val * 1.15)
    magnitude = 10 ** math.floor(math.log10(target))
    fraction = target / magnitude
    for limit, nice_fraction in ((1.0, 1.0), (2.0, 2.0), (2.5, 2.5), (5.0, 5.0)):
        if fraction <= limit:
            return float(nice_fraction * magnitude)
    return float(10.0 * magnitude)


class ResourceHistory:
    DEFAULT_WINDOW_SECONDS = 1800.0
    DEFAULT_MAX_SAMPLES = 1200

    def __init__(
        self, window_seconds: float = DEFAULT_WINDOW_SECONDS, max_samples: int = DEFAULT_MAX_SAMPLES
    ) -> None:
        self.window_seconds = max(0.0, float(window_seconds))
        self.max_samples = max(1, int(max_samples))
        self._history: dict[str, list[ResourceSample]] = {}

    def record_sample(
        self,
        name: str,
        cpu: Any,
        memory: Any,
        timestamp: float | None = None,
        state: str = "Running",
    ) -> None:
        if not name or not isinstance(name, str):
            return
        try:
            sample_time = time.time() if timestamp is None else float(timestamp)
        except (TypeError, ValueError):
            return
        if not math.isfinite(sample_time):
            return
        self._history.setdefault(name, []).append(
            ResourceSample(
                sample_time,
                parse_numeric_resource(cpu),
                parse_numeric_resource(memory),
                str(state) if state is not None else "",
            )
        )
        self._prune_distro(name, sample_time)

    def record_refresh(
        self, distros: list[dict[str, Any]], timestamp: float | None = None
    ) -> None:
        try:
            refresh_time = time.time() if timestamp is None else float(timestamp)
        except (TypeError, ValueError):
            return
        if not math.isfinite(refresh_time):
            return
        active_names: set[str] = set()
        for distro in distros:
            if not isinstance(distro, dict):
                continue
            name = distro.get("name")
            if not isinstance(name, str) or not name:
                continue
            active_names.add(name)
            self.record_sample(
                name,
                distro.get("cpu"),
                distro.get("memory"),
                refresh_time,
                distro.get("state", "Running"),
            )
        for name in list(self._history):
            if name not in active_names:
                del self._history[name]
        self.prune(refresh_time)

    def prune(self, now: float | None = None) -> None:
        try:
            current_time = time.time() if now is None else float(now)
        except (TypeError, ValueError):
            return
        if not math.isfinite(current_time):
            return
        for name in list(self._history):
            self._prune_distro(name, current_time)
            if not self._history[name]:
                del self._history[name]

    def _prune_distro(self, name: str, now: float) -> None:
        samples = self._history.get(name, [])
        cutoff = now - self.window_seconds
        samples[:] = [sample for sample in samples if sample.timestamp >= cutoff]
        if len(samples) > self.max_samples:
            del samples[: -self.max_samples]

    def get_samples(self, name: str) -> list[ResourceSample]:
        return list(self._history.get(name, []))

    def get_distro_names(self) -> list[str]:
        return sorted(self._history)

    def get_series(self, name: str, metric: str = "cpu") -> list[tuple[float, float | None]]:
        samples = self._history.get(name, [])
        if metric == "cpu":
            return [(sample.timestamp, sample.cpu) for sample in samples]
        if metric == "memory":
            return [(sample.timestamp, sample.memory) for sample in samples]
        raise ValueError(f"Unknown metric: {metric}")

    def clear(self) -> None:
        self._history.clear()

    def has_data(self) -> bool:
        return any(self._history.values())


def prepare_chart_layout(
    history: ResourceHistory | dict[str, list[ResourceSample]],
    metric: str,
    width: float,
    height: float,
    now: float | None = None,
    time_window: float | None = None,
    distro_colors: dict[str, str] | None = None,
    margins: tuple[float, float, float, float] = (45.0, 15.0, 20.0, 25.0),
) -> ChartLayout:
    if metric not in {"cpu", "memory"}:
        raise ValueError(f"Unknown metric: {metric}")
    left, right, top, bottom = margins
    plot_x0, plot_y0 = float(left), float(top)
    plot_x1, plot_y1 = (
        max(plot_x0 + 10.0, float(width) - right),
        max(plot_y0 + 10.0, float(height) - bottom),
    )
    try:
        current_time = time.time() if now is None else float(now)
    except (TypeError, ValueError):
        current_time = time.time()
    if not math.isfinite(current_time):
        current_time = time.time()
    if isinstance(history, ResourceHistory):
        window = history.window_seconds if time_window is None else float(time_window)
        distro_dict, names = history._history, history.get_distro_names()
    elif isinstance(history, dict):
        window = 1800.0 if time_window is None else float(time_window)
        distro_dict, names = history, sorted(history)
    else:
        window, distro_dict, names = 1800.0, {}, []
    if not math.isfinite(window) or window <= 0:
        window = 1800.0
    t_min, t_max = current_time - window, current_time
    t_range = max(1.0, t_max - t_min)
    values = [
        float(value)
        for samples in distro_dict.values()
        if isinstance(samples, list)
        for sample in samples
        if isinstance(sample, ResourceSample)
        and math.isfinite(sample.timestamp)
        and t_min <= sample.timestamp <= t_max
        for value in [sample.cpu if metric == "cpu" else sample.memory]
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and value >= 0
    ]
    y_min = 0.0
    y_max = (
        max(100.0, math.ceil(max(values, default=0.0) / 10.0) * 10.0)
        if metric == "cpu"
        else calculate_nice_ceiling(max(values, default=0.0))
    )
    y_range = max(1.0, y_max - y_min)
    y_ticks = [
        ChartAxisTick(
            plot_y1 - i / 4 * (plot_y1 - plot_y0),
            f"{(y_min + (y_max - y_min) * i / 4):.0f}%"
            if metric == "cpu"
            else (
                f"{(y_min + (y_max - y_min) * i / 4) / 1024:.1f}G"
                if y_max >= 1024 and y_min + (y_max - y_min) * i / 4 >= 1024
                else f"{y_min + (y_max - y_min) * i / 4:.0f}M"
            ),
            y_min + (y_max - y_min) * i / 4,
        )
        for i in range(5)
    ]
    x_ticks = [
        ChartAxisTick(
            plot_x0 + i / 3 * (plot_x1 - plot_x0),
            "現在" if i == 3 else f"-{round(window * (3 - i) / 3 / 60)}分",
            t_min + window * i / 3,
        )
        for i in range(4)
    ]
    series_list: list[ChartSeries] = []
    has_data = False
    for name in names:
        samples = distro_dict.get(name, [])
        if not isinstance(samples, list):
            continue
        points: list[ChartPoint] = []
        segments: list[list[tuple[float, float]]] = []
        segment: list[tuple[float, float]] = []
        last_value: float | None = None
        for sample in samples:
            if (
                not isinstance(sample, ResourceSample)
                or not math.isfinite(sample.timestamp)
                or not t_min <= sample.timestamp <= t_max
            ):
                continue
            value = sample.cpu if metric == "cpu" else sample.memory
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or value < 0
            ):
                if segment:
                    segments.append(segment)
                    segment = []
                continue
            numeric_value = float(value)
            x = plot_x0 + (sample.timestamp - t_min) / t_range * (plot_x1 - plot_x0)
            y = plot_y1 - (max(y_min, min(numeric_value, y_max)) - y_min) / y_range * (
                plot_y1 - plot_y0
            )
            points.append(ChartPoint(x, y, sample.timestamp, numeric_value))
            segment.append((x, y))
            last_value = numeric_value
            has_data = True
        if segment:
            segments.append(segment)
        if points or samples:
            color = (
                distro_colors.get(name)
                if distro_colors and name in distro_colors
                else get_distro_color(name, names)
            )
            series_list.append(ChartSeries(name, color, points, segments, last_value))
    return ChartLayout(
        plot_x0,
        plot_y0,
        plot_x1,
        plot_y1,
        y_min,
        y_max,
        t_min,
        t_max,
        y_ticks,
        x_ticks,
        series_list,
        not has_data,
    )
