"""Chart of a stored history: real time axis, gaps stay gaps, peaks shown as a band."""
from __future__ import annotations

import bisect
import math
import time
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.i18n import current_language, tr
from app.themes import WIN10_CHART_COLORS
from widgets.live_chart import _blend

# A bucket further from its neighbour than this means nothing was recorded in between.
GAP_STEPS = 2.5
_TICK_SECONDS = (60, 300, 600, 900, 1800, 3600, 2 * 3600, 3 * 3600, 6 * 3600, 12 * 3600,
                 86400, 2 * 86400, 7 * 86400, 14 * 86400, 30 * 86400, 60 * 86400, 90 * 86400)
_DAY = 86400


@dataclass
class ChartSeries:
    label: str
    color_key: str
    avg: list  # float or None per entry of the chart's times
    peak: list


def nice_maximum(value: float) -> float:
    """Top of the y axis: above `value`, and a quarter of it is still a round number."""
    if value <= 0:
        return 1.0
    power = 10 ** math.floor(math.log10(value))
    return next(factor * power for factor in (1, 2, 4, 6, 8, 10) if factor * power >= value)


def segments(times: list, values: list, step: float) -> list:
    """Index lists of the runs that belong together, split at gaps and missing values."""
    runs, current = [], []
    for index, value in enumerate(values):
        if value is None:
            if current:
                runs.append(current)
            current = []
            continue
        if current and times[index] - times[current[-1]] > GAP_STEPS * step:
            runs.append(current)
            current = []
        current.append(index)
    if current:
        runs.append(current)
    return runs


def format_time_label(moment: float, span: float) -> str:
    """Tick text: the time of day within one day, otherwise the date."""
    local = time.localtime(moment)
    if span <= _DAY:
        return time.strftime("%H:%M", local)
    return time.strftime("%d.%m." if current_language() == "de" else "%m-%d", local)


def format_moment(moment: float) -> str:
    pattern = "%d.%m.%Y %H:%M" if current_language() == "de" else "%Y-%m-%d %H:%M"
    return time.strftime(pattern, time.localtime(moment))


def time_ticks(start: float, end: float, max_ticks: int) -> list:
    """Round local times between start and end, not more than `max_ticks` of them."""
    span = end - start
    minimum = _DAY if span > _DAY else 0
    interval = next((seconds for seconds in _TICK_SECONDS
                     if seconds >= minimum and span / seconds <= max(1, max_ticks)),
                    _TICK_SECONDS[-1])
    offset = time.localtime(start).tm_gmtoff
    moment = math.ceil((start + offset) / interval) * interval - offset
    ticks = []
    while moment <= end:
        ticks.append(moment)
        # Snap again each time: a day with a clock change has 23 or 25 hours.
        moment += interval
        offset = time.localtime(moment).tm_gmtoff
        moment = round((moment + offset) / interval) * interval - offset
    return ticks


class HistoryChart(QWidget):
    """Lines of the averages, a band up to the peaks, one y axis. From the second series
    on the line is dashed, so that the colour isn't all that tells them apart."""

    def __init__(self, title: str, formatter, fixed_max: float | None = None, parent=None):
        super().__init__(parent)
        self.title = title
        self._format = formatter
        self._fixed_max = fixed_max
        self._dark = False
        self._bg = QColor("#ffffff")
        self._colors = dict(WIN10_CHART_COLORS)
        self._start, self._end, self._step = 0.0, 1.0, 1.0
        self._times: list = []
        self._series: list[ChartSeries] = []
        self._maximum = fixed_max or 1.0
        self._hover: int | None = None
        self._label_width = 0
        self.setMouseTracking(True)
        self.setMinimumSize(420, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName(title)

    def sizeHint(self):
        size = super().sizeHint()
        size.setHeight(190)
        return size

    def set_theme(self, dark: bool, background: str | None, colors: dict) -> None:
        self._dark = dark
        self._bg = QColor(background or ("#1c1c1c" if dark else "#ffffff"))
        self._colors = dict(colors)
        self.update()

    def set_data(self, start: float, end: float, step: float, times: list,
                 series: list[ChartSeries]) -> None:
        self._start, self._end, self._step = start, max(end, start + 1), step
        self._times = times
        self._series = series
        highest = max((value for entry in series for value in entry.peak if value is not None),
                      default=0.0)
        self._maximum = self._fixed_max or nice_maximum(highest)
        self._hover = None
        self.update()

    def _text_color(self) -> QColor:
        return QColor("#dddddd" if self._dark else "#333333")

    def _muted_color(self) -> QColor:
        return _blend(self._text_color(), self._bg, 0.65)

    def axis_label_width(self) -> int:
        """Room the labels of the y axis need with the current data."""
        return max(self.fontMetrics().horizontalAdvance(self._format(self._maximum * i / 4))
                   for i in range(5))

    def set_label_width(self, width: int) -> None:
        """Reserve this much for the y axis, so that stacked charts share their time axis."""
        self._label_width = width
        self.update()

    def _plot_rect(self) -> QRectF:
        metrics = self.fontMetrics()
        label_width = max(self.axis_label_width(), self._label_width)
        top = metrics.height() * 2 + 14
        return QRectF(label_width + 14, top, max(1, self.width() - label_width - 26),
                      max(1, self.height() - top - metrics.height() - 10))

    def _x(self, plot: QRectF, moment: float) -> float:
        return plot.left() + (moment - self._start) / (self._end - self._start) * plot.width()

    def _y(self, plot: QRectF, value: float) -> float:
        return plot.bottom() - min(value, self._maximum) / self._maximum * plot.height()

    def _pen(self, index: int, color: QColor) -> QPen:
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.FlatCap if index else Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if index:
            pen.setDashPattern([4, 2])
        return pen

    def _color(self, entry: ChartSeries) -> QColor:
        return QColor(self._colors.get(entry.color_key, "#117dbb"))

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self._bg)
        plot = self._plot_rect()
        self._draw_header(painter)
        self._draw_axes(painter, plot)
        painter.save()
        painter.setClipRect(plot.adjusted(0, -2, 0, 2))
        for index, entry in enumerate(self._series):
            self._draw_series(painter, plot, index, entry)
        painter.restore()
        if self._hover is not None:
            self._draw_hover(painter, plot)

    def _draw_header(self, painter: QPainter) -> None:
        metrics = self.fontMetrics()
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self._text_color())
        painter.drawText(QPointF(8, metrics.ascent() + 4), self.title)
        font.setBold(False)
        painter.setFont(font)
        x = 8.0
        y = metrics.height() + metrics.ascent() + 6
        for index, entry in enumerate(self._series):
            painter.setPen(self._pen(index, self._color(entry)))
            middle = y - metrics.ascent() / 2 + 1
            painter.drawLine(QPointF(x, middle), QPointF(x + 18, middle))
            averages = [value for value in entry.avg if value is not None]
            peaks = [value for value in entry.peak if value is not None]
            text = tr("{name}: average {average}, peak {peak}", name=entry.label,
                      average=self._format(sum(averages) / len(averages)) if averages else "-",
                      peak=self._format(max(peaks)) if peaks else "-")
            painter.setPen(self._muted_color())
            painter.drawText(QPointF(x + 24, y), text)
            x += 24 + metrics.horizontalAdvance(text) + 18

    def _draw_axes(self, painter: QPainter, plot: QRectF) -> None:
        metrics = self.fontMetrics()
        grid = _blend(self._text_color(), self._bg, 0.14)
        for i in range(5):
            value = self._maximum * i / 4
            y = self._y(plot, value)
            painter.setPen(QPen(grid, 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            label = self._format(value)
            painter.setPen(self._muted_color())
            painter.drawText(QPointF(plot.left() - 8 - metrics.horizontalAdvance(label),
                                     y + metrics.ascent() / 2 - 1), label)
        span = self._end - self._start
        widest = metrics.horizontalAdvance(format_time_label(self._end, span)) + 24
        baseline = plot.bottom() + metrics.height() + 2
        for moment in time_ticks(self._start, self._end, int(plot.width() / widest)):
            x = self._x(plot, moment)
            painter.setPen(QPen(grid, 1))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            label = format_time_label(moment, span)
            half = metrics.horizontalAdvance(label) / 2
            painter.setPen(self._muted_color())
            painter.drawText(QPointF(min(x - half, self.width() - 2 * half - 2), baseline), label)

    def _draw_series(self, painter: QPainter, plot: QRectF, index: int,
                     entry: ChartSeries) -> None:
        color = self._color(entry)
        band = QColor(color)
        band.setAlphaF(0.2)
        for run in segments(self._times, entry.avg, self._step):
            line = [QPointF(self._x(plot, self._times[i]), self._y(plot, entry.avg[i]))
                    for i in run]
            tops = [QPointF(point.x(), self._y(plot, entry.peak[i]
                                               if entry.peak[i] is not None else entry.avg[i]))
                    for point, i in zip(line, run)]
            if len(line) == 1:
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(line[0], 2.5, 2.5)
                continue
            painter.setPen(Qt.NoPen)
            painter.setBrush(band)
            painter.drawPolygon(QPolygonF(line + tops[::-1]))
            path = QPainterPath(line[0])
            for point in line[1:]:
                path.lineTo(point)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(self._pen(index, color))
            painter.drawPath(path)

    def _draw_hover(self, painter: QPainter, plot: QRectF) -> None:
        moment = self._times[self._hover]
        x = self._x(plot, moment)
        painter.setPen(QPen(self._muted_color(), 1))
        painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        lines = [format_moment(moment)]
        for entry in self._series:
            average, peak = entry.avg[self._hover], entry.peak[self._hover]
            if average is None:
                continue
            painter.setPen(QPen(self._bg, 2))
            painter.setBrush(self._color(entry))
            painter.drawEllipse(QPointF(x, self._y(plot, average)), 4, 4)
            lines.append(tr("{name}: average {average}, peak {peak}", name=entry.label,
                            average=self._format(average),
                            peak=self._format(average if peak is None else peak)))
        metrics = self.fontMetrics()
        width = max(metrics.horizontalAdvance(line) for line in lines) + 16
        height = metrics.height() * len(lines) + 10
        left = x + 10 if x + 10 + width <= self.width() else max(0, x - 10 - width)
        box = QRectF(left, plot.top() + 2, width, height)
        painter.setPen(QPen(self._muted_color(), 1))
        painter.setBrush(self._bg)
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(self._text_color())
        y = box.top() + 5 + metrics.ascent()
        for line in lines:
            painter.drawText(QPointF(box.left() + 8, y), line)
            y += metrics.height()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._hover = self._index_at(event.position().x())
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._hover = None
        self.update()

    def _index_at(self, x: float) -> int | None:
        """The bucket under the mouse; none where nothing was recorded."""
        plot = self._plot_rect()
        if not self._times or not plot.left() <= x <= plot.right():
            return None
        moment = self._start + (x - plot.left()) / plot.width() * (self._end - self._start)
        right = bisect.bisect_left(self._times, moment)
        candidates = [i for i in (right - 1, right) if 0 <= i < len(self._times)]
        best = min(candidates, key=lambda i: abs(self._times[i] - moment))
        return best if abs(self._times[best] - moment) <= GAP_STEPS * self._step / 2 else None
