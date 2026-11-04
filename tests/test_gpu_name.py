"""The GPU model name: AMD cards by device ID and revision, everything else through lspci."""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import system_info  # noqa: E402
from app.system_info import (  # noqa: E402
    GpuSystemMonitor,
    _amdgpu_product_name,
    _lspci_gpu_name,
    _lookup_amdgpu_id,
)

BUNDLED_IDS = system_info._AMDGPU_IDS_FILES[-1]


def make_card(root, vendor="0x1002", device="0x7590", revision="0xc0",
              subsystem=("0x1458", "0x2429")):
    for name, value in (("vendor", vendor), ("device", device), ("revision", revision),
                        ("subsystem_vendor", subsystem[0]), ("subsystem_device", subsystem[1]),
                        ("uevent", "DRIVER=amdgpu\nPCI_SLOT_NAME=0000:18:00.0\n")):
        with open(os.path.join(root, name), "w") as f:
            f.write(value + "\n")
    return root


class TestAmdgpuIds(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name

    def write_ids(self, text):
        path = os.path.join(self.root, "amdgpu.ids")
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_the_revision_tells_the_cards_with_device_id_7590_apart(self):
        for revision, name in ((0xC0, "AMD Radeon RX 9060 XT"), (0xC7, "AMD Radeon RX 9060"),
                               (0xCF, "AMD Radeon RX 9050")):
            with self.subTest(revision=revision):
                self.assertEqual(_lookup_amdgpu_id(BUNDLED_IDS, 0x7590, revision, (None, None)),
                                 name)

    def test_an_unknown_revision_is_not_guessed(self):
        self.assertIsNone(_lookup_amdgpu_id(BUNDLED_IDS, 0x7590, 0x01, (None, None)))

    def test_a_board_line_overrides_only_its_own_entry(self):
        path = self.write_ids("# comment\n\n1.0.0\n"
                              "7590,\tC0,\tAMD Radeon RX 9060 XT\n"
                              "\t1458,\t2429,\tBoard Name\n"
                              "7590,\tC7,\tAMD Radeon RX 9060\n")
        self.assertEqual(_lookup_amdgpu_id(path, 0x7590, 0xC0, (0x1458, 0x2429)), "Board Name")
        self.assertEqual(_lookup_amdgpu_id(path, 0x7590, 0xC0, (0x1043, 0x0639)),
                         "AMD Radeon RX 9060 XT")
        self.assertEqual(_lookup_amdgpu_id(path, 0x7590, 0xC7, (0x1458, 0x2429)),
                         "AMD Radeon RX 9060")

    def test_a_missing_or_broken_file_is_no_error(self):
        self.assertIsNone(_lookup_amdgpu_id(os.path.join(self.root, "none"), 1, 2, (None, None)))
        path = os.path.join(self.root, "binary")
        with open(path, "wb") as f:
            f.write(b"\xff\xfe\x00")
        self.assertIsNone(_lookup_amdgpu_id(path, 1, 2, (None, None)))

    def test_an_old_system_list_falls_back_to_the_bundled_one(self):
        old = self.write_ids("1.0.0\n744C,\tC8,\tAMD Radeon RX 7900 XTX\n")
        with mock.patch.object(system_info, "_AMDGPU_IDS_FILES", (old, BUNDLED_IDS)):
            self.assertEqual(_amdgpu_product_name(make_card(self.root)), "AMD Radeon RX 9060 XT")

    def test_the_system_list_wins_when_it_knows_the_card(self):
        system = self.write_ids("7590,\tC0,\tName From System\n")
        with mock.patch.object(system_info, "_AMDGPU_IDS_FILES", (system, BUNDLED_IDS)):
            self.assertEqual(_amdgpu_product_name(make_card(self.root)), "Name From System")

    def test_other_vendors_are_not_looked_up(self):
        self.assertIsNone(_amdgpu_product_name(make_card(self.root, vendor="0x10de")))

    def test_the_monitor_shows_the_exact_name_even_if_lspci_does_not_know_the_card(self):
        monitor = GpuSystemMonitor.__new__(GpuSystemMonitor)
        monitor._card_path = make_card(self.root)
        with mock.patch.object(system_info, "_AMDGPU_IDS_FILES", (BUNDLED_IDS,)), \
                mock.patch.object(system_info.subprocess, "check_output",
                                  return_value='18:00.0 "VGA" "Advanced Micro Devices, Inc. '
                                               '[AMD/ATI]" "Device 7590" "" ""\n'):
            info = monitor._sysfs_static_info()
        self.assertEqual(info["name"], "AMD Radeon RX 9060 XT")

    def test_an_unlisted_card_still_gets_the_lspci_name(self):
        monitor = GpuSystemMonitor.__new__(GpuSystemMonitor)
        monitor._card_path = make_card(self.root, revision="0x01")
        with mock.patch.object(system_info, "_AMDGPU_IDS_FILES", (BUNDLED_IDS,)), \
                mock.patch.object(system_info.subprocess, "check_output",
                                  return_value='18:00.0 "VGA" "Advanced Micro Devices, Inc. '
                                               '[AMD/ATI]" "Device 7590" "" ""\n'):
            info = monitor._sysfs_static_info()
        self.assertEqual(info["name"], "AMD Device 7590")


class TestLspciName(unittest.TestCase):
    def name_for(self, device, subsystem="Device 1234"):
        output = (f'18:00.0 "VGA compatible controller" "Advanced Micro Devices, Inc. [AMD/ATI]" '
                  f'"{device}" -rc0 "Some Vendor" "{subsystem}"\n')
        with mock.patch.object(system_info.subprocess, "check_output", return_value=output):
            return _lspci_gpu_name("18:00.0")

    def test_the_subsystem_picks_the_variant(self):
        family = "Navi 31 [Radeon RX 7900 XT/7900 XTX/7900 GRE/7900M]"
        self.assertEqual(self.name_for(family, "RX 7900 XTX Gaming"), "AMD Radeon RX 7900 XTX")

    def test_spaces_around_the_slash_do_not_break_the_name(self):
        family = "Navi 44 [Radeon RX 9050 / 9060 XT]"
        self.assertEqual(self.name_for(family, "RX 9060 XT Gaming OC"), "AMD Radeon RX 9060 XT")


if __name__ == "__main__":
    unittest.main()
