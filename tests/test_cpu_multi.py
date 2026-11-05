"""Two (or more) CPUs in one board: the hottest one is shown, each is listed as CPU 1, CPU 2."""
import io
import os
import tempfile
import unittest
from collections import namedtuple
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import system_info  # noqa: E402
from app.system_info import (  # noqa: E402
    CcdPowerMonitor, CpuPowerMonitor, _is_amd_cpu, energy_watts, parse_energy_sample, _rapl_counters, get_ccd_cpu_groups, get_ccd_temperatures,
    get_cpu_socket_count, get_cpu_temperature, get_cpu_temperatures, get_l3_cpu_groups,
)
from app.i18n import tr  # noqa: E402
from pages.performance_page import (  # noqa: E402
    StatsPanel, _ccd_grid_columns, _ccd_lines, _ccd_loads, _core_grid_columns, _cpu_socket_lines,
)
from tests.test_gpu_multi import FakeMonitor  # noqa: E402

Temp = namedtuple("Temp", "label current high critical")


def sensors(**chips):
    return mock.patch.object(system_info.psutil, "sensors_temperatures",
                             return_value={name: [Temp(label, value, None, None)
                                                  for label, value in entries]
                                           for name, entries in chips.items()})


def write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f"{value}\n")


class TestCpuTemperatures(unittest.TestCase):
    def test_two_intel_sockets(self):
        with sensors(coretemp=[("Package id 1", 74.0), ("Core 0", 70.0),
                               ("Package id 0", 61.0), ("Core 0", 58.0)]):
            self.assertEqual(get_cpu_temperatures(), [61.0, 74.0])
            self.assertEqual(get_cpu_temperature(), 74.0)

    def test_two_amd_sockets(self):
        with sensors(k10temp=[("Tctl", 55.0), ("Tccd1", 50.0),
                              ("Tctl", 68.0), ("Tccd1", 63.0)]):
            self.assertEqual(get_cpu_temperatures(), [55.0, 68.0])
            self.assertEqual(get_cpu_temperature(), 68.0)

    def test_zen1_prefers_tdie_over_tctl(self):
        with sensors(k10temp=[("Tctl", 72.0), ("Tdie", 52.0),
                              ("Tctl", 75.0), ("Tdie", 55.0)]):
            self.assertEqual(get_cpu_temperatures(), [52.0, 55.0])

    def test_single_cpu_and_unlabelled_sensor(self):
        with sensors(coretemp=[("Package id 0", 45.0), ("Core 0", 40.0)]):
            self.assertEqual(get_cpu_temperatures(), [45.0])
        with sensors(cpu_thermal=[("", 50.0)]):
            self.assertEqual(get_cpu_temperatures(), [50.0])

    def test_no_sensor(self):
        with sensors():
            self.assertEqual(get_cpu_temperatures(), [])
            self.assertIsNone(get_cpu_temperature())

    def test_fallback_never_takes_the_ssd(self):
        # k10temp missing: the NVMe "Composite" sensor is not the CPU.
        with sensors(nvme=[("Composite", 45.0)], amdgpu=[("edge", 50.0)]):
            self.assertEqual(get_cpu_temperatures(), [])

    def test_fallback_to_the_board_chip(self):
        with sensors(nvme=[("Composite", 45.0)],
                     nct6799=[("SYSTIN", 30.0), ("CPUTIN", 41.0), ("AMD TSI Addr 98h", 52.0)]):
            self.assertEqual(get_cpu_temperatures(), [52.0])
        with sensors(nct6775=[("SYSTIN", 30.0), ("CPUTIN", 41.0)]):
            self.assertEqual(get_cpu_temperatures(), [41.0])


class TestCcds(unittest.TestCase):
    def setUp(self):
        get_l3_cpu_groups.cache_clear()
        self.addCleanup(get_l3_cpu_groups.cache_clear)

    def make_hwmon(self, base, index, name, labels):
        write(f"{base}/hwmon{index}/name", name)
        for number, (label, millidegrees) in labels.items():
            write(f"{base}/hwmon{index}/temp{number}_label", label)
            write(f"{base}/hwmon{index}/temp{number}_input", millidegrees)

    def test_ccd_temperatures_in_number_order(self):
        with tempfile.TemporaryDirectory() as base:
            self.make_hwmon(base, 0, "nvme", {1: ("Composite", 45000)})
            # Tccd8 is temp10, which a string sort would put before temp3.
            self.make_hwmon(base, 2, "k10temp", {1: ("Tctl", 70000)} | {
                ccd + 2: (f"Tccd{ccd}", ccd * 1000) for ccd in range(1, 9)})
            self.assertEqual(get_ccd_temperatures(base), [float(ccd) for ccd in range(1, 9)])

    def test_no_ccds_on_intel(self):
        with tempfile.TemporaryDirectory() as base:
            self.make_hwmon(base, 0, "coretemp", {1: ("Package id 0", 45000)})
            self.assertEqual(get_ccd_temperatures(base), [])

    def make_l3(self, base, groups):
        for group in groups:
            for cpu in _expand(group):
                write(f"{base}/cpu{cpu}/cache/index3/level", 3)
                write(f"{base}/cpu{cpu}/cache/index3/shared_cpu_list", group)
                write(f"{base}/cpu{cpu}/cache/index2/level", 2)
                write(f"{base}/cpu{cpu}/cache/index2/shared_cpu_list", cpu)

    def test_zen3_one_l3_per_ccd(self):
        with tempfile.TemporaryDirectory() as base:
            self.make_l3(base, ["8-15,24-31", "0-7,16-23"])
            groups = get_l3_cpu_groups(base)
        self.assertEqual(get_ccd_cpu_groups(2, groups),
                         [[*range(0, 8), *range(16, 24)], [*range(8, 16), *range(24, 32)]])

    def test_zen2_two_l3_per_ccd(self):
        # Ryzen 9 3950X: four CCX (one L3 each) on two CCDs.
        with tempfile.TemporaryDirectory() as base:
            self.make_l3(base, ["0-3,16-19", "4-7,20-23", "8-11,24-27", "12-15,28-31"])
            groups = get_l3_cpu_groups(base)
        self.assertEqual(get_ccd_cpu_groups(2, groups),
                         [[*range(0, 8), *range(16, 24)], [*range(8, 16), *range(24, 32)]])

    def test_l3_count_that_does_not_fit(self):
        self.assertEqual(get_ccd_cpu_groups(2, ((0, 1), (2, 3), (4, 5))), [])
        self.assertEqual(get_ccd_cpu_groups(0, ((0, 1),)), [])


def _expand(cpu_list):
    cpus = []
    for part in cpu_list.split(","):
        first, _, last = part.partition("-")
        cpus.extend(range(int(first), int(last or first) + 1))
    return cpus


class TestCcdPower(unittest.TestCase):
    def test_parse_sample(self):
        self.assertEqual(parse_energy_sample("1000 16 0:5 16:5 1:7\n"),
                         (1000, 16, {0: 5, 16: 5, 1: 7}))
        for line in ("", "1000 16", "x 16 0:5", "1000 16 0:x", "1000 16 05"):
            self.assertIsNone(parse_energy_sample(line), line)

    def test_watts(self):
        # 2**16 counts are one joule; 3 J in half a second are 6 W.
        before = (1_000_000_000, 16, {0: 0, 1: 0xFFFFFFFF})
        after = (1_500_000_000, 16, {0: 3 << 16, 1: (3 << 16) - 1, 2: 9})
        self.assertEqual(energy_watts(before, after), {0: 6.0, 1: 6.0})

    def test_no_watts_without_time_or_with_another_unit(self):
        sample = (1000, 16, {0: 5})
        self.assertEqual(energy_watts(sample, sample), {})
        self.assertEqual(energy_watts(sample, (2000, 14, {0: 9})), {})

    def make_monitor(self, base, siblings):
        for cpu, cpu_list in siblings.items():
            write(f"{base}/cpu{cpu}/topology/thread_siblings_list", cpu_list)
        monitor = CcdPowerMonitor(base)
        monitor._amd = False  # never starts the helper
        return monitor

    def test_ccd_watts_count_each_core_once(self):
        with tempfile.TemporaryDirectory() as base:
            monitor = self.make_monitor(base, {0: "0,2", 1: "1,3", 2: "0,2", 3: "1,3"})
            monitor._watts = {0: 4.0, 1: 6.0, 2: 4.0, 3: 6.0}
            self.assertEqual(monitor.ccd_watts([[0, 2], [1, 3]]), [4.0, 6.0])
            monitor._watts = {0: 4.0}
            self.assertEqual(monitor.ccd_watts([[0, 2], [1, 3]]), [4.0, None])

    def test_nothing_without_the_setup(self):
        with tempfile.TemporaryDirectory() as base:
            monitor = CcdPowerMonitor(base)
            monitor._amd = True
            with mock.patch.object(system_info, "sudo_helper", return_value=None), \
                    mock.patch.object(system_info.subprocess, "Popen") as popen:
                self.assertEqual(monitor.ccd_watts([[0], [1]]), [])
            popen.assert_not_called()

    def test_failed_helper_is_not_started_again(self):
        with tempfile.TemporaryDirectory() as base:
            helper = os.path.join(base, "helper")
            write(helper, "")
            monitor = CcdPowerMonitor(base)
            monitor._amd = True
            process = mock.Mock(stdout=io.StringIO(""))
            process.poll.return_value = 2
            with mock.patch.object(system_info, "sudo_helper", return_value=helper), \
                    mock.patch.object(system_info.subprocess, "Popen",
                                      return_value=process) as popen:
                monitor.ccd_watts([[0], [1]])
                monitor._next_check = 0.0
                monitor.ccd_watts([[0], [1]])
                self.assertEqual(popen.call_count, 1)
                self.assertEqual(popen.call_args.args[0], ["sudo", "-n", helper, "cpu-energy"])
                # The setup installed a new helper: that one gets its chance.
                os.utime(helper, ns=(1, 1))
                monitor._next_check = 0.0
                monitor.ccd_watts([[0], [1]])
                self.assertEqual(popen.call_count, 2)

    def test_stream_sets_and_clears_the_watts(self):
        monitor = CcdPowerMonitor()
        seen = []
        real_lock = monitor._lock

        class Recorder:
            def __enter__(self):
                real_lock.acquire()

            def __exit__(self, *exc):
                seen.append(dict(monitor._watts))
                real_lock.release()

        monitor._lock = Recorder()
        stream = io.StringIO("1000000000 16 0:0\ngarbage\n2000000000 16 0:131072\n")
        monitor._read_stream(mock.Mock(stdout=stream))
        self.assertEqual(seen, [{0: 2.0}, {}])
        self.assertTrue(stream.closed)


class TestSocketCount(unittest.TestCase):
    def setUp(self):
        get_cpu_socket_count.cache_clear()
        self.addCleanup(get_cpu_socket_count.cache_clear)

    def test_counts_distinct_packages(self):
        with tempfile.TemporaryDirectory() as base:
            for cpu in range(8):
                write(f"{base}/cpu{cpu}/topology/physical_package_id", cpu // 4)
            self.assertEqual(get_cpu_socket_count(base), 2)

    def test_defaults_to_one(self):
        with tempfile.TemporaryDirectory() as base:
            self.assertEqual(get_cpu_socket_count(base), 1)


class TestPerSocketPower(unittest.TestCase):
    def make_zone(self, base, index, energy):
        zone = f"{base}/intel-rapl:{index}"
        write(f"{zone}/name", f"package-{index}")
        write(f"{zone}/energy_uj", energy)
        write(f"{zone}/max_energy_range_uj", 262143328850)
        # A sub-zone that must not be counted as a socket.
        write(f"{zone}:0/name", "core")
        write(f"{zone}:0/energy_uj", 1)

    def test_zones_in_socket_order_beyond_ten(self):
        with tempfile.TemporaryDirectory() as base:
            for index in range(12):
                self.make_zone(base, index, 0)
            paths = [counter.path for counter in _rapl_counters("package", base)]
        self.assertEqual(paths, [f"{base}/intel-rapl:{i}/energy_uj" for i in range(12)])

    def test_watts_per_socket_and_sum(self):
        with tempfile.TemporaryDirectory() as base:
            self.make_zone(base, 0, 0)
            self.make_zone(base, 1, 0)
            with mock.patch.object(system_info, "_POWERCAP_BASE", base), \
                    mock.patch.object(system_info, "_rapl_counters",
                                      lambda kind: _rapl_counters(kind, base)):
                monitor = CpuPowerMonitor()
            now = [100.0]
            with mock.patch.object(system_info.time, "monotonic", lambda: now[0]):
                self.assertIsNone(monitor.poll_watts())
                now[0] = 101.0
                write(f"{base}/intel-rapl:0/energy_uj", 80_000_000)
                write(f"{base}/intel-rapl:1/energy_uj", 95_500_000)
                total = monitor.poll_watts()
        self.assertEqual(monitor.cpu_watts, [80.0, 95.5])
        self.assertAlmostEqual(total, 175.5)

    def test_cores_power_on_intel(self):
        with tempfile.TemporaryDirectory() as base:
            self.make_zone(base, 0, 0)
            with mock.patch.object(system_info, "_rapl_counters",
                                   lambda kind: _rapl_counters(kind, base)), \
                    mock.patch.object(system_info, "_is_amd_cpu", lambda: False):
                monitor = CpuPowerMonitor()
            now = [100.0]
            with mock.patch.object(system_info.time, "monotonic", lambda: now[0]):
                monitor.poll_watts()
                self.assertIsNone(monitor.cores_watts)
                now[0] = 102.0
                write(f"{base}/intel-rapl:0:0/energy_uj", 60_000_001)
                monitor.poll_watts()
        self.assertAlmostEqual(monitor.cores_watts, 30.0)

    def test_no_cores_power_on_amd(self):
        # AMD's core zone is one core's energy register, not all cores.
        with tempfile.TemporaryDirectory() as base:
            self.make_zone(base, 0, 0)
            with mock.patch.object(system_info, "_rapl_counters",
                                   lambda kind: _rapl_counters(kind, base)), \
                    mock.patch.object(system_info, "_is_amd_cpu", lambda: True):
                monitor = CpuPowerMonitor()
            monitor.poll_watts()
            monitor.poll_watts()
        self.assertIsNone(monitor.cores_watts)

    def test_amd_vendor(self):
        with tempfile.TemporaryDirectory() as base:
            write(f"{base}/cpuinfo", "processor\t: 0\nvendor_id\t: AuthenticAMD")
            self.assertTrue(_is_amd_cpu(f"{base}/cpuinfo"))
            write(f"{base}/cpuinfo", "processor\t: 0\nvendor_id\t: GenuineIntel")
            self.assertFalse(_is_amd_cpu(f"{base}/cpuinfo"))


class TestCpuDisplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_one_cpu_gets_no_extra_rows(self):
        self.assertEqual(_cpu_socket_lines([50.0], [60.0]), "")
        self.assertEqual(_cpu_socket_lines([], []), "")

    def test_rows_per_cpu(self):
        cpu1, cpu2 = (tr("CPU {number}", number=n) for n in (1, 2))
        self.assertEqual(_cpu_socket_lines([61.0, 74.4], [85.3, None]),
                         f"{cpu1}: 61 °C · 85.3 W<br>{cpu2}: 74 °C<br>")
        self.assertEqual(_cpu_socket_lines([], [10.0, 20.0]),
                         f"{cpu1}: 10.0 W<br>{cpu2}: 20.0 W<br>")
        self.assertEqual(_cpu_socket_lines([50.0, None], []),
                         f"{cpu1}: 50 °C<br>{cpu2}: {tr('Not available')}<br>")

    def test_cpu_rows_and_sockets_go_to_the_side_list(self):
        panel = StatsPanel()
        usage, hottest, processes = tr("Utilization"), tr("Highest temperature"), tr("Processes")
        panel.set_text(f"Model<br>{usage}: 5%<br>{hottest}: 74°C<br>{tr('Sockets')}: 2<br>"
                       + _cpu_socket_lines([61.0, 74.0], [85.3, 92.1])
                       + f"{processes}: 300")
        keys, is_big, _notes = panel._signature
        big = [key for key, flag in zip(keys, is_big) if flag]
        self.assertEqual(big, [usage, hottest, processes])
        self.assertIn(tr("CPU {number}", number=2), keys)

    def test_ccd_rows(self):
        ccd1, ccd2 = (tr("CCD {number}", number=n) for n in (1, 2))
        per_core = [20.0, 40.0, 0.0, 10.0]
        freqs = [4700.0, 4500.0, 2200.0, 2200.0]
        self.assertEqual(_ccd_lines([48.2, 39.0], [[0, 1], [2, 3]], per_core, freqs),
                         f"{ccd1}: 48 °C · 30% · 4.60 GHz<br>{ccd2}: 39 °C · 5% · 2.20 GHz<br>")
        # CPUs not matched to the CCDs: temperature only.
        self.assertEqual(_ccd_lines([48.0, 39.0], [], per_core, freqs),
                         f"{ccd1}: 48 °C<br>{ccd2}: 39 °C<br>")

    def test_ccd_rows_with_watts(self):
        ccd1, ccd2 = (tr("CCD {number}", number=n) for n in (1, 2))
        self.assertEqual(_ccd_lines([48.0, 39.0], [[0], [1]], [20.0, 10.0], [], [21.34, None]),
                         f"{ccd1}: 48 °C · 20% · 21.3 W<br>{ccd2}: 39 °C · 10%<br>")
        # Watts that don't match the CCDs are left out.
        self.assertEqual(_ccd_lines([48.0, 39.0], [[0], [1]], [20.0, 10.0], [], [5.0]),
                         f"{ccd1}: 48 °C · 20%<br>{ccd2}: 39 °C · 10%<br>")

    def test_one_ccd_gets_no_rows(self):
        self.assertEqual(_ccd_lines([48.0], [[0, 1]], [1.0, 2.0], []), "")
        self.assertEqual(_ccd_lines([], [], [], []), "")

    def test_ccd_rows_go_to_the_side_list(self):
        panel = StatsPanel()
        usage = tr("Utilization")
        panel.set_text(f"Model<br>{usage}: 5%<br>{tr('Cores power draw')}: 30.0 W<br>"
                       + _ccd_lines([48.0, 39.0], [[0], [1]], [5.0, 5.0], [4700.0, 2200.0]))
        keys, is_big, _notes = panel._signature
        self.assertEqual([key for key, flag in zip(keys, is_big) if flag], [usage])
        self.assertIn(tr("CCD {number}", number=2), keys)

    def test_core_grid_columns(self):
        # Full rectangles like Windows: threads -> columns x rows.
        for threads, columns in ((1, 1), (2, 2), (4, 2), (6, 3), (8, 4), (12, 4),
                                 (16, 4), (24, 6), (32, 8), (64, 8), (256, 16)):
            with self.subTest(threads=threads):
                self.assertEqual(_core_grid_columns(threads), columns)
                self.assertEqual(threads % columns, 0)

    def test_ccd_loads_are_the_mean_of_their_threads(self):
        per_core = [10.0, 30.0, 100.0, 100.0, 50.0]
        self.assertEqual(_ccd_loads([[0, 1], [2, 3]], per_core), [20.0, 100.0])
        # CPUs the snapshot does not know count as idle, never above 100 %.
        self.assertEqual(_ccd_loads([[7, 8]], per_core), [0.0])
        self.assertEqual(_ccd_loads([[0]], [140.0]), [100.0])

    def test_ccd_grid_columns(self):
        for count, columns in ((2, 1), (4, 2), (8, 2), (12, 4), (16, 4)):
            with self.subTest(count=count):
                self.assertEqual(_ccd_grid_columns(count), columns)


class TestCcdGraphs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_page(self, ccd_cpus):
        from pages import performance_page

        real = performance_page.system_snapshot()
        snap = {**real, "cpu_per_core": [10.0, 30.0, 90.0, 70.0], "ccd_cpus": ccd_cpus}
        patcher = mock.patch.object(performance_page, "system_snapshot", return_value=snap)
        patcher.start()
        self.addCleanup(patcher.stop)
        with mock.patch.object(system_info, "list_gpus", return_value=[]), \
                mock.patch.object(system_info, "GpuSystemMonitor", FakeMonitor):
            page = performance_page.PerformancePage()
        page.shutdown()
        self.addCleanup(page.deleteLater)
        return page

    def menu_labels(self, page):
        from PySide6.QtWidgets import QMenu

        menu = QMenu()
        page._add_cpu_graph_menu(menu)
        return [action.text() for action in menu.actions()[0].menu().actions()]

    def test_one_graph_per_ccd(self):
        page = self.make_page([[0, 1], [2, 3]])
        self.assertEqual(len(page._ccd_charts), 2)
        self.assertEqual(page._ccd_histories[0][-1], 20.0)
        self.assertEqual(page._ccd_histories[1][-1], 80.0)
        self.assertIn(tr("CCDs"), self.menu_labels(page))

        page._set_cpu_graph("ccds", save=False)
        self.assertIs(page.chart_stack.currentWidget(), page.ccds_widget)
        self.assertTrue(page.core_toggle_btn.isChecked())
        page.core_toggle_btn.setChecked(False)
        self.assertIs(page.chart_stack.currentWidget(), page.detail_chart)

    def test_single_ccd_has_no_ccd_graphs(self):
        page = self.make_page([[0, 1, 2, 3]])
        self.assertEqual(page._ccd_charts, [])
        self.assertNotIn(tr("CCDs"), self.menu_labels(page))
        # A saved "CCDs" choice falls back to the logical processors.
        page._set_cpu_graph("ccds", save=False)
        self.assertIs(page.chart_stack.currentWidget(), page.cores_widget)


if __name__ == "__main__":
    unittest.main()
