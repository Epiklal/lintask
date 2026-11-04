"""Several GPUs at once, e.g. an NVIDIA and an AMD card: every one is listed and shown."""
import builtins
import ctypes
import os
import struct
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import system_info  # noqa: E402
from app.system_info import (  # noqa: E402
    GpuMonitor, GpuSystemMonitor, GpuSystemWorker, _drm_vram_total, _parse_drm_fdinfo,
    _sum_device_memory_regions, list_gpus, poll_gpus,
)


def make_card(drm, name, driver, slot, vendor="0x1002", boot_vga="0", vram=False):
    device = os.path.join(drm, name, "device")
    os.makedirs(device)
    files = {"uevent": f"DRIVER={driver}\nPCI_SLOT_NAME={slot}\n",
             "vendor": vendor, "boot_vga": boot_vga}
    if vram:
        files["mem_info_vram_total"] = "8589934592"
        files["gpu_busy_percent"] = "0"
    for file_name, value in files.items():
        with open(os.path.join(device, file_name), "w") as f:
            f.write(value + "\n")
    return device


def fake_proc(fdinfo, dirs):
    """Patch open/listdir so /proc shows the given fdinfo files."""
    real_open = builtins.open
    real_listdir = os.listdir

    def fake_open(path, *args, **kwargs):
        if path in fdinfo:
            return mock.mock_open(read_data=fdinfo[path])()
        return real_open(path, *args, **kwargs)

    def fake_listdir(path):
        if path in dirs:
            return dirs[path]
        if not str(path).startswith("/proc"):
            return real_listdir(path)
        raise FileNotFoundError(path)

    return (mock.patch.object(system_info.os, "listdir", fake_listdir),
            mock.patch("builtins.open", fake_open))


def nvidia_smi(output):
    """Patch nvidia-smi so it reports `output` for the index/bus id query."""
    return mock.patch.multiple(
        system_info, _NVIDIA_SMI="/usr/bin/nvidia-smi",
    ), mock.patch.object(system_info.subprocess, "check_output", return_value=output)


class TestListGpus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.drm = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_nvidia_and_amd_are_both_listed(self):
        make_card(self.drm, "card0", "nvidia", "0000:01:00.0", vendor="0x10de", boot_vga="1")
        amd = make_card(self.drm, "card1", "amdgpu", "0000:0b:00.0", vram=True)
        patch_smi, patch_output = nvidia_smi("0, 00000000:01:00.0\n")
        with patch_smi, patch_output:
            gpus = list_gpus(self.drm)

        self.assertEqual([gpu["backend"] for gpu in gpus], ["nvidia", "sysfs"])
        self.assertEqual(gpus[0]["index"], 0)
        self.assertEqual(gpus[0]["pci_slot"], "0000:01:00.0")
        # The NVIDIA card's own DRM node is not listed a second time.
        self.assertEqual(gpus[1]["card_path"], amd)

    def test_two_nvidia_cards_are_both_listed(self):
        patch_smi, patch_output = nvidia_smi("0, 00000000:01:00.0\n1, 00000000:02:00.0\n")
        with patch_smi, patch_output:
            gpus = list_gpus(self.drm)
        self.assertEqual([(gpu["index"], gpu["pci_slot"]) for gpu in gpus],
                         [(0, "0000:01:00.0"), (1, "0000:02:00.0")])

    def test_two_nvidia_one_amd_and_intel_igpu(self):
        make_card(self.drm, "card0", "nvidia", "0000:01:00.0", vendor="0x10de")
        make_card(self.drm, "card1", "nvidia", "0000:02:00.0", vendor="0x10de")
        amd = make_card(self.drm, "card2", "amdgpu", "0000:0b:00.0", vram=True)
        intel = make_card(self.drm, "card3", "i915", "0000:00:02.0", vendor="0x8086",
                          boot_vga="1")
        patch_smi, patch_output = nvidia_smi("0, 00000000:01:00.0\n1, 00000000:02:00.0\n")
        with patch_smi, patch_output:
            gpus = list_gpus(self.drm)

        self.assertEqual([(gpu["backend"], gpu["index"] if gpu["backend"] == "nvidia"
                           else gpu["card_path"]) for gpu in gpus],
                         [("nvidia", 0), ("nvidia", 1), ("sysfs", amd), ("sysfs", intel)])
        # With two sysfs cards, clients must name their device to be counted.
        self.assertFalse(any(gpu["only_drm_card"] for gpu in gpus[2:]))

    def test_two_amd_cards(self):
        first = make_card(self.drm, "card0", "amdgpu", "0000:03:00.0", vram=True)
        second = make_card(self.drm, "card1", "amdgpu", "0000:04:00.0", vram=True)
        with mock.patch.object(system_info, "_NVIDIA_SMI", None):
            gpus = list_gpus(self.drm)
        self.assertEqual([gpu["card_path"] for gpu in gpus], [first, second])

    def test_amd_and_intel_without_nvidia(self):
        intel = make_card(self.drm, "card0", "i915", "0000:00:02.0", vendor="0x8086",
                          boot_vga="1")
        amd = make_card(self.drm, "card1", "amdgpu", "0000:03:00.0", vram=True)
        make_card(self.drm, "card2", "simpledrm", "0000:00:02.1")
        with mock.patch.object(system_info, "_NVIDIA_SMI", None):
            gpus = list_gpus(self.drm)

        # The dedicated card stays GPU 0; the boot framebuffer is no GPU.
        self.assertEqual([gpu["card_path"] for gpu in gpus], [amd, intel])
        self.assertFalse(any(gpu["only_drm_card"] for gpu in gpus))

    def test_single_card_may_count_clients_without_pdev(self):
        make_card(self.drm, "card0", "amdgpu", "0000:03:00.0", vram=True)
        with mock.patch.object(system_info, "_NVIDIA_SMI", None):
            gpus = list_gpus(self.drm)
        self.assertEqual(len(gpus), 1)
        self.assertTrue(gpus[0]["only_drm_card"])


class TestPerGpuQueries(unittest.TestCase):
    def test_nvidia_commands_select_their_gpu(self):
        monitor = GpuSystemMonitor.__new__(GpuSystemMonitor)
        monitor._nvidia = "/usr/bin/nvidia-smi"
        monitor._nvidia_index = 1
        command = monitor._nvidia_command("--query-gpu=name", "--format=csv")
        self.assertEqual(command[-2:], ["-i", "1"])

    def test_engine_busy_time_is_split_by_device(self):
        fdinfo = {
            "/proc/10/fdinfo/3": ("drm-driver:\tamdgpu\ndrm-pdev:\t0000:03:00.0\n"
                                  "drm-client-id:\t1\ndrm-engine-gfx:\t100 ns\n"),
            # Same client through a second fd: counted once.
            "/proc/10/fdinfo/4": ("drm-driver:\tamdgpu\ndrm-pdev:\t0000:03:00.0\n"
                                  "drm-client-id:\t1\ndrm-engine-gfx:\t100 ns\n"),
            "/proc/10/fdinfo/5": ("drm-driver:\ti915\ndrm-pdev:\t0000:00:02.0\n"
                                  "drm-client-id:\t2\ndrm-engine-render:\t70 ns\n"),
            "/proc/11/fdinfo/3": ("drm-driver:\tamdgpu\ndrm-client-id:\t3\n"
                                  "drm-engine-gfx:\t5 ns\n"),
        }
        dirs = {"/proc": ["10", "11", "self"], "/proc/10/fdinfo": ["3", "4", "5"],
                "/proc/11/fdinfo": ["3"]}
        patch_listdir, patch_open = fake_proc(fdinfo, dirs)
        with patch_listdir, patch_open:
            amd = GpuSystemMonitor._collect_drm_usage("0000:03:00.0", only_drm_card=False)
            intel = GpuSystemMonitor._collect_drm_usage("0000:00:02.0", only_drm_card=False)
            only = GpuSystemMonitor._collect_drm_usage("0000:03:00.0", only_drm_card=True)

        self.assertEqual(amd["ns"], {"gfx": 100})
        self.assertEqual(intel["ns"], {"render": 70})
        # A client without drm-pdev belongs to the GPU only if it is the sole card.
        self.assertEqual(only["ns"], {"gfx": 105})


ARC_XE = "0000:03:00.0"


def xe_fdinfo(client, rcs, vcs, total, vram="vram0", vram_value="512 MiB"):
    return (f"drm-driver:\txe\ndrm-pdev:\t{ARC_XE}\ndrm-client-id:\t{client}\n"
            f"drm-total-system0:\t4096 KiB\ndrm-resident-system0:\t4096 KiB\n"
            f"drm-total-{vram}:\t{vram_value}\ndrm-resident-{vram}:\t{vram_value}\n"
            f"drm-cycles-rcs:\t{rcs}\ndrm-total-cycles-rcs:\t{total}\n"
            f"drm-cycles-vcs:\t{vcs}\ndrm-total-cycles-vcs:\t{total}\n"
            f"drm-engine-capacity-vcs:\t2\n")


GIB = 1024 ** 3


def i915_regions(*regions):
    """drm_i915_query_memory_regions answer for (memory class, probed size) pairs."""
    data = struct.pack("=I3I", len(regions), 0, 0, 0)
    for mem_class, size in regions:
        data += struct.pack("=HHIQQ8Q", mem_class, 0, 0, size, size, *[0] * 8)
    return data


def xe_regions(*regions):
    """drm_xe_query_mem_regions answer for (memory class, total size) pairs."""
    data = struct.pack("=II", len(regions), 0)
    for mem_class, size in regions:
        data += struct.pack("=HHIQQQQ6Q", mem_class, 0, 4096, size, 0, size, 0, *[0] * 6)
    return data


def fake_drm_ioctl(answer, calls):
    """fcntl.ioctl stand-in that answers the i915/xe two-pass queries like the kernel."""
    def ioctl(fd, request, arg, *rest):
        calls.append(request)
        if request == system_info._DRM_IOCTL_XE_DEVICE_QUERY:
            _ext, _query, size, data_ptr, _r0, _r1 = struct.unpack("=QIIQ2Q", bytes(arg))
            if size == 0:
                struct.pack_into("=I", arg, 12, len(answer))
            else:
                ctypes.memmove(data_ptr, answer, len(answer))
        elif request == system_info._DRM_IOCTL_I915_QUERY:
            _count, _flags, item_ptr = struct.unpack("=IIQ", bytes(arg))
            _query, length, _flags, data_ptr = struct.unpack("=QiIQ", ctypes.string_at(item_ptr, 24))
            if length == 0:
                ctypes.memmove(item_ptr + 8, struct.pack("=i", len(answer)), 4)
            else:
                ctypes.memmove(data_ptr, answer, len(answer))
        else:
            raise OSError(25, "Inappropriate ioctl for device")
        return 0
    return ioctl


class TestIntelArc(unittest.TestCase):
    def test_parse_xe_fdinfo(self):
        usage = _parse_drm_fdinfo(xe_fdinfo(1, rcs=500, vcs=20, total=1000))
        self.assertEqual(usage["cycles"], {"rcs": 500, "vcs": 20})
        self.assertEqual(usage["total_cycles"], {"rcs": 1000, "vcs": 1000})
        self.assertEqual(usage["capacity"], {"vcs": 2})
        self.assertEqual(usage["ns"], {})
        # Only device memory counts as VRAM, system0 does not.
        self.assertEqual(usage["vram_kib"], 512 * 1024)

    def test_parse_i915_arc_fdinfo(self):
        usage = _parse_drm_fdinfo(
            "drm-driver:\ti915\ndrm-pdev:\t0000:03:00.0\ndrm-client-id:\t7\n"
            "drm-engine-render:\t2500 ns\ndrm-engine-capacity-video:\t2\n"
            "drm-engine-video:\t100 ns\ndrm-total-local0:\t300 MiB\n"
            "drm-resident-local0:\t200 MiB\ndrm-resident-stolen-system0:\t0\n")
        self.assertEqual(usage["ns"], {"render": 2500, "video": 100})
        self.assertEqual(usage["capacity"], {"video": 2})
        self.assertEqual(usage["vram_kib"], 200 * 1024)

    def test_parse_memory_units_and_amdgpu_legacy_key(self):
        self.assertEqual(_parse_drm_fdinfo("drm-resident-vram0:\t2048\n")["vram_kib"], 2)
        self.assertEqual(_parse_drm_fdinfo("drm-resident-local0:\t1 GiB\n")["vram_kib"],
                         1024 * 1024)
        # amdgpu reports the same VRAM twice (old and new key): counted once.
        amd = _parse_drm_fdinfo("drm-memory-vram:\t1024 KiB\ndrm-resident-vram:\t1024 KiB\n")
        self.assertEqual(amd["vram_kib"], 1024)
        # An iGPU only has system memory: no VRAM at all.
        self.assertIsNone(_parse_drm_fdinfo("drm-resident-system0:\t4 MiB\n")["vram_kib"])

    def make_monitor(self):
        monitor = GpuSystemMonitor.__new__(GpuSystemMonitor)
        monitor._prev_engine_usage = None
        monitor._prev_engine_time = None
        return monitor

    def test_xe_engine_load_uses_cycles_and_capacity(self):
        monitor = self.make_monitor()
        first = {"ns": {}, "cycles": {"rcs": 0, "vcs": 0},
                 "total_cycles": {"rcs": 1000, "vcs": 1000}, "capacity": {"vcs": 2},
                 "vram_kib": None}
        second = {"ns": {}, "cycles": {"rcs": 750, "vcs": 1000},
                  "total_cycles": {"rcs": 2000, "vcs": 2000}, "capacity": {"vcs": 2},
                  "vram_kib": None}
        self.assertEqual(monitor._poll_sysfs_engines(first), {})
        engines = monitor._poll_sysfs_engines(second)
        self.assertAlmostEqual(engines["3D"], 75.0)
        # Two video engines fully busy for half the time each: 50 %, not 100 %.
        self.assertAlmostEqual(engines["Video Decode"], 50.0)

    def test_xe_card_reports_load_vram_temperature_and_power(self):
        with tempfile.TemporaryDirectory() as drm:
            card = make_card(drm, "card0", "xe", ARC_XE, vendor="0x8086")
            hwmon = os.path.join(card, "hwmon", "hwmon3")
            os.makedirs(hwmon)
            # xe has no temp1 or energy1: package temperature and energy come as 2.
            for name, value in {"temp2_input": "48000", "temp3_input": "60000",
                                "energy2_input": "1000000"}.items():
                with open(os.path.join(hwmon, name), "w") as f:
                    f.write(value + "\n")
            with mock.patch.object(system_info, "_read_sysfs_str",
                                   wraps=system_info._read_sysfs_str):
                monitor = GpuSystemMonitor({"backend": "sysfs", "card_path": card,
                                            "pci_slot": ARC_XE, "only_drm_card": True})
            self.assertTrue(monitor._power_counter.path.endswith("energy2_input"))

            dirs = {"/proc": ["20", "21"], "/proc/20/fdinfo": ["5"], "/proc/21/fdinfo": ["6"]}
            steps = [
                {"/proc/20/fdinfo/5": xe_fdinfo(1, rcs=0, vcs=0, total=1000),
                 "/proc/21/fdinfo/6": xe_fdinfo(2, rcs=0, vcs=0, total=1000,
                                                vram_value="256 MiB")},
                {"/proc/20/fdinfo/5": xe_fdinfo(1, rcs=300, vcs=0, total=2000),
                 "/proc/21/fdinfo/6": xe_fdinfo(2, rcs=300, vcs=0, total=2000,
                                                vram_value="256 MiB")},
            ]
            results = []
            for fdinfo in steps:
                patch_listdir, patch_open = fake_proc(fdinfo, dirs)
                with patch_listdir, patch_open, \
                        mock.patch.object(system_info.time, "monotonic",
                                          return_value=100.0 + len(results)):
                    results.append(monitor.poll())

        result = results[-1]
        self.assertEqual(result["temp_c"], 48.0)
        self.assertAlmostEqual(result["vram_used_mb"], 768.0)
        self.assertIsNone(result["vram_total_mb"])
        # Two clients each busy 300 of 1000 cycles on the render engine: 60 %.
        self.assertAlmostEqual(result["engines"]["3D"], 60.0)
        self.assertAlmostEqual(result["percent"], 60.0)

    def test_xe_vram_size_from_tiles(self):
        with tempfile.TemporaryDirectory() as drm:
            card = make_card(drm, "card0", "xe", ARC_XE, vendor="0x8086")
            os.makedirs(os.path.join(card, "tile0"))
            with open(os.path.join(card, "tile0", "physical_vram_size_bytes"), "w") as f:
                f.write(f"{16 * 1024 ** 3}\n")
            monitor = GpuSystemMonitor({"backend": "sysfs", "card_path": card,
                                        "pci_slot": ARC_XE, "only_drm_card": True})
            with mock.patch.object(GpuSystemMonitor, "_collect_drm_usage",
                                   return_value={"ns": {}, "cycles": {}, "total_cycles": {},
                                                 "capacity": {}, "vram_kib": None}):
                result = monitor.poll()
        self.assertEqual(result["vram_total_mb"], 16 * 1024)

    def test_device_memory_regions_are_summed(self):
        self.assertEqual(_sum_device_memory_regions(
            i915_regions((0, 32 * GIB), (1, 8 * GIB)), 16), 8 * GIB)
        self.assertEqual(_sum_device_memory_regions(
            xe_regions((0, 32 * GIB), (1, 12 * GIB), (1, 12 * GIB)), 8), 24 * GIB)
        # Integrated graphics only have system memory.
        self.assertIsNone(_sum_device_memory_regions(i915_regions((0, 32 * GIB)), 16))
        self.assertIsNone(_sum_device_memory_regions(b"", 16))

    def drm_vram_total(self, driver, answer):
        calls = []
        with tempfile.TemporaryDirectory() as drm:
            card = make_card(drm, "card1", driver, ARC_XE, vendor="0x8086")
            os.makedirs(os.path.join(card, "drm", "renderD129"))
            with mock.patch.object(system_info.os, "open", return_value=99) as fake_open, \
                    mock.patch.object(system_info.os, "close") as fake_close, \
                    mock.patch.object(system_info.fcntl, "ioctl", fake_drm_ioctl(answer, calls)):
                total = _drm_vram_total(card, driver)
        if calls:
            self.assertEqual(fake_open.call_args[0][0], "/dev/dri/renderD129")
            fake_close.assert_called_once_with(99)
        return total, calls

    def test_xe_vram_size_from_device_query(self):
        total, calls = self.drm_vram_total("xe", xe_regions((0, 32 * GIB), (1, 12 * GIB)))
        self.assertEqual(total, 12 * GIB)
        self.assertEqual(calls, [system_info._DRM_IOCTL_XE_DEVICE_QUERY] * 2)

    def test_i915_arc_vram_size_from_query(self):
        total, calls = self.drm_vram_total("i915", i915_regions((0, 32 * GIB), (1, 8 * GIB)))
        self.assertEqual(total, 8 * GIB)
        self.assertEqual(calls, [system_info._DRM_IOCTL_I915_QUERY] * 2)

    def test_other_drivers_are_not_queried(self):
        self.assertEqual(self.drm_vram_total("amdgpu", b""), (None, []))

    def test_unopenable_render_node_gives_no_size(self):
        with tempfile.TemporaryDirectory() as drm:
            card = make_card(drm, "card1", "xe", ARC_XE, vendor="0x8086")
            os.makedirs(os.path.join(card, "drm", "renderD129"))
            with mock.patch.object(system_info.os, "open", side_effect=PermissionError):
                self.assertIsNone(_drm_vram_total(card, "xe"))

    def test_xe_card_without_tile_file_asks_the_driver_once(self):
        with tempfile.TemporaryDirectory() as drm:
            card = make_card(drm, "card0", "xe", ARC_XE, vendor="0x8086")
            monitor = GpuSystemMonitor({"backend": "sysfs", "card_path": card,
                                        "pci_slot": ARC_XE, "only_drm_card": True})
            usage = {"ns": {}, "cycles": {}, "total_cycles": {}, "capacity": {}, "vram_kib": None}
            with mock.patch.object(GpuSystemMonitor, "_collect_drm_usage", return_value=usage), \
                    mock.patch.object(system_info, "_drm_vram_total",
                                      return_value=12 * GIB) as query:
                results = [monitor.poll(), monitor.poll()]
        self.assertEqual([result["vram_total_mb"] for result in results], [12 * 1024] * 2)
        query.assert_called_once_with(card, "xe")

    def test_process_gpu_percent_from_xe_cycles(self):
        monitor = GpuMonitor.__new__(GpuMonitor)
        monitor._nvidia = None
        monitor._prev_busy = {}
        dirs = {"/proc": ["30", "self"], "/proc/30/fdinfo": ["4"]}
        polls = []
        for rcs, total in ((0, 1000), (400, 2000)):
            fdinfo = {"/proc/30/fdinfo/4": xe_fdinfo(9, rcs=rcs, vcs=0, total=total)}
            patch_listdir, patch_open = fake_proc(fdinfo, dirs)
            with patch_listdir, patch_open:
                polls.append(monitor._poll_drm_fdinfo())
        self.assertAlmostEqual(polls[-1][30]["gpu_percent"], 40.0)
        self.assertAlmostEqual(polls[-1][30]["vram_mb"], 512.0)

    def test_arc_card_is_listed_next_to_nvidia_and_igpu(self):
        with tempfile.TemporaryDirectory() as drm:
            igpu = make_card(drm, "card0", "i915", "0000:00:02.0", vendor="0x8086",
                             boot_vga="1")
            arc = make_card(drm, "card1", "xe", ARC_XE, vendor="0x8086")
            patch_smi, patch_output = nvidia_smi("0, 00000000:01:00.0\n")
            with patch_smi, patch_output:
                gpus = list_gpus(drm)
        self.assertEqual([gpu["backend"] for gpu in gpus], ["nvidia", "sysfs", "sysfs"])
        self.assertEqual({gpu["card_path"] for gpu in gpus[1:]}, {arc, igpu})
        self.assertEqual(gpus[1]["card_path"], arc)


def nvidia_query_row(index):
    return (f"{index}, RTX {index}, {index}, 1024, 24576, 50, 100.5, "
            "4, 16, 4, 16, 0, 0")


class FakeDmon:
    def __init__(self, command, **_kwargs):
        self.indices = [int(index) for index in command[command.index("-i") + 1].split(",")]
        self.returncode = 0

    def communicate(self, timeout=None):
        rows = "".join(f"    {index}    {index}     1     2     3\n" for index in self.indices)
        return "# gpu     sm    mem    enc    dec\n# Idx      %      %      %      %\n" + rows, ""


class TestManyGpus(unittest.TestCase):
    """Ten, twenty or more cards: no fixed limit, and one round stays a single nvidia-smi
    query, one dmon per 16 GPUs and one /proc scan, however many GPUs there are."""

    def test_ten_nvidia_and_ten_amd_are_all_listed(self):
        with tempfile.TemporaryDirectory() as drm:
            for i in range(10):
                make_card(drm, f"card{i}", "amdgpu", f"0000:{0x40 + i:02x}:00.0", vram=True)
            smi = "".join(f"{i}, 00000000:{0x10 + i:02X}:00.0, 550.54\n" for i in range(10))
            patch_smi, patch_output = nvidia_smi(smi)
            with patch_smi, patch_output:
                gpus = list_gpus(drm)
        self.assertEqual(len(gpus), 20)
        self.assertEqual([gpu["index"] for gpu in gpus[:10]], list(range(10)))
        self.assertEqual({gpu["backend"] for gpu in gpus[10:]}, {"sysfs"})
        self.assertEqual(len({gpu["pci_slot"] for gpu in gpus}), 20)

    def test_twenty_nvidia_gpus_share_one_query_and_two_dmon_calls(self):
        with mock.patch.object(system_info, "_NVIDIA_SMI", "/usr/bin/nvidia-smi"):
            monitors = [GpuSystemMonitor({"backend": "nvidia", "index": i,
                                          "pci_slot": f"0000:{0x10 + i:02x}:00.0",
                                          "driver_version": "550.54"}) for i in range(20)]
            query = "".join(nvidia_query_row(i) + "\n" for i in range(20))
            with mock.patch.object(system_info.subprocess, "check_output",
                                   return_value=query) as check_output, \
                    mock.patch.object(system_info.subprocess, "Popen",
                                      side_effect=FakeDmon) as popen:
                snapshots = poll_gpus(monitors)

        check_output.assert_called_once()
        chunks = [call.args[0][call.args[0].index("-i") + 1] for call in popen.call_args_list]
        self.assertEqual(chunks, [",".join(map(str, range(16))),
                                  ",".join(map(str, range(16, 20)))])
        self.assertEqual([snapshot["name"] for snapshot in snapshots],
                         [f"RTX {i}" for i in range(20)])
        self.assertEqual(snapshots[19]["percent"], 19.0)
        self.assertEqual(snapshots[19]["engines"]["3D"], 19.0)
        self.assertEqual(snapshots[0]["driver_version"], "550.54")

    def test_proc_is_scanned_once_for_all_cards(self):
        with tempfile.TemporaryDirectory() as drm:
            monitors = []
            for i in range(12):
                device = make_card(drm, f"card{i}", "amdgpu", f"0000:{0x40 + i:02x}:00.0",
                                   vram=True)
                monitors.append(GpuSystemMonitor({"backend": "sysfs", "card_path": device,
                                                  "pci_slot": f"0000:{0x40 + i:02x}:00.0"}))
            with mock.patch.object(system_info, "_scan_drm_clients",
                                   return_value=[]) as scan:
                snapshots = poll_gpus(monitors)
        scan.assert_called_once()
        self.assertEqual(len(snapshots), 12)
        self.assertTrue(all(snapshot is not None for snapshot in snapshots))


class FakeMonitor:
    def __init__(self, gpu):
        self.gpu = gpu

    def poll(self):
        return {"name": self.gpu["name"], "percent": self.gpu["percent"]}


class TestGpuWorker(unittest.TestCase):
    def test_worker_emits_one_snapshot_per_gpu(self):
        gpus = [{"name": "GeForce", "percent": 40.0}, {"name": "Radeon", "percent": 10.0}]
        with mock.patch.object(system_info, "list_gpus", return_value=gpus), \
                mock.patch.object(system_info, "GpuSystemMonitor", FakeMonitor):
            worker = GpuSystemWorker()
        self.assertEqual(worker.gpu_count, 2)
        received = []
        worker.snapshotReady.connect(lambda snapshots: (received.append(snapshots),
                                                        worker._stop_event.set()))
        worker.run()
        self.assertEqual([gpu["name"] for gpu in received[0]], ["GeForce", "Radeon"])


class TestPerformancePageGpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_page(self, gpu_count):
        from pages.performance_page import PerformancePage

        gpus = [{"name": f"GPU{i}", "percent": 0.0} for i in range(gpu_count)]
        with mock.patch.object(system_info, "list_gpus", return_value=gpus), \
                mock.patch.object(system_info, "GpuSystemMonitor", FakeMonitor):
            page = PerformancePage()
        page.shutdown()
        self.addCleanup(page.deleteLater)
        return page

    def test_each_gpu_gets_its_own_tile_and_graphs(self):
        page = self.make_page(2)
        self.assertIn("gpu:0", page.tiles)
        self.assertIn("gpu:1", page.tiles)

        page._on_gpu_snapshot_ready([
            {"name": "NVIDIA GeForce RTX 3060", "percent": 80.0},
            {"name": "AMD Radeon RX 6600", "percent": 20.0},
        ])
        page._tick()
        self.assertEqual(page._subtitles["gpu:0"], "NVIDIA GeForce RTX 3060")
        self.assertEqual(page._subtitles["gpu:1"], "AMD Radeon RX 6600")
        self.assertEqual(page._gpu_histories[0]["Utilization"][-1], 80.0)
        self.assertEqual(page._gpu_histories[1]["Utilization"][-1], 20.0)

        page._select("gpu:1")
        self.assertIs(page._gpu_history, page._gpu_histories[1])

    def test_four_gpus_get_four_tiles(self):
        page = self.make_page(4)
        self.assertEqual(page._gpu_keys(), ["gpu:0", "gpu:1", "gpu:2", "gpu:3"])
        names = ["RTX 4090", "RTX 3060", "Radeon RX 7800", "Intel UHD 770"]
        page._on_gpu_snapshot_ready([{"name": name, "percent": float(i * 10)}
                                     for i, name in enumerate(names)])
        page._tick()
        self.assertEqual([page._subtitles[key] for key in page._gpu_keys()], names)
        self.assertEqual([page._gpu_histories[i]["Utilization"][-1] for i in range(4)],
                         [0.0, 10.0, 20.0, 30.0])

    def test_twenty_gpus_fit_into_the_scrolling_sidebar(self):
        page = self.make_page(20)
        self.assertEqual(len(page._gpu_keys()), 20)
        page._on_gpu_snapshot_ready([{"name": f"GPU{i}", "percent": float(i)}
                                     for i in range(20)])
        page._tick()
        self.assertEqual(page._gpu_histories[19]["Utilization"][-1], 19.0)
        sidebar = page._nav_scroll.widget()
        self.assertTrue(all(sidebar.isAncestorOf(page.tiles[key]) for key in page._gpu_keys()))

    def test_vram_usage_without_size_is_still_shown(self):
        page = self.make_page(1)
        text = page._format_gpu_text({"name": "Intel Arc A770", "vram_used_mb": 1536.0,
                                      "vram_total_mb": None}, 0.0)
        self.assertRegex(text, r"1[.,]5 GB<br>")

    def test_without_gpu_there_is_still_one_tile(self):
        page = self.make_page(0)
        self.assertEqual(page._gpu_keys(), ["gpu:0"])
        page._tick()

    def test_remote_server_with_more_gpus_adds_tiles(self):
        page = self.make_page(1)
        page._remote_enabled = True
        page._on_remote_snapshot_ready({"gpus": [
            {"name": "A", "percent": 1.0, "engines": {}},
            {"name": "B", "percent": 2.0, "engines": {}},
            {"name": "C", "percent": 3.0, "engines": {}},
        ]})
        self.assertEqual(page._gpu_keys(), ["gpu:0", "gpu:1", "gpu:2"])
        self.assertFalse(page.tiles["gpu:2"].isHidden())
        page._tick()
        self.assertEqual(page._gpu_histories[2]["Utilization"][-1], 3.0)

        # An older server only sends "gpu": the extra tiles go away again.
        page._select("gpu:2")
        page._on_remote_snapshot_ready({"gpu": {"name": "A", "percent": 1.0}})
        self.assertTrue(page.tiles["gpu:2"].isHidden())
        self.assertEqual(page._selected, "cpu")


if __name__ == "__main__":
    unittest.main()
