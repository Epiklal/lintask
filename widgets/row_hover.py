"""Whole-row hover for table views, as in the Windows Task Manager.

Qt only marks the single cell under the mouse as hovered; Windows highlights the
entire row. `enable_row_hover` tracks the hovered row on the view and installs a
delegate that flags every cell of that row as hovered (and never draws the dotted
focus rectangle), so the `::item:hover` stylesheet rule tints the full row."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QAbstractItemView, QStyle, QStyledItemDelegate

_HOVER_ROW = "_hover_row"


def hovered_row(view) -> int:
    return getattr(view, _HOVER_ROW, -1) if view is not None else -1


class RowHoverDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index) -> None:  # noqa: N802 (Qt override)
        super().initStyleOption(option, index)
        if index.row() == hovered_row(option.widget):
            option.state |= QStyle.State_MouseOver
        else:
            option.state &= ~QStyle.State_MouseOver
        option.state &= ~QStyle.State_HasFocus


class _HoverTracker(QObject):
    def __init__(self, view: QAbstractItemView):
        super().__init__(view)
        self._view = view
        view.verticalScrollBar().valueChanged.connect(self._update_from_cursor)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        kind = event.type()
        if kind == QEvent.MouseMove:
            self._set_row(self._view.indexAt(event.position().toPoint()).row())
        elif kind == QEvent.Leave:
            self._set_row(-1)
        return False

    def _update_from_cursor(self) -> None:
        viewport = self._view.viewport()
        pos = viewport.mapFromGlobal(QCursor.pos())
        row = self._view.indexAt(pos).row() if viewport.rect().contains(pos) else -1
        self._set_row(row)

    def _set_row(self, row: int) -> None:
        if row != hovered_row(self._view):
            setattr(self._view, _HOVER_ROW, row)
            self._view.viewport().update()


def enable_row_hover(view: QAbstractItemView) -> None:
    """Highlight the whole row under the mouse. Column delegates set later should
    derive from RowHoverDelegate to take part."""
    view.setMouseTracking(True)
    view.viewport().installEventFilter(_HoverTracker(view))
    view.setItemDelegate(RowHoverDelegate(view))
