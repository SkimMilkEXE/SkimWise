from datetime import datetime

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QHorizontalBarSeries,
    QLineSeries,
    QValueAxis,
)
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QToolTip, QVBoxLayout, QWidget

from skimwise.services.money import format_cents
from skimwise.services.reports import MonthTotals, ReportService
from skimwise.ui.colors import chart_color
from skimwise.ui.settings import month_label

MONTHS_SHOWN = 12


class ChartsView(QWidget):
    """Three charts for the chosen month: spending by category, the monthly spending trend,
    and income vs expenses. The trend charts cover the 12 months ending at the chosen month."""

    def __init__(self, reports: ReportService):
        super().__init__()
        self.reports = reports

        self.month = QComboBox()
        self.month.currentIndexChanged.connect(self.redraw)
        # QChartView is the widget; each redraw swaps in a freshly built QChart.
        self.by_category, self.trend, self.income_expenses = (QChartView() for _ in range(3))
        for view in (self.by_category, self.trend, self.income_expenses):
            view.setRenderHint(QPainter.RenderHint.Antialiasing)
            view.setMinimumHeight(220)

        bar = QHBoxLayout()
        bar.addStretch()
        bar.addWidget(QLabel("Month:"))
        bar.addWidget(self.month)

        grid = QGridLayout()
        grid.addWidget(self.by_category, 0, 0)
        grid.addWidget(self.trend, 0, 1)
        grid.addWidget(self.income_expenses, 1, 0, 1, 2)  # full width

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addLayout(grid)

        self.refresh()

    def refresh(self) -> None:
        current = self.month.currentData()
        self.month.blockSignals(True)
        self.month.clear()
        for m in self.reports.months():
            self.month.addItem(month_label(m), m)
        self.month.setCurrentIndex(max(0, self.month.findData(current)))  # defaults to the newest month
        self.month.blockSignals(False)
        self.redraw()

    def redraw(self) -> None:
        month = self.month.currentData()
        totals = self.reports.monthly_totals(month, MONTHS_SHOWN)
        first, last = (f"{_short(m)} {m[:4]}" for m in (totals[0].month, month))
        span = last if first == last else f"{first} – {last}"
        _set_chart(self.by_category, self._category_chart(month))
        _set_chart(self.trend, self._trend_chart(totals, span))
        _set_chart(self.income_expenses, self._income_expenses_chart(totals, span))

    def _category_chart(self, month: str) -> QChart:
        rows = self.reports.spending_by_category(month)
        chart = _chart(f"Spending by category · {month_label(month)}")
        if not rows:
            return _empty(chart, "No spending this month")
        rows.reverse()  # horizontal bars draw bottom-up; this puts the largest on top
        bars = QBarSet("Spending")
        bars.append([cents / 100 for _, cents in rows])
        bars.setColor(chart_color("spending"))
        bars.setBorderColor(chart_color("spending"))
        series = QHorizontalBarSeries()
        series.append(bars)
        series.setBarWidth(0.6)
        _tooltips(series, lambda i, _set: f"{rows[i][0]}: {format_cents(rows[i][1])}")
        chart.addSeries(series)
        _attach_axes(chart, series, [name for name, _ in rows], horizontal=True)
        return chart

    def _trend_chart(self, totals: list[MonthTotals], span: str) -> QChart:
        chart = _chart(f"Monthly spending · {span}")
        if not any(t.expense_cents for t in totals):
            return _empty(chart, "No spending in this period")
        series = QLineSeries()
        for i, t in enumerate(totals):
            series.append(i, t.expense_cents / 100)
        pen = QPen(chart_color("spending"), 2)
        series.setPen(pen)
        series.setPointsVisible(True)
        series.setMarkerSize(6)

        def hovered(point, state):
            if state:
                t = totals[round(point.x())]
                QToolTip.showText(QCursor.pos(), f"{month_label(t.month)}: {format_cents(t.expense_cents)}")
            else:
                QToolTip.hideText()

        series.hovered.connect(hovered)
        chart.addSeries(series)
        _attach_axes(chart, series, [_short(t.month) for t in totals])
        return chart

    def _income_expenses_chart(self, totals: list[MonthTotals], span: str) -> QChart:
        chart = _chart(f"Income vs expenses · {span}")
        if not any(t.income_cents or t.expense_cents for t in totals):
            return _empty(chart, "No transactions in this period")
        series = QBarSeries()
        for name, role, attr in (("Income", "income", "income_cents"), ("Expenses", "spending", "expense_cents")):
            bars = QBarSet(name)
            bars.append([getattr(t, attr) / 100 for t in totals])
            bars.setColor(chart_color(role))
            bars.setBorderColor(chart_color(role))
            series.append(bars)
        series.setBarWidth(0.7)
        _tooltips(
            series,
            lambda i, bars: (
                f"{month_label(totals[i].month)} {bars.label().lower()}: {format_cents(round(bars.at(i) * 100))}"
            ),
        )
        chart.addSeries(series)
        _attach_axes(chart, series, [_short(t.month) for t in totals])
        # Two series, so a legend (colour alone never identifies a series).
        chart.legend().setVisible(True)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignTop)
        chart.legend().setLabelColor(chart_color("ink"))
        return chart


def _chart(title: str) -> QChart:
    """A chart with the app's look: transparent background, themed title, no legend by default."""
    chart = QChart()
    chart.setTitle(title)
    font = QFont(chart.titleFont())
    font.setBold(True)
    chart.setTitleFont(font)
    chart.setTitleBrush(chart_color("ink"))
    chart.setBackgroundVisible(False)  # let the window colour show through, in light and dark
    chart.legend().setVisible(False)
    chart.setMargins(QMargins(0, 0, 0, 0))
    return chart


def _empty(chart: QChart, message: str) -> QChart:
    chart.setTitle(f"{chart.title()} · {message}")
    return chart


def _attach_axes(chart: QChart, series, categories: list[str], horizontal: bool = False) -> None:
    """Category axis for the labels, value axis in dollars starting at zero; recessive colours."""
    labels = QBarCategoryAxis()
    labels.append(categories)
    values = QValueAxis()
    values.setLabelFormat("$%.0f")
    for axis in (labels, values):
        axis.setLabelsBrush(chart_color("label"))
        axis.setLinePenColor(chart_color("axis"))
        axis.setGridLineColor(chart_color("grid"))
    labels.setGridLineVisible(False)
    labels.setTruncateLabels(False)  # Qt shortens labels to "…" in narrow charts; category names must stay readable
    label_side, value_side = (Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignBottom)
    if not horizontal:
        label_side, value_side = value_side, label_side
    chart.addAxis(labels, label_side)
    chart.addAxis(values, value_side)
    series.attachAxis(labels)
    series.attachAxis(values)
    # Money starts at $0, or small changes look huge. Set after attaching: attaching resets the range.
    values.setMin(0)
    values.applyNiceNumbers()  # round tick steps like $0, $500, $1,000


def _tooltips(series, text) -> None:
    """Show `text(index, bar_set)` while hovering a bar."""

    def hovered(status, index, bars):
        if status:
            QToolTip.showText(QCursor.pos(), text(index, bars))
        else:
            QToolTip.hideText()

    series.hovered.connect(hovered)


def _set_chart(view: QChartView, chart: QChart) -> None:
    old = view.chart()
    view.setChart(chart)
    old.deleteLater()  # QChartView doesn't free the chart it replaces


def _short(year_month: str) -> str:
    """ "2026-09" -> "Sep". Compact enough for 12 labels on an axis; titles carry the years."""
    return datetime.strptime(year_month, "%Y-%m").strftime("%b")
