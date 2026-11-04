"""Tests for the Processes tab: the RAM and swap columns and moving a program to swap."""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from app.i18n import set_language
from app.memory_info import ERROR_NOT_SET_UP, MIB, PageOutResult
from app.system_info import ProcessRow, ProcessWorker, _process_swap_mb
from pages import processes_page
from pages.processes_page import COLUMNS, TOTAL_ROLE, ProcessesPage, ProcessTableModel

RAM_COLUMN = 3
SWAP_COLUMN = 4


def setUpModule():
    set_language("en")


def tearDownModule():
    set_language("system")


def make_row(pid=100, name="app", username="someone", memory_mb=10.0, swap_mb=0.0):
    return ProcessRow(pid=pid, name=name, username=username, status="running", cpu_percent=0.0,
                      memory_mb=memory_mb, num_threads=1, swap_mb=swap_mb)


def make_model(rows, **totals):
    model = ProcessTableModel()
    model._current_user = "someone"
    model.set_rows(rows, **totals)
    return model


def row_of(model, name):
    for row in range(model.rowCount()):
        text = model.index(row, 0).data(Qt.DisplayRole)
        if text and text.startswith(name):
            return row
    raise AssertionError(f"{name} is not in the list")


class FakeSettings:
    def column_widths(self, _key):
        return {}

    def set_column_widths(self, _key, _widths):
        pass

    def row_height(self, _key, default):
        return default

    def set_row_height(self, _key, _height):
        pass


class ProcessTableModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ram_and_swap_have_their_own_columns(self):
        self.assertEqual(COLUMNS[RAM_COLUMN], "RAM")
        self.assertEqual(COLUMNS[SWAP_COLUMN], "Swap")

    def test_shows_the_swap_of_a_process(self):
        model = make_model([make_row(swap_mb=12.5)])
        row = row_of(model, "app")
        self.assertIn("12", model.index(row, SWAP_COLUMN).data(Qt.DisplayRole))
        self.assertIn("MB", model.index(row, SWAP_COLUMN).data(Qt.DisplayRole))

    def test_unreadable_swap_shows_a_dash(self):
        model = make_model([make_row(swap_mb=None)])
        self.assertEqual(model.index(row_of(model, "app"), SWAP_COLUMN).data(Qt.DisplayRole), "–")

    def test_a_group_adds_up_its_processes(self):
        model = make_model([make_row(pid=1, swap_mb=10.0), make_row(pid=2, swap_mb=None),
                            make_row(pid=3, swap_mb=20.0)])
        members = model.rows_at(row_of(model, "app"))
        self.assertEqual({row.pid for row in members}, {1, 2, 3})
        self.assertIn("30", model.index(row_of(model, "app"), SWAP_COLUMN).data(Qt.DisplayRole))

    def test_sorting_by_swap_copes_with_unreadable_values(self):
        model = make_model([make_row(pid=1, name="small", swap_mb=1.0),
                            make_row(pid=2, name="unknown", swap_mb=None),
                            make_row(pid=3, name="large", swap_mb=50.0)])
        model.set_sort(SWAP_COLUMN, Qt.DescendingOrder)
        self.assertLess(row_of(model, "large"), row_of(model, "small"))
        self.assertLess(row_of(model, "small"), row_of(model, "unknown"))

    def test_header_totals_show_the_system_percentages(self):
        model = make_model([make_row()], memory_percent=42.0, swap_percent=7.0)
        self.assertIn("42", model.headerData(RAM_COLUMN, Qt.Horizontal, TOTAL_ROLE))
        self.assertIn("7", model.headerData(SWAP_COLUMN, Qt.Horizontal, TOTAL_ROLE))

    def test_a_row_without_a_process_has_no_rows(self):
        model = make_model([make_row()])
        self.assertEqual(model.rows_at(-1), [])


class MoveToSwapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # One page without a running worker: a page dropped while its worker thread runs
        # can be collected on that thread, which Qt doesn't survive.
        cls.page = ProcessesPage(FakeSettings())
        cls.page.shutdown()

    def setUp(self):
        self.page._remote_enabled = False
        self.page.model._current_user = "someone"
        swap = mock.patch.object(processes_page.psutil, "swap_memory",
                                 return_value=mock.Mock(total=4 * 1024 * MIB))
        swap.start()
        self.addCleanup(swap.stop)

    def test_an_ordinary_program_can_be_moved(self):
        self.assertEqual(self.page._swap_block_reason([make_row()]), "")

    def test_refuses_in_the_remote_view(self):
        self.page._remote_enabled = True
        self.assertTrue(self.page._swap_block_reason([make_row()]))

    def test_refuses_its_own_process(self):
        reason = self.page._swap_block_reason([make_row(pid=os.getpid())])
        self.assertEqual(reason, "Lintask cannot move itself to swap.")

    def test_refuses_what_the_desktop_needs(self):
        with mock.patch.object(processes_page, "is_essential", return_value=True):
            reason = self.page._swap_block_reason([make_row()])
        self.assertEqual(reason, "The desktop needs this program, so it cannot be moved to swap.")

    def test_refuses_a_program_of_another_user(self):
        reason = self.page._swap_block_reason([make_row(username="other")])
        self.assertEqual(reason, "This program belongs to another user.")

    def test_refuses_without_swap(self):
        with mock.patch.object(processes_page.psutil, "swap_memory",
                               return_value=mock.Mock(total=0)):
            reason = self.page._swap_block_reason([make_row()])
        self.assertEqual(reason, "No swap is set up, so nothing can be moved out of memory.")

    def test_answering_no_starts_nothing(self):
        row = make_row(pid=os.getppid())
        with mock.patch.object(processes_page.QMessageBox, "question",
                               return_value=QMessageBox.No) as question, \
                mock.patch.object(processes_page, "PageOutWorker") as worker:
            self.page._move_to_swap([row])
        question.assert_called_once()
        worker.assert_not_called()
        self.assertIsNone(self.page._swap_worker)

    def test_shows_the_error_of_a_failed_move(self):
        result = PageOutResult("app", error=ERROR_NOT_SET_UP)
        with mock.patch.object(processes_page.QMessageBox, "warning") as warning, \
                mock.patch.object(processes_page.QMessageBox, "information") as information:
            self.page._on_swap_result(result)
        self.assertEqual(warning.call_args.args[2], ERROR_NOT_SET_UP)
        information.assert_not_called()


class SwapResultTextTest(unittest.TestCase):
    def test_says_when_hardly_anything_moved(self):
        text = ProcessesPage._swap_result_text(PageOutResult("app", moved_bytes=MIB))
        self.assertTrue(text.startswith("app: hardly anything could be moved."))

    def test_says_how_much_moved(self):
        text = ProcessesPage._swap_result_text(PageOutResult("app", moved_bytes=512 * MIB))
        self.assertIn("moved to swap.", text)
        self.assertIn("512", text)

    def test_mentions_protected_processes(self):
        text = ProcessesPage._swap_result_text(
            PageOutResult("app", moved_bytes=512 * MIB, refused=2))
        self.assertIn("2 of its processes protect their memory", text)


class ProcessSwapTest(unittest.TestCase):
    def read_with(self, content):
        with mock.patch("builtins.open", mock.mock_open(read_data=content)):
            return _process_swap_mb(1)

    def test_reads_the_swap_line_in_mb(self):
        self.assertEqual(self.read_with("Name:\tapp\nVmSwap:\t    2048 kB\n"), 2.0)

    def test_a_kernel_thread_has_no_swap(self):
        self.assertEqual(self.read_with("Name:\tkthreadd\nState:\tS\n"), 0.0)

    def test_a_broken_line_counts_as_unreadable(self):
        self.assertIsNone(self.read_with("VmSwap:\n"))

    def test_a_process_that_is_gone_counts_as_unreadable(self):
        with mock.patch("builtins.open", side_effect=FileNotFoundError):
            self.assertIsNone(_process_swap_mb(1))

    def test_the_own_process_has_a_swap_value(self):
        worker = ProcessWorker()
        worker._sync_process_table()
        rows = {row.pid: row for row in worker._collect_rows()}
        self.assertIsNotNone(rows[os.getpid()].swap_mb)


if __name__ == "__main__":
    unittest.main()
