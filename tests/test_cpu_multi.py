"""Two (or more) CPUs in one board: the hottest one is shown, each is listed as CPU 1, CPU 2."""
import os
import tempfile
import unittest
from collections import namedtuple
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import system_info  # noqa: E402
from app.system_info import (  # noqa: E402
    CpuPowerMonitor, _rapl_counters, get_cpu_socket_count, get_cpu_temperature,
    get_cpu_temperatures,
)
from app.i18n import tr  # noqa: E402
from pages.performance_page import (  # noqa: E402
    StatsPanel, _core_grid_columns, _cpu_socket_lines,
)

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

    def test_core_grid_columns(self):
        # Full rectangles like Windows: threads -> columns x rows.
        for threads, columns in ((1, 1), (2, 2), (4, 2), (6, 3), (8, 4), (12, 4),
                                 (16, 4), (24, 6), (32, 8), (64, 8), (256, 16)):
            with self.subTest(threads=threads):
                self.assertEqual(_core_grid_columns(threads), columns)
                self.assertEqual(threads % columns, 0)


if __name__ == "__main__":
    unittest.main()
