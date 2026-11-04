"""Memory view data: the overview, everything known about the memory, and the actions behind it.

Nothing in here moves a program or empties a cache on its own: every action starts from an explicit click.
"""
from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field

import psutil
from PySide6.QtCore import Signal

from app.hardware_setup import sudo_helper
from app.i18n import N_, format_decimal, tr
from app.system_info import StoppableWorker, WorkerStopped, list_ram_sensors, read_dmi_memory

GIB = 1024 ** 3
MIB = 1024 ** 2

MEMINFO_FILE = "/proc/meminfo"
SWAPS_FILE = "/proc/swaps"
PRESSURE_FILE = "/proc/pressure/memory"
_PRESSURE_TEXTS = {
    "none": N_("None"),
    "light": N_("Light"),
    "high": N_("High"),
    None: N_("Unknown"),
}
PRESSURE_LIGHT = 1.0
PRESSURE_HIGH = 10.0
TIGHT_AVAILABLE_SHARE = 0.10

VISIBLE_INTERVAL = 5.0

# Process names are cut to 15 characters by the kernel, so the comparison is too.
_ESSENTIAL_NAMES = frozenset(name[:15] for name in (
    "systemd", "dbus-daemon", "dbus-broker", "Xorg", "Xwayland", "gnome-shell",
    "plasmashell", "kwin_x11", "kwin_wayland", "ksmserver", "cinnamon", "cinnamon-session",
    "muffin", "mutter", "xfwm4", "xfce4-session", "xfce4-panel", "mate-session", "marco",
    "sddm", "gdm", "lightdm", "pipewire", "wireplumber", "pulseaudio", "sway", "Hyprland",
    "lxqt-session", "budgie-wm",
))
_ESSENTIAL_PREFIXES = ("gnome-session",)

# Protection against a process with the same pid that started after the list was read.
_CREATE_TIME_TOLERANCE = 0.01
_HELPER_TIMEOUT = 120
_SETTLE_SECONDS = 0.5

ERROR_NOT_SET_UP = N_(
    "Administrator rights are not set up yet. Open Settings and click "
    "\"Set up hardware data with sudo\"."
)
ERROR_HELPER_OLD = N_(
    "The helper is out of date. Open Settings and click "
    "\"Set up hardware data with sudo\" again."
)
ERROR_HELPER_FAILED = N_("The helper reported an error, nothing was changed.")
ERROR_HELPER_TIMEOUT = N_("The helper did not finish in time.")
ERROR_PAGEOUT_REFUSED = N_(
    "This program protects its memory or runs with other rights, "
    "so it cannot be moved to swap."
)
ERROR_PAGEOUT_KERNEL = N_("This kernel is too old to move a single program to swap.")
ERROR_PAGEOUT_NO_PYTHON = N_("Moving to swap needs python3 in /usr/bin, which is missing.")
ERROR_DROP_REFUSED = N_("The system refused to empty the cache.")


def format_bytes(value: int | float) -> str:
    if value >= GIB:
        return f"{format_decimal(value / GIB)} GB"
    return f"{format_decimal(value / MIB)} MB"


def is_essential(name: str) -> bool:
    """Programs the desktop session cannot live without: no actions."""
    return name[:15] in _ESSENTIAL_NAMES or name.startswith(_ESSENTIAL_PREFIXES)


@dataclass(frozen=True)
class MemoryOverview:
    total: int
    used: int
    available: int
    cached: int
    # None: not known, which is the case for a remote server.
    swap_total: int | None = None
    swap_used: int | None = None
    pressure_some: float | None = None
    pressure_full: float | None = None


@dataclass(frozen=True)
class MemorySnapshot:
    overview: MemoryOverview
    ram_sensors: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class SwapDevice:
    name: str
    type: str
    size: int
    used: int


@dataclass(frozen=True)
class MemoryModule:
    locator: str
    size: int
    form_factor: str = ""
    type: str = ""
    type_detail: str = ""
    speed: str = ""
    configured_speed: str = ""
    manufacturer: str = ""
    part_number: str = ""
    rank: str = ""
    voltage: str = ""


@dataclass(frozen=True)
class MemoryHardware:
    max_capacity: int | None = None
    error_correction: str = ""
    slots_total: int = 0
    modules: tuple[MemoryModule, ...] = ()


def parse_meminfo(text: str) -> dict[str, int]:
    """/proc/meminfo in bytes. Counters without a unit, like HugePages_Total, stay plain numbers."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        fields = rest.split()
        if not fields:
            continue
        try:
            number = int(fields[0])
        except ValueError:
            continue
        values[name.strip()] = number * 1024 if fields[1:] == ["kB"] else number
    return values


def parse_swaps(text: str) -> list[SwapDevice]:
    """/proc/swaps, whose sizes are in KiB. The kernel writes spaces in a path as \\040."""
    devices = []
    for line in text.splitlines()[1:]:
        # From the right, as only the name can contain anything but digits.
        fields = line.rsplit(None, 4)
        if len(fields) != 5:
            continue
        try:
            size, used = int(fields[2]) * 1024, int(fields[3]) * 1024
        except ValueError:
            continue
        devices.append(SwapDevice(fields[0].replace("\\040", " "), fields[1], size, used))
    return devices


def read_meminfo() -> dict[str, int]:
    try:
        with open(MEMINFO_FILE, encoding="ascii") as handle:
            return parse_meminfo(handle.read())
    except OSError:
        return {}


def read_swaps() -> list[SwapDevice]:
    try:
        with open(SWAPS_FILE, encoding="utf-8", errors="replace") as handle:
            return parse_swaps(handle.read())
    except OSError:
        return []


_DMI_PLACEHOLDERS = frozenset(("", "unknown", "not specified", "not provided", "none",
                               "no module installed", "not installed", "undefined"))
_SIZE_UNITS = {"KB": 1024, "MB": MIB, "GB": GIB, "TB": 1024 * GIB}


def _dmi_text(value: str | None) -> str:
    """The value of a dmidecode field, empty for what firmware writes instead of nothing."""
    value = (value or "").strip()
    if value.lower() in _DMI_PLACEHOLDERS or not value.strip("0"):
        return ""
    return value


def _dmi_size(value: str | None) -> int | None:
    fields = (value or "").split()
    if len(fields) != 2 or fields[1].upper() not in _SIZE_UNITS:
        return None
    try:
        size = int(fields[0])
    except ValueError:
        return None
    return size * _SIZE_UNITS[fields[1].upper()] or None


def _dmi_blocks(text: str) -> list[tuple[str, str, dict[str, str]]]:
    """Every block as (title, handle, fields). Only single-tab lines are fields: deeper lines
    belong to a list under the field above them.
    """
    blocks: list[tuple[str, str, dict[str, str]]] = []
    current: dict[str, str] | None = None
    handle = ""
    expect_title = False
    for line in text.splitlines():
        if line.startswith("Handle "):
            handle = line.split()[1].rstrip(",")
            expect_title = True
            current = None
        elif expect_title:
            current = {}
            blocks.append((line.strip(), handle, current))
            expect_title = False
        elif current is not None and line.startswith("\t") and not line.startswith("\t\t"):
            name, _, value = line.strip().partition(":")
            current[name] = value.strip()
    return blocks


def parse_dmi_memory(text: str) -> MemoryHardware:
    """The output of "dmidecode -t memory". The serial number is left out on purpose: it
    identifies the machine and tells nothing about its memory.
    """
    blocks = _dmi_blocks(text)
    max_capacity = 0
    corrections: list[str] = []
    system_arrays = set()
    for title, handle, fields in blocks:
        if title != "Physical Memory Array" or fields.get("Use") != "System Memory":
            continue
        system_arrays.add(handle)
        max_capacity += _dmi_size(fields.get("Maximum Capacity")) or 0
        correction = fields.get("Error Correction Type", "").strip()
        if correction and correction not in corrections:
            corrections.append(correction)

    slots = 0
    modules = []
    for title, _handle, fields in blocks:
        if title != "Memory Device":
            continue
        # Flash chips and the like have an array of their own, boards without any array data
        # still have memory.
        if system_arrays and fields.get("Array Handle") not in system_arrays:
            continue
        slots += 1
        size = _dmi_size(fields.get("Size"))
        if size is None:
            continue
        modules.append(MemoryModule(
            locator=_dmi_text(fields.get("Locator")) or _dmi_text(fields.get("Bank Locator")),
            size=size,
            form_factor=_dmi_text(fields.get("Form Factor")),
            type=_dmi_text(fields.get("Type")),
            type_detail=_dmi_text(fields.get("Type Detail")),
            speed=_dmi_text(fields.get("Speed")),
            configured_speed=_dmi_text(fields.get("Configured Memory Speed")
                                       or fields.get("Configured Clock Speed")),
            manufacturer=_dmi_text(fields.get("Manufacturer")),
            part_number=_dmi_text(fields.get("Part Number")),
            rank=_dmi_text(fields.get("Rank")),
            voltage=_dmi_text(fields.get("Configured Voltage")),
        ))
    # "None" is a real answer here, unlike in the other fields.
    known = [correction for correction in corrections
             if correction == "None" or _dmi_text(correction)]
    return MemoryHardware(max_capacity=max_capacity or None, error_correction=", ".join(known),
                          slots_total=slots, modules=tuple(modules))


def read_memory_hardware() -> MemoryHardware | None:
    """None if the module data cannot be read, which needs the setup under Settings."""
    text = read_dmi_memory()
    if text is None:
        return None
    hardware = parse_dmi_memory(text)
    return hardware if hardware.slots_total else None


def _module_title(module: MemoryModule, number: int) -> str:
    if module.locator:
        return tr("Module {number}: {slot}", number=number, slot=module.locator)
    return tr("Module {number}", number=number)


def _hardware_rows(hardware: MemoryHardware) -> list[tuple[str, str]]:
    rows = []
    if hardware.max_capacity:
        rows.append((tr("Maximum capacity"), format_bytes(hardware.max_capacity)))
    rows.append((tr("Slots in use"), tr("{used} of {total}", used=len(hardware.modules),
                                        total=hardware.slots_total)))
    if hardware.error_correction:
        correction = hardware.error_correction
        rows.append((tr("Error correction"), tr("None") if correction == "None" else correction))
    return rows


def _module_rows(module: MemoryModule) -> list[tuple[str, str]]:
    candidates = (
        (N_("Size"), format_bytes(module.size)),
        (N_("Type"), " ".join(part for part in (module.type, module.form_factor) if part)),
        (N_("Details"), module.type_detail),
        (N_("Maximum speed"), module.speed),
        (N_("Current speed"), module.configured_speed),
        (N_("Manufacturer"), module.manufacturer),
        (N_("Part number"), module.part_number),
        (N_("Rank"), module.rank),
        (N_("Voltage"), module.voltage),
    )
    return [(tr(label), value) for label, value in candidates if value]


def _temperature_rows(ram_sensors: list[dict] | None) -> list[tuple[str, str]]:
    if ram_sensors is None:
        return [(tr("Temperature"), tr("Unknown"))]
    temperatures = [sensor for sensor in ram_sensors if sensor.get("unit") == "°C"]
    if not temperatures:
        return [(tr("Temperature"), tr("No sensor found"))]
    # All sensors of a kind have the same name, so a number tells them apart.
    return [(tr("Sensor {number}", number=number),
             f"{format_decimal(sensor['value'])} °C")
            for number, sensor in enumerate(temperatures, 1)]


def memory_summary_rows(overview: MemoryOverview) -> list[tuple[str, str]]:
    """The values of the block below the graph as (label, value), already translated."""
    if overview.swap_total is None:
        swap = tr("Unknown")
    elif overview.swap_total == 0:
        swap = tr("Not set up")
    else:
        swap = tr("{used} of {total}", used=format_bytes(overview.swap_used or 0),
                  total=format_bytes(overview.swap_total))
    pressure = tr(_PRESSURE_TEXTS[pressure_level(overview)])
    if overview.pressure_some is not None:
        pressure += f" ({format_decimal(overview.pressure_some)} %)"
    return [
        (tr("In use"), format_bytes(overview.used)),
        (tr("Available now"), format_bytes(overview.available)),
        (tr("Cache"), format_bytes(overview.cached)),
        (tr("Swap"), swap),
        (tr("Memory pressure"), pressure),
    ]


def memory_data_sections(
    overview: MemoryOverview,
    meminfo: dict[str, int],
    swaps: list[SwapDevice],
    hardware: MemoryHardware | None,
    ram_sensors: list[dict] | None,
    remote: bool = False,
) -> list[tuple[str, list[tuple[str, str]]]]:
    """What is known beyond memory_summary_rows as (section, [(label, value)]), already translated."""
    def from_meminfo(*items: tuple[str, str]) -> list[tuple[str, str]]:
        return [(tr(label), format_bytes(meminfo[key])) for label, key in items if key in meminfo]

    usage = from_meminfo((N_("Free"), "MemFree"), (N_("Buffers"), "Buffers"), (N_("Shared"), "Shmem"),
                         (N_("Active"), "Active"), (N_("Inactive"), "Inactive"),
                         (N_("Waiting to be written"), "Dirty"), (N_("Being written"), "Writeback"),
                         (N_("Mapped files"), "Mapped"))

    kernel = from_meminfo((N_("Kernel caches (slab)"), "Slab"), (N_("Kernel stacks"), "KernelStack"),
                          (N_("Page tables"), "PageTables"), (N_("Promised to programs"), "Committed_AS"),
                          (N_("Commit limit"), "CommitLimit"))
    if meminfo.get("HugePages_Total"):
        kernel.append((tr("Huge pages"), tr("{used} of {total}",
                                            used=meminfo["HugePages_Total"] - meminfo.get("HugePages_Free", 0),
                                            total=meminfo["HugePages_Total"])))

    swap: list[tuple[str, str]] = []
    if overview.swap_total:
        swap_used = overview.swap_used or 0
        swap = [(tr("Free"), format_bytes(max(0, overview.swap_total - swap_used))),
                *from_meminfo((N_("Also still in memory"), "SwapCached"))]
        swap += [(device.name, tr("{used} of {total}", used=format_bytes(device.used),
                                  total=format_bytes(device.size)))
                 for device in swaps]

    sections = []
    if usage:
        sections.append((tr("Usage"), usage))
    if kernel:
        sections.append((tr("Kernel"), kernel))
    if swap:
        sections.append((tr("Swap"), swap))
    if hardware is not None:
        sections.append((tr("Hardware"), _hardware_rows(hardware)))
        sections += [(_module_title(module, number), _module_rows(module))
                     for number, module in enumerate(hardware.modules, 1)]
    elif remote:
        sections.append((tr("Hardware"), [(tr("Modules"), tr("Only shown for this PC"))]))
    else:
        sections.append((tr("Hardware"), [(tr("Modules"), tr(
            "Needs \"Set up hardware data with sudo\" under Settings"))]))
    sections.append((tr("Temperature"), _temperature_rows(ram_sensors)))
    return sections


def parse_pressure(text: str) -> tuple[float | None, float | None]:
    """The avg60 values of the "some" and "full" lines of a PSI file."""
    values: dict[str, float] = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        for field in fields[1:]:
            name, _, value = field.partition("=")
            if name == "avg60":
                try:
                    values[fields[0]] = float(value)
                except ValueError:
                    pass
    return values.get("some"), values.get("full")


def read_overview() -> MemoryOverview:
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    try:
        with open(PRESSURE_FILE, encoding="ascii") as handle:
            some, full = parse_pressure(handle.read())
    except OSError:
        # Kernels without CONFIG_PSI, or with psi=0 on the command line.
        some, full = None, None
    return MemoryOverview(
        total=vm.total,
        used=vm.total - vm.available,
        available=vm.available,
        cached=getattr(vm, "cached", 0) + getattr(vm, "buffers", 0),
        swap_total=swap.total,
        swap_used=swap.used,
        pressure_some=some,
        pressure_full=full,
    )


def pressure_level(overview: MemoryOverview) -> str | None:
    """"none", "light" or "high"; None if the system does not report pressure."""
    if overview.pressure_some is None:
        return None
    if overview.pressure_some >= PRESSURE_HIGH:
        return "high"
    if overview.pressure_some >= PRESSURE_LIGHT:
        return "light"
    return "none"


def is_tight(overview: MemoryOverview) -> bool:
    if pressure_level(overview) == "high":
        return True
    return overview.total > 0 and overview.available < overview.total * TIGHT_AVAILABLE_SHARE


def overview_from_remote(system: dict) -> MemoryOverview:
    total = int(system.get("mem_total_gb", 0) * GIB)
    available = int(system.get("mem_available_gb", 0) * GIB)
    return MemoryOverview(
        total=total, used=total - available, available=available,
        cached=int(system.get("mem_cached_gb", 0) * GIB))


class MemoryWorker(StoppableWorker):
    """Reads the sensors while the view is visible, the module data once."""

    snapshotReady = Signal(object)
    hardwareReady = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._visible = threading.Event()
        self._refresh = threading.Event()
        self._consumed = threading.Event()
        self._consumed.set()
        self._hardware_wanted = threading.Event()
        self._hardware_loaded = False

    def set_visible(self, visible: bool) -> None:
        if visible:
            self._visible.set()
            self._refresh.set()
            # Asked again on every look, so the setup under Settings works without a restart.
            if not self._hardware_loaded:
                self._hardware_wanted.set()
        else:
            self._visible.clear()

    def request_refresh(self) -> None:
        self._refresh.set()

    def mark_consumed(self) -> None:
        self._consumed.set()

    def run(self) -> None:
        last_scan = None
        while not self._stop_event.is_set():
            now = time.monotonic()
            if self._visible.is_set() and (self._refresh.is_set() or last_scan is None
                                           or now - last_scan >= VISIBLE_INTERVAL):
                self._refresh.clear()
                last_scan = now
                self._scan()
            if self._hardware_wanted.is_set():
                self._hardware_wanted.clear()
                self._load_hardware()
            self._stop_event.wait(0.5)

    def _load_hardware(self) -> None:
        hardware = read_memory_hardware()
        if hardware is not None and not self._stop_event.is_set():
            self._hardware_loaded = True
            self.hardwareReady.emit(hardware)

    def _scan(self) -> None:
        # A page that has not drawn the last result yet does not need the next one.
        if self._stop_event.is_set() or not self._consumed.is_set():
            return
        overview = read_overview()
        sensors = list_ram_sensors()
        self._consumed.clear()
        self.snapshotReady.emit(MemorySnapshot(overview, sensors))


def _live_processes(processes: list[tuple[int, float]]) -> list[psutil.Process]:
    """The listed processes that still exist, leaving out pids that were reused since."""
    live = []
    for pid, created in processes:
        try:
            process = psutil.Process(pid)
            if abs(process.create_time() - created) <= _CREATE_TIME_TOLERANCE:
                live.append(process)
        except psutil.Error:
            continue
    return live


def _swapped_bytes(processes: list[psutil.Process]) -> int:
    # Not the drop in RSS: shared memory leaves RSS without leaving RAM, so that would
    # report memory as moved that is still there.
    total = 0
    for process in processes:
        try:
            with open(f"/proc/{process.pid}/status") as handle:
                for line in handle:
                    if line.startswith("VmSwap:"):
                        total += int(line.split()[1]) * 1024
                        break
        except (OSError, ValueError, IndexError):
            continue
    return total


def _helper_error(returncode: int) -> str:
    """Text for the exit codes every helper command has in common."""
    if returncode == 1:  # from sudo: no rule for this helper
        return ERROR_NOT_SET_UP
    if returncode == 2:  # a helper from before these commands sees an invalid device
        return ERROR_HELPER_OLD
    return ERROR_HELPER_FAILED


@dataclass(frozen=True)
class PageOutResult:
    name: str
    error: str = ""
    moved_bytes: int = 0
    refused: int = 0


class PageOutWorker(StoppableWorker):
    """Moves the memory of a program to swap. The program keeps running and fetches it back on use."""

    resultReady = Signal(object)

    def __init__(self, name: str, processes: list[tuple[int, float]], parent=None):
        super().__init__(parent)
        self._name = name
        self._processes = processes

    def run(self) -> None:
        try:
            result = self._page_out()
        except WorkerStopped:
            return
        if not self._stop_event.is_set():
            self.resultReady.emit(result)

    def _page_out(self) -> PageOutResult:
        helper = sudo_helper()
        if not helper:
            return PageOutResult(self._name, error=ERROR_NOT_SET_UP)
        live = _live_processes(self._processes)
        if not live:
            return PageOutResult(self._name)
        before = _swapped_bytes(live)
        command = ["sudo", "-n", helper, "pageout", *(str(process.pid) for process in live)]
        try:
            done = self._run_command(command, _HELPER_TIMEOUT)
        except subprocess.TimeoutExpired:
            return PageOutResult(self._name, error=ERROR_HELPER_TIMEOUT)
        except OSError:
            return PageOutResult(self._name, error=ERROR_NOT_SET_UP)
        if done.returncode == 3:
            return PageOutResult(self._name, error=ERROR_PAGEOUT_REFUSED)
        if done.returncode == 4:
            return PageOutResult(self._name, error=ERROR_PAGEOUT_KERNEL)
        if done.returncode == 127:
            return PageOutResult(self._name, error=ERROR_PAGEOUT_NO_PYTHON)
        if done.returncode != 0:
            return PageOutResult(self._name, error=_helper_error(done.returncode))
        # The numbers settle right after the kernel has written the pages.
        self._stop_event.wait(_SETTLE_SECONDS)
        return PageOutResult(self._name, moved_bytes=max(0, _swapped_bytes(live) - before),
                             refused=parse_refused(done.stdout))


def parse_refused(output: str) -> int:
    for field in output.split():
        name, _, value = field.partition("=")
        if name == "refused" and value.isdigit():
            return int(value)
    return 0


@dataclass(frozen=True)
class DropCachesResult:
    error: str = ""
    before_bytes: int = 0
    after_bytes: int = 0


class DropCachesWorker(StoppableWorker):
    resultReady = Signal(object)

    def run(self) -> None:
        try:
            result = self._drop()
        except WorkerStopped:
            return
        if not self._stop_event.is_set():
            self.resultReady.emit(result)

    def _drop(self) -> DropCachesResult:
        helper = sudo_helper()
        if not helper:
            return DropCachesResult(error=ERROR_NOT_SET_UP)
        before = read_overview().cached
        try:
            done = self._run_command(["sudo", "-n", helper, "drop-caches"], _HELPER_TIMEOUT)
        except subprocess.TimeoutExpired:
            return DropCachesResult(error=ERROR_HELPER_TIMEOUT)
        except OSError:
            return DropCachesResult(error=ERROR_NOT_SET_UP)
        if done.returncode == 3:
            return DropCachesResult(error=ERROR_DROP_REFUSED)
        if done.returncode != 0:
            return DropCachesResult(error=_helper_error(done.returncode))
        return DropCachesResult(before_bytes=before, after_bytes=read_overview().cached)
