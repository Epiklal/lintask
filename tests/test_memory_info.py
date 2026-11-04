"""The memory view: rating, data and the workers behind its actions. No real helper or sudo
is involved.
"""
import glob
import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import psutil  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import memory_info  # noqa: E402
from app.i18n import format_decimal, tr  # noqa: E402
from app.memory_info import (  # noqa: E402
    ERROR_DROP_REFUSED, ERROR_HELPER_FAILED, ERROR_HELPER_OLD, ERROR_HELPER_TIMEOUT,
    ERROR_NOT_SET_UP, ERROR_PAGEOUT_KERNEL, ERROR_PAGEOUT_NO_PYTHON, ERROR_PAGEOUT_REFUSED,
    GIB, MIB, DropCachesWorker, MemoryHardware, MemoryModule, MemoryOverview, MemorySnapshot,
    PageOutResult, PageOutWorker, SwapDevice, format_bytes, is_essential, is_tight,
    memory_data_sections, memory_summary_rows, overview_from_remote, parse_dmi_memory,
    parse_meminfo, parse_pressure, parse_refused, parse_swaps, pressure_level,
    read_memory_hardware,
)
from app.system_info import list_hardware_sensors, list_ram_sensors  # noqa: E402
from pages import memory_page  # noqa: E402
from pages.memory_page import MemoryPage  # noqa: E402


def overview(total=16 * GIB, available=8 * GIB, some=None, swap_total=4 * GIB):
    return MemoryOverview(total=total, used=total - available, available=available,
                          cached=2 * GIB, swap_total=swap_total, swap_used=0, pressure_some=some)


class TestPressure(unittest.TestCase):
    TEXT = ("some avg10=0.50 avg60=1.25 avg300=0.00 total=99\n"
            "full avg10=0.10 avg60=0.75 avg300=0.00 total=12\n")

    def test_reads_the_one_minute_average_of_both_lines(self):
        self.assertEqual(parse_pressure(self.TEXT), (1.25, 0.75))

    def test_broken_or_empty_input_is_unknown(self):
        self.assertEqual(parse_pressure(""), (None, None))
        self.assertEqual(parse_pressure("\nsome avg60=abc\n"), (None, None))

    def test_a_missing_full_line_stays_unknown(self):
        self.assertEqual(parse_pressure("some avg60=2.00\n"), (2.0, None))

    def test_levels(self):
        for some, level in ((None, None), (0.0, "none"), (0.99, "none"), (1.0, "light"),
                            (9.99, "light"), (10.0, "high"), (80.0, "high")):
            with self.subTest(some=some):
                self.assertEqual(pressure_level(overview(some=some)), level)


class TestIsTight(unittest.TestCase):
    def test_much_cache_and_free_memory_is_not_tight(self):
        self.assertFalse(is_tight(overview(available=8 * GIB, some=0.0)))

    def test_little_available_memory_is_tight(self):
        self.assertTrue(is_tight(overview(available=GIB, some=0.0)))

    def test_high_pressure_is_tight_even_with_memory_left(self):
        self.assertTrue(is_tight(overview(available=8 * GIB, some=25.0)))

    def test_light_pressure_alone_is_not_tight(self):
        self.assertFalse(is_tight(overview(available=8 * GIB, some=5.0)))

    def test_unknown_total_is_not_tight(self):
        self.assertFalse(is_tight(overview(total=0, available=0)))


class TestIsEssential(unittest.TestCase):
    def test_desktop_programs(self):
        for name in ("systemd", "gnome-shell", "Xorg", "plasmashell", "gnome-session-binary"):
            with self.subTest(name=name):
                self.assertTrue(is_essential(name))

    def test_cinnamon_session_is_found_under_its_cut_off_name(self):
        self.assertTrue(is_essential("xfce4-session"))
        self.assertTrue(is_essential("cinnamon-session"[:15]))

    def test_ordinary_programs(self):
        for name in ("firefox", "code", "systemd-resolved-but-longer", "python3"):
            with self.subTest(name=name):
                self.assertFalse(is_essential(name))


class TestRemoteData(unittest.TestCase):
    def test_overview(self):
        result = overview_from_remote(
            {"mem_total_gb": 16, "mem_available_gb": 4, "mem_cached_gb": 2})
        self.assertEqual((result.total, result.used, result.available, result.cached),
                         (16 * GIB, 12 * GIB, 4 * GIB, 2 * GIB))
        self.assertIsNone(result.swap_total)
        self.assertIsNone(pressure_level(result))

    def test_missing_fields_do_not_raise(self):
        self.assertEqual(overview_from_remote({}).total, 0)


class TestHelperResults(unittest.TestCase):
    def test_parse_refused(self):
        self.assertEqual(parse_refused("paged=2 refused=3\n"), 3)
        self.assertEqual(parse_refused(""), 0)
        self.assertEqual(parse_refused("refused=x"), 0)

    def run_page_out(self, returncode=0, stdout="", raises=None, helper="/usr/bin/helper"):
        worker = PageOutWorker("app", [(1, 1.0)])
        run = mock.Mock(return_value=subprocess.CompletedProcess([], returncode, stdout, ""),
                        side_effect=raises)
        with mock.patch.object(memory_info, "sudo_helper", return_value=helper), \
                mock.patch.object(memory_info, "_live_processes", return_value=[psutil.Process()]), \
                mock.patch.object(memory_info, "_SETTLE_SECONDS", 0), \
                mock.patch.object(worker, "_run_command", run):
            return worker._page_out(), run

    def test_page_out_errors(self):
        for returncode, error in ((1, ERROR_NOT_SET_UP), (2, ERROR_HELPER_OLD),
                                  (3, ERROR_PAGEOUT_REFUSED), (4, ERROR_PAGEOUT_KERNEL),
                                  (5, ERROR_HELPER_FAILED), (127, ERROR_PAGEOUT_NO_PYTHON)):
            with self.subTest(returncode=returncode):
                self.assertEqual(self.run_page_out(returncode)[0].error, error)

    def test_page_out_without_sudo_or_helper(self):
        self.assertEqual(self.run_page_out(raises=OSError())[0].error, ERROR_NOT_SET_UP)
        self.assertEqual(self.run_page_out(helper=None)[0].error, ERROR_NOT_SET_UP)

    def test_page_out_timeout(self):
        result, _ = self.run_page_out(raises=subprocess.TimeoutExpired("sudo", 1))
        self.assertEqual(result.error, ERROR_HELPER_TIMEOUT)

    def test_page_out_success_reports_refused_processes(self):
        result, run = self.run_page_out(0, "paged=1 refused=2\n")
        self.assertEqual((result.error, result.refused), ("", 2))
        self.assertEqual(run.call_args.args[0],
                         ["sudo", "-n", "/usr/bin/helper", "pageout", str(os.getpid())])

    def test_page_out_counts_only_what_reached_swap(self):
        for swapped, moved in (((10 * MIB, 60 * MIB), 50 * MIB), ((60 * MIB, 10 * MIB), 0)):
            with self.subTest(swapped=swapped), \
                    mock.patch.object(memory_info, "_swapped_bytes", side_effect=swapped):
                self.assertEqual(self.run_page_out(0, "paged=1 refused=0\n")[0].moved_bytes, moved)

    def test_swapped_bytes_of_a_process_that_is_gone_count_as_nothing(self):
        gone = mock.Mock(pid=2 ** 30)
        with mock.patch("builtins.open", mock.mock_open(read_data="Name:\tapp\nVmSwap:\t  2 kB\n")):
            self.assertEqual(memory_info._swapped_bytes([gone, gone]), 4096)
        self.assertEqual(memory_info._swapped_bytes([gone]), 0)

    def test_page_out_of_a_program_that_is_gone_does_nothing(self):
        worker = PageOutWorker("app", [(1, 1.0)])
        run = mock.Mock()
        with mock.patch.object(memory_info, "sudo_helper", return_value="/usr/bin/helper"), \
                mock.patch.object(memory_info, "_live_processes", return_value=[]), \
                mock.patch.object(worker, "_run_command", run):
            self.assertEqual(worker._page_out(), PageOutResult("app"))
        run.assert_not_called()

    def run_drop(self, returncode=0, raises=None, helper="/usr/bin/helper"):
        worker = DropCachesWorker()
        run = mock.Mock(return_value=subprocess.CompletedProcess([], returncode, "", ""),
                        side_effect=raises)
        with mock.patch.object(memory_info, "sudo_helper", return_value=helper), \
                mock.patch.object(worker, "_run_command", run):
            return worker._drop(), run

    def test_drop_errors(self):
        for returncode, error in ((1, ERROR_NOT_SET_UP), (2, ERROR_HELPER_OLD),
                                  (3, ERROR_DROP_REFUSED), (5, ERROR_HELPER_FAILED)):
            with self.subTest(returncode=returncode):
                self.assertEqual(self.run_drop(returncode)[0].error, error)
        self.assertEqual(self.run_drop(raises=OSError())[0].error, ERROR_NOT_SET_UP)
        self.assertEqual(self.run_drop(helper=None)[0].error, ERROR_NOT_SET_UP)

    def test_drop_success_calls_only_the_fixed_command(self):
        result, run = self.run_drop()
        self.assertEqual(result.error, "")
        self.assertEqual(run.call_args.args[0], ["sudo", "-n", "/usr/bin/helper", "drop-caches"])


class TestMemoryFiles(unittest.TestCase):
    def test_meminfo_is_in_bytes_and_plain_counters_stay_as_they_are(self):
        values = parse_meminfo("MemTotal:    16 kB\nHugePages_Total:   3\nbroken\nOdd: abc kB\n")
        self.assertEqual(values, {"MemTotal": 16 * 1024, "HugePages_Total": 3})

    def test_swaps_are_in_bytes_and_keep_spaces_in_the_name(self):
        text = ("Filename\tType\tSize\tUsed\tPriority\n"
                "/my\\040swap file 1024 512 -2\n"
                "/dev/sda3 partition 2048 0 -3\n"
                "broken line\n"
                "/dev/sdb1 partition abc 0 -4\n")
        self.assertEqual(parse_swaps(text), [
            SwapDevice("/my swap", "file", 1024 * 1024, 512 * 1024),
            SwapDevice("/dev/sda3", "partition", 2048 * 1024, 0),
        ])

    def test_empty_files_mean_no_data(self):
        self.assertEqual(parse_meminfo(""), {})
        self.assertEqual(parse_swaps(""), [])


DMI_TEXT = """\
# dmidecode 3.6

Handle 0x0010, DMI type 16, 23 bytes
Physical Memory Array
\tLocation: System Board Or Motherboard
\tUse: System Memory
\tError Correction Type: None
\tMaximum Capacity: 128 GB
\tNumber Of Devices: 2

Handle 0x0020, DMI type 16, 23 bytes
Physical Memory Array
\tUse: Flash Memory
\tError Correction Type: Unknown
\tMaximum Capacity: 16 MB

Handle 0x0011, DMI type 17, 92 bytes
Memory Device
\tArray Handle: 0x0010
\tSize: 16 GB
\tForm Factor: DIMM
\tLocator: DIMM_A1
\tBank Locator: BANK 0
\tType: DDR4
\tType Detail: Synchronous Unbuffered
\tSpeed: 3200 MT/s
\tManufacturer: 00000000
\tSerial Number: SECRET123
\tPart Number: Not Specified
\tRank: 2
\tConfigured Memory Speed: 3000 MT/s
\tConfigured Voltage: 1.35 V
\tMemory Operating Mode Capability:
\t\tVolatile memory

Handle 0x0012, DMI type 17, 92 bytes
Memory Device
\tArray Handle: 0x0010
\tSize: No Module Installed
\tLocator: DIMM_A2
\tType: Unknown

Handle 0x0021, DMI type 17, 92 bytes
Memory Device
\tArray Handle: 0x0020
\tSize: 16 MB
\tLocator: FLASH
"""


class TestDmiMemory(unittest.TestCase):
    def test_reads_the_array_and_its_slots(self):
        hardware = parse_dmi_memory(DMI_TEXT)
        self.assertEqual(hardware.max_capacity, 128 * GIB)
        self.assertEqual(hardware.error_correction, "None")
        # The flash chip has an array of its own and is no memory slot.
        self.assertEqual(hardware.slots_total, 2)
        self.assertEqual([module.locator for module in hardware.modules], ["DIMM_A1"])

    def test_reads_a_module_and_drops_placeholders(self):
        module = parse_dmi_memory(DMI_TEXT).modules[0]
        self.assertEqual(module.size, 16 * GIB)
        self.assertEqual((module.type, module.form_factor), ("DDR4", "DIMM"))
        self.assertEqual((module.speed, module.configured_speed), ("3200 MT/s", "3000 MT/s"))
        self.assertEqual((module.rank, module.voltage), ("2", "1.35 V"))
        self.assertEqual((module.manufacturer, module.part_number), ("", ""))

    def test_the_serial_number_is_not_kept(self):
        self.assertNotIn("SECRET123", repr(parse_dmi_memory(DMI_TEXT)))

    def test_boards_without_array_data_still_have_memory(self):
        text = "Handle 0x1, DMI type 17, 92 bytes\nMemory Device\n\tSize: 8192 MB\n\tLocator: A\n"
        hardware = parse_dmi_memory(text)
        self.assertEqual((hardware.max_capacity, hardware.error_correction), (None, ""))
        self.assertEqual([module.size for module in hardware.modules], [8 * GIB])

    def test_no_readable_data_means_no_hardware(self):
        for text in (None, "", "# dmidecode 3.6\n"):
            with self.subTest(text=text), mock.patch.object(memory_info, "read_dmi_memory",
                                                            return_value=text):
                self.assertIsNone(read_memory_hardware())
        with mock.patch.object(memory_info, "read_dmi_memory", return_value=DMI_TEXT):
            self.assertEqual(read_memory_hardware().slots_total, 2)


class TestRamSensors(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        chips = {"hwmon0": ("jc42", {"temp1_input": "41500"}),
                 "hwmon1": ("SPD5118", {"temp1_input": "39000"}),
                 "hwmon2": ("nct6687", {"temp1_input": "50000", "temp1_label": "CPU"})}
        for folder, (chip, files) in chips.items():
            os.mkdir(os.path.join(directory.name, folder))
            for name, content in {"name": chip, **files}.items():
                with open(os.path.join(directory.name, folder, name), "w") as handle:
                    handle.write(content)
        real_glob = glob.glob
        patcher = mock.patch("glob.glob", side_effect=lambda pattern: real_glob(
            pattern.replace("/sys/class/hwmon", directory.name)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_memory_tab_gets_the_sensors_on_the_modules(self):
        sensors = list_ram_sensors()
        self.assertEqual([sensor["name"] for sensor in sensors],
                         ["jc42: temp1", "SPD5118: temp1"])
        self.assertEqual((sensors[0]["value"], sensors[0]["unit"]), (41.5, "°C"))

    def test_the_sensors_tab_no_longer_gets_them(self):
        names = [sensor["name"] for sensor in list_hardware_sensors()]
        self.assertIn("nct6687: CPU", names)
        self.assertFalse([name for name in names if name.lower().startswith(("jc42", "spd"))])


class TestMemoryData(unittest.TestCase):
    MEMINFO = {"MemFree": GIB, "Buffers": MIB, "Slab": 2 * MIB, "SwapCached": 3 * MIB,
               "HugePages_Total": 4, "HugePages_Free": 1}

    @staticmethod
    def sections(data=None, meminfo=None, swaps=(), hardware=None, sensors=None, remote=False):
        return dict(memory_data_sections(data or overview(), meminfo or {}, list(swaps), hardware,
                                         sensors, remote=remote))

    def test_usage_lists_the_overview_and_the_kernel_counters(self):
        sections = self.sections(meminfo=self.MEMINFO)
        usage = dict(sections[tr("Usage")])
        self.assertEqual(usage[tr("Free")], format_bytes(GIB))
        kernel = dict(sections[tr("Kernel")])
        self.assertEqual(kernel[tr("Kernel caches (slab)")], format_bytes(2 * MIB))
        self.assertEqual(kernel[tr("Huge pages")], tr("{used} of {total}", used=3, total=4))

    def test_without_kernel_counters_the_section_is_left_out(self):
        self.assertNotIn(tr("Kernel"), self.sections())

    def test_summary_shows_pressure_with_the_value_if_known(self):
        rows = dict(memory_summary_rows(overview()))
        self.assertEqual(rows[tr("Memory pressure")], tr("Unknown"))
        rows = dict(memory_summary_rows(overview(some=1.5)))
        self.assertIn(f"({format_decimal(1.5)} %)", rows[tr("Memory pressure")])

    def test_summary_states_of_swap(self):
        for total, text in ((None, tr("Unknown")), (0, tr("Not set up"))):
            with self.subTest(total=total):
                rows = dict(memory_summary_rows(overview(swap_total=total)))
                self.assertEqual(rows[tr("Swap")], text)
        data = MemoryOverview(total=16 * GIB, used=8 * GIB, available=8 * GIB, cached=0,
                              swap_total=4 * GIB, swap_used=GIB)
        self.assertEqual(dict(memory_summary_rows(data))[tr("Swap")],
                         tr("{used} of {total}", used=format_bytes(GIB),
                            total=format_bytes(4 * GIB)))

    def test_the_table_does_not_repeat_the_summary(self):
        summary = {label for label, _value in memory_summary_rows(overview())}
        device = SwapDevice("/swapfile", "file", 4 * GIB, GIB)
        sections = self.sections(meminfo=self.MEMINFO, swaps=[device])
        for section in (tr("Usage"), tr("Swap")):
            with self.subTest(section=section):
                self.assertFalse(summary & set(dict(sections[section])))

    def test_swap_states(self):
        for total in (None, 0):
            with self.subTest(total=total):
                self.assertNotIn(tr("Swap"), self.sections(data=overview(swap_total=total)))
        device = SwapDevice("/swapfile", "file", 4 * GIB, GIB)
        swap = dict(self.sections(meminfo=self.MEMINFO, swaps=[device])[tr("Swap")])
        self.assertEqual(swap[tr("Also still in memory")], format_bytes(3 * MIB))
        self.assertEqual(swap["/swapfile"], tr("{used} of {total}", used=format_bytes(GIB),
                                               total=format_bytes(4 * GIB)))

    def test_hardware_lists_every_module(self):
        hardware = MemoryHardware(
            max_capacity=64 * GIB, error_correction="None", slots_total=4,
            modules=(MemoryModule("DIMM_A1", 16 * GIB, type="DDR4", form_factor="DIMM"),
                     MemoryModule("", 8 * GIB)))
        sections = self.sections(hardware=hardware)
        rows = dict(sections[tr("Hardware")])
        self.assertEqual(rows[tr("Slots in use")], tr("{used} of {total}", used=2, total=4))
        self.assertEqual(rows[tr("Error correction")], tr("None"))
        first = dict(sections[tr("Module {number}: {slot}", number=1, slot="DIMM_A1")])
        self.assertEqual(first[tr("Type")], "DDR4 DIMM")
        # Fields that are not known get no empty row.
        self.assertNotIn(tr("Manufacturer"), first)
        self.assertEqual(sections[tr("Module {number}", number=2)],
                         [(tr("Size"), format_bytes(8 * GIB))])

    def test_without_hardware_the_reason_is_shown(self):
        local = dict(self.sections()[tr("Hardware")])
        self.assertEqual(local[tr("Modules")],
                         tr("Needs \"Set up hardware data with sudo\" under Settings"))
        remote = dict(self.sections(remote=True)[tr("Hardware")])
        self.assertEqual(remote[tr("Modules")], tr("Only shown for this PC"))

    def test_temperature_states(self):
        self.assertEqual(self.sections(sensors=None)[tr("Temperature")],
                         [(tr("Temperature"), tr("Unknown"))])
        self.assertEqual(self.sections(sensors=[])[tr("Temperature")],
                         [(tr("Temperature"), tr("No sensor found"))])
        sensors = [{"unit": "°C", "value": 41.5}, {"unit": "V", "value": 1.2},
                   {"unit": "°C", "value": 40.0}]
        self.assertEqual(self.sections(sensors=sensors)[tr("Temperature")],
                         [(tr("Sensor {number}", number=1), f"{format_decimal(41.5)} °C"),
                          (tr("Sensor {number}", number=2), f"{format_decimal(40.0)} °C")])


class TestMemoryPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.settings = SimpleNamespace(memory_cache_option=False)
        self.page = MemoryPage(self.settings)
        self.addCleanup(self.page.deleteLater)
        self.addCleanup(self.page.shutdown)

    def test_cache_button_is_off_by_default_and_warns_when_switched_on(self):
        self.assertTrue(self.page.drop_btn.isHidden())
        self.assertTrue(self.page.cache_warning.isHidden())
        self.page.cache_check.setChecked(True)
        self.assertFalse(self.page.drop_btn.isHidden())
        self.assertFalse(self.page.cache_warning.isHidden())
        self.assertTrue(self.settings.memory_cache_option)

    def test_emptying_the_cache_asks_first(self):
        with mock.patch.object(QMessageBox, "warning", return_value=QMessageBox.No) as ask, \
                mock.patch.object(self.page, "_start_action") as start:
            self.page._on_drop_clicked()
        ask.assert_called_once()
        start.assert_not_called()

    def test_markup_in_a_status_stays_text(self):
        self.page._show_status("<img src=x>")
        self.assertEqual(self.page.status_label.textFormat(), memory_page.Qt.PlainText)

    def test_remote_mode_shows_server_data_and_locks_everything(self):
        payload = {"system": {"mem_total_gb": 16, "mem_available_gb": 8}, "processes": []}
        self.page.set_remote_data(payload)
        self.assertTrue(self.page.cache_box.isHidden())
        rows = dict(memory_summary_rows(self.page.overview))
        self.assertEqual(rows[tr("Swap")], tr("Unknown"))
        self.assertEqual(rows[tr("In use")], format_bytes(8 * GIB))

        # Local results that are still on their way must not replace the server's numbers.
        self.page._on_snapshot(MemorySnapshot(overview(available=GIB)))
        self.assertEqual(dict(memory_summary_rows(self.page.overview))[tr("In use")],
                         format_bytes(8 * GIB))

        self.page.set_remote_data(None)
        self.assertFalse(self.page.cache_box.isHidden())

    def data_rows(self):
        """The rows of the data table as {label: value}; section titles have the value None."""
        table = self.page.data_table
        rows = {}
        for index in range(table.rowCount()):
            value = table.item(index, 1)
            rows[table.item(index, 0).text()] = value.text() if value else None
        return rows

    def show_snapshot(self, snapshot):
        with mock.patch.object(memory_page, "read_meminfo", return_value={"Buffers": GIB}), \
                mock.patch.object(memory_page, "read_swaps", return_value=[]):
            self.page._on_snapshot(snapshot)

    def test_one_graph_shows_memory_and_swap(self):
        self.assertIs(self.page.memory_chart._secondary, self.page._swap_history)
        self.page._add_to_charts(MemoryOverview(
            total=16 * GIB, used=4 * GIB, available=12 * GIB, cached=0,
            swap_total=4 * GIB, swap_used=GIB))
        self.assertEqual(self.page._memory_history[-1], 25.0)
        self.assertEqual(self.page._swap_history[-1], 25.0)

    def test_the_captions_only_name_the_lines(self):
        self.page._add_to_charts(overview())
        self.assertEqual(self.page.memory_chart_label.text(), tr("RAM (solid line)"))
        self.assertEqual(self.page.swap_label.text(), tr("Swap (dashed line)"))

    def test_without_swap_the_line_stays_at_zero(self):
        for total in (0, None):
            with self.subTest(total=total):
                self.page._add_to_charts(overview(swap_total=total))
                self.assertEqual(self.page._swap_history[-1], 0.0)

    def test_no_total_does_not_divide_by_zero(self):
        self.page._add_to_charts(overview(total=0, available=0))
        self.assertEqual(self.page._memory_history[-1], 0.0)

    def test_the_data_table_is_filled_by_a_snapshot(self):
        self.show_snapshot(MemorySnapshot(overview()))
        rows = self.data_rows()
        self.assertIsNone(rows[tr("Usage")])
        self.assertIsNone(rows[tr("Hardware")])
        self.assertEqual(rows[tr("Buffers")], format_bytes(GIB))
        self.assertEqual(rows[tr("Temperature")], tr("No sensor found"))

    def test_the_data_table_shows_sensors_and_modules_when_they_arrive(self):
        self.show_snapshot(MemorySnapshot(overview(), [{"unit": "°C", "value": 41.5}]))
        self.assertEqual(self.data_rows()[tr("Sensor {number}", number=1)],
                         f"{format_decimal(41.5)} °C")
        with mock.patch.object(memory_page, "read_meminfo", return_value={}), \
                mock.patch.object(memory_page, "read_swaps", return_value=[]):
            self.page._on_hardware(MemoryHardware(slots_total=2, modules=(
                MemoryModule("DIMM_A1", 16 * GIB),)))
        rows = self.data_rows()
        self.assertEqual(rows[tr("Slots in use")], tr("{used} of {total}", used=1, total=2))
        self.assertIn(tr("Module {number}: {slot}", number=1, slot="DIMM_A1"), rows)

    def test_a_new_value_keeps_the_rows_and_with_them_the_scroll_position(self):
        self.show_snapshot(MemorySnapshot(overview()))
        table = self.page.data_table
        item = table.item(1, 1)
        self.show_snapshot(MemorySnapshot(overview(available=4 * GIB)))
        self.assertIs(table.item(1, 1), item)

    def test_the_remote_data_table_only_shows_what_the_server_sent(self):
        payload = {"system": {"mem_total_gb": 16, "mem_available_gb": 8}, "processes": [],
                   "ram_sensors": [{"unit": "°C", "value": 30.0}]}
        self.page.set_remote_data(payload)
        rows = self.data_rows()
        self.assertEqual(rows[tr("Modules")], tr("Only shown for this PC"))
        self.assertEqual(rows[tr("Sensor {number}", number=1)], f"{format_decimal(30.0)} °C")

        # A server from before this field knows nothing about its sensors, which is not "none".
        del payload["ram_sensors"]
        self.page.set_remote_data(payload)
        self.assertEqual(self.data_rows()[tr("Temperature")], tr("Unknown"))

    def test_switching_to_a_server_starts_the_graphs_anew(self):
        self.page._add_to_charts(overview())
        self.page.set_remote_data({"system": {"mem_total_gb": 16, "mem_available_gb": 12},
                                   "processes": []})
        self.assertEqual(list(self.page._memory_history)[:-1], [0.0] * 59)
        self.assertEqual(self.page._memory_history[-1], 25.0)
        # The timer reads this PC, so it must not draw into the server's graph.
        self.page._on_chart_timer()
        self.assertEqual(list(self.page._memory_history)[-2:], [0.0, 25.0])


if __name__ == "__main__":
    unittest.main()
