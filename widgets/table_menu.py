"""Right-click menus for the tables, as in the Windows Task Manager.

Every page already has buttons for what can be done with the selected row;
`install_table_menu` offers the same actions on right-click (selecting the clicked
row first, so the buttons' enabled states fit it) and adds "Copy" / "Copy all",
which copy rows as tab-separated text that pastes cleanly into a spreadsheet."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QMenu

from app.i18n import tr


def _visible_columns(view: QAbstractItemView) -> list[int]:
    header = view.horizontalHeader()
    columns = [header.logicalIndex(v) for v in range(header.count())]
    return [c for c in columns if not header.isSectionHidden(c)]


def _row_text(model, row: int, columns: list[int]) -> str:
    cells = []
    for column in columns:
        value = model.data(model.index(row, column), Qt.DisplayRole)
        cells.append("" if value is None else str(value).replace("\n", " "))
    return "\t".join(cells)


def rows_text(view: QAbstractItemView, rows, with_header: bool = False) -> str:
    model = view.model()
    columns = _visible_columns(view)
    lines = []
    if with_header and not view.horizontalHeader().isHidden():
        lines.append("\t".join(
            str(model.headerData(c, Qt.Horizontal, Qt.DisplayRole) or "") for c in columns
        ))
    lines.extend(_row_text(model, row, columns) for row in rows)
    return "\n".join(lines)


def selected_rows(view: QAbstractItemView) -> list[int]:
    selection = view.selectionModel()
    if selection is None:
        return []
    return sorted({index.row() for index in selection.selectedIndexes()})


def copy_rows(view: QAbstractItemView, rows, with_header: bool = False) -> None:
    QApplication.clipboard().setText(rows_text(view, rows, with_header))


def add_copy_actions(menu: QMenu, view: QAbstractItemView, rows: list[int]) -> None:
    copy = menu.addAction(tr("Copy"))
    copy.setEnabled(bool(rows))
    copy.triggered.connect(lambda: copy_rows(view, rows))
    copy_all = menu.addAction(tr("Copy all"))
    total = view.model().rowCount()
    copy_all.setEnabled(total > 0)
    copy_all.triggered.connect(lambda: copy_rows(view, range(view.model().rowCount()), True))


def add_button_actions(menu: QMenu, buttons) -> None:
    """One menu entry per button (None adds a separator); triggering it clicks the
    button, so the page's own handler, confirmation dialogs included, runs."""
    for button in buttons:
        if button is None:
            menu.addSeparator()
            continue
        if button.isHidden():
            continue
        action = menu.addAction(button.text().replace("&", "&&") or button.toolTip())
        action.setEnabled(button.isEnabled())
        if not button.icon().isNull():
            action.setIcon(button.icon())
        if button.isCheckable():
            action.setCheckable(True)
            action.setChecked(button.isChecked())
        if button.toolTip():
            action.setToolTip(button.toolTip())
        action.triggered.connect(lambda _checked=False, b=button: b.click())


def install_table_menu(view: QAbstractItemView, buttons=(), extra=None) -> None:
    """`buttons` are the page's buttons for the selected row; `extra(menu, index)`
    may add page-specific entries at the end."""
    view.setContextMenuPolicy(Qt.CustomContextMenu)

    def show(position) -> None:
        index = view.indexAt(position)
        selection = view.selectionModel()
        if (index.isValid() and selection is not None
                and view.selectionMode() != QAbstractItemView.NoSelection
                and not selection.isRowSelected(index.row(), index.parent())):
            view.selectRow(index.row())
        rows = selected_rows(view)
        if not rows and index.isValid():
            rows = [index.row()]
        menu = QMenu(view)
        menu.setToolTipsVisible(True)
        add_button_actions(menu, buttons)
        if not menu.isEmpty():
            menu.addSeparator()
        add_copy_actions(menu, view, rows)
        if extra is not None:
            extra(menu, index)
        menu.exec(view.viewport().mapToGlobal(position))

    view.customContextMenuRequested.connect(show)
