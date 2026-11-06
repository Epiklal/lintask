# Lintask

A native Linux system monitor that looks and feels like the Windows Task Manager.
Choose the classic **Windows 10** look or the modern **Windows 11** look, pick a light,
dark or one of nine popular color schemes, and get live processes, detailed
performance graphs, sensors, services, Docker containers, autostart entries and
hardware benchmarks in one PySide6 desktop application. A built-in **server mode**
lets you watch a headless Linux server from your desktop.

On AMD Ryzen, Threadripper and EPYC CPUs Lintask goes further than the Windows Task
Manager: it splits the CPU into its **CCDs** (core complex dies) and shows the
temperature, load, clock and power draw of each one, with the per-thread graphs
grouped by CCD and socket.

Built for Linux desktops running Wayland or X11. The user interface is available in
English and German; it follows your system language and can be switched in the settings.

![Windows 11 design, dark theme, CPU split into its two CCDs](docs/screenshots/win11-dark-cpu-ccds.png)

## Contents

- [CPU and CCD view](#cpu-and-ccd-view)
- [Screenshots](#screenshots)
- [Features at a glance](#features-at-a-glance)
- [What gets installed](#what-gets-installed)
- [Install, run, update, uninstall](#install)
- [Upgrading from WinTaskManager](#upgrading-from-wintaskmanager)
- [Debian package (.deb)](#debian-package-deb)
- [Arch package (PKGBUILD)](#arch-package-pkgbuild)
- [RPM package (Fedora, openSUSE)](#rpm-package-fedora-opensuse)
- [AppImage and tarball (any distribution)](#appimage-and-tarball-any-distribution)
- [Snap](#snap)
- [Why there is no Flatpak](#why-there-is-no-flatpak)
- [Feature guide (every tab)](#feature-guide)
- [Design and color schemes](#design-and-color-schemes)
- [Remote monitoring (server mode)](#remote-monitoring-server-mode)
- [Benchmarks](#benchmarks)
- [Hardware data notes](#hardware-data-notes)
- [Custom styling (QSS)](#custom-styling-qss)
- [Security](#security)
- [Development](#development)

## CPU and CCD view

The CPU page has three graph modes: right-click the graph (or the CPU entry on the
left) → **Change graph to** → *Overall utilization* / *Logical processors* / *CCDs*.
The **Per core** button switches between the first two. The choice is remembered.

| CCDs | Logical processors | Overall utilization |
| --- | --- | --- |
| ![One graph per CCD](docs/screenshots/win11-dark-cpu-ccds.png) | ![One graph per logical processor, grouped by CCD](docs/screenshots/win10-light-cpu-threads.png) | ![One graph for the whole CPU](docs/screenshots/win10-dark-cpu-overall.png) |
| One graph per CCD, titled with its threads (*CCD 1 · CPU 0–7, 16–23*) | One graph per thread, each CCD on rows of its own | The whole CPU in one graph, like on Windows |

- **CCDs are found automatically** from the CPUs that share an L3 cache (on Zen 2,
  with two L3 caches per CCD, both are merged into one CCD). No setup and no root
  rights are needed for the graphs.
- **One line per CCD** below the graph: `CCD 1: 55 °C · 39% · 4.52 GHz` – the
  temperature of that die (`Tccd` from the `k10temp` driver), its load and its
  average clock. After **Set up hardware data with sudo** in the settings the line
  also shows the **power draw of each CCD** (`· 21.3 W`), read from the energy
  counter of every core.
- **Clear borders**: in the *Logical processors* grid a slightly thicker line
  (2 px) separates the CCDs and a thick line (4 px) separates the sockets. Hover a
  graph to see where it belongs (*CPU 17 · CCD 2*).
- **Any size**: up to 2 CCDs are shown in one column, up to 8 in two, more in four.
  Boards with several CPUs name every die by socket (*Socket 2 · CCD 3*) and also
  show *Sockets* and the *Highest temperature*.

How the *Logical processors* grid looks on bigger CPUs (example data):

| 2 CCDs | 4 CCDs |
| --- | --- |
| ![Ryzen 9 7950X, 2 CCDs with 8 cores each](docs/screenshots/ccd-grid-1.png) | ![Threadripper 7960X, 4 CCDs with 6 cores each](docs/screenshots/ccd-grid-2.png) |
| Ryzen 9 7950X: 2 CCDs × 8 cores, 32 threads | Threadripper 7960X: 4 CCDs × 6 cores, 48 threads |
| ![Threadripper 7980X, 8 CCDs with 8 cores each](docs/screenshots/ccd-grid-3.png) | ![Two EPYC 9654, 2 sockets with 12 CCDs each](docs/screenshots/ccd-grid-4.png) |
| Threadripper 7980X: 8 CCDs × 8 cores, 128 threads | 2 × EPYC 9654: 2 sockets × 12 CCDs × 8 cores, 384 threads |

On Intel CPUs and on AMD CPUs with a single CCD the *CCDs* mode is not offered, and
the other two modes work as before.

## Screenshots

All screenshots use the English interface; containers, processes and names in them
are example data.

**Performance: every device**

| Windows 11, light | Windows 10, dark |
| --- | --- |
| ![Memory view](docs/screenshots/win11-light-memory.png) | ![GPU view](docs/screenshots/win10-dark-gpu.png) |
| **Memory**: RAM (solid) and swap (dashed) in one graph, with a plain rating of whether memory is tight | **GPU**: selectable engines, dedicated and shared GPU memory, temperature and power |
| ![Network view](docs/screenshots/win11-dark-network.png) | ![Disk view](docs/screenshots/win10-light-disk.png) |
| **Network**: receive (solid) and send (dashed), auto-scaled | **Disk**: active time and transfer rate of every physical disk, model, used space and SMART values (power-on hours, temperature) once hardware data is set up |

**Processes and history**

| Windows 11, light | Windows 10, dark |
| --- | --- |
| ![Process list in the Windows 11 design](docs/screenshots/win11-light-processes.png) | ![Process list in the Windows 10 design](docs/screenshots/win10-dark-processes.png) |
| Process list with heat map, grouped into apps and background processes | The same list in the Windows 10 design |

![History of CPU, memory, disks and network](docs/screenshots/win10-dark-history.png)

**History**: CPU, memory, swap, disks, network, temperatures and GPU, kept for up to a year.

**More tabs**

| | |
| --- | --- |
| ![Sensors](docs/screenshots/win11-dark-sensors.png) | ![Services](docs/screenshots/win10-light-services.png) |
| **Sensors**: every hardware sensor the kernel exposes | **Services**: all systemd services with description and status |
| ![Docker](docs/screenshots/win11-dark-docker.png) | ![Autostart](docs/screenshots/win11-light-autostart.png) |
| **Docker**: containers with live CPU, memory and GPU usage | **Autostart**: user and system autostart entries, enable/disable |
| ![Benchmarks](docs/screenshots/win10-light-benchmarks.png) | ![Settings](docs/screenshots/win11-dark-settings.png) |
| **Benchmarks**: CPU, memory, GPU and disk results | **Settings**: language, design, color scheme, refresh rates, remote server |

**Color schemes**: all 11 schemes in the Windows 11 design:

![All eleven color schemes side by side](docs/screenshots/color-schemes.png)

## Features at a glance

- **Processes** with Windows-style grouping, heat map, overall usage in the column
  headers, search, end task, run new task and drag & drop to start programs.
- **History** of CPU, memory, swap, disks, network, temperatures and GPU, kept for up to a
  year in a small local file. Also shows the history of a server in remote mode.
- **Performance** graphs for CPU (overall, per logical processor or per CCD), memory, every physical disk, network (auto-scaled, send/receive) and every
  GPU (selectable engines, dedicated and shared memory).
- **Memory** under Performance with one graph for RAM and swap and a plain rating of
  whether memory is actually tight. A data view lists everything else: kernel figures,
  swap devices, every module and the module temperatures.
- **CCD view** for AMD Ryzen, Threadripper and EPYC: temperature, load, clock and
  power draw of every CCD, and the per-thread graphs grouped by CCD and socket
  ([details](#cpu-and-ccd-view)).
- **Every GPU is detected**: AMD, NVIDIA and Intel (including Arc), also on systems with
  several GPUs. Multi-socket boards show each CPU separately.
- **Detailed hardware data**: CPU temperature and frequency, RAM speed and module
  temperature, SMART disk data, GPU model, driver, temperature, power and PCIe link.
- **Right-click menus** on every table and on the performance page, as on Windows: the
  actions of the page's buttons plus *Copy* and *Copy all* (pastes into a spreadsheet).
- **Sensors**, **systemd services**, **Docker containers** (start/stop/restart/remove,
  favorites, custom names and pictures) and **autostart entries** (enable/disable).
- **Benchmarks** for CPU, memory, GPU and disk using established Linux tools.
- **Two designs** (Windows 10 / Windows 11) and **11 color schemes**, looking like the
  Windows Task Manager down to hover, selection and buttons.
- **Scales with the screen**: the interface looks the same on 720p, 1080p, 4K or 8K,
  worked out per screen; a fixed size can be set in the settings.
- **Always on top** (also on KDE Plasma Wayland) and a **default start page**; window
  size, position and the CPU view are remembered.
- **Server mode**: monitor a headless machine over the network, protected by an
  access token.
- **Customizable**: refresh rates, column widths and row height are remembered, and
  your own Qt Style Sheet (QSS) rules can override anything.

## What gets installed

This section describes `./install.sh`. With the [Debian package](#debian-package-deb),
the [Arch package](#arch-package-pkgbuild) or the [RPM](#rpm-package-fedora-opensuse)
the package manager installs everything listed here as package dependencies instead;
the [AppImage, tarball and snap](#appimage-and-tarball-any-distribution) bring
Python, PySide6 and psutil along and install nothing system-wide.

`./install.sh` asks for your password once (for the package manager) and then
installs:

**System packages**

| Package | Used for | Required? |
| --- | --- | --- |
| `python3`, `python3-venv`, `python3-pip` | Running the application | Yes |
| Qt runtime libraries (`libxcb-*`, `libxkbcommon-x11-0`, `libegl1`, `libgl1`, `libfontconfig1`, `libdbus-1-3`, ...; named after each distribution) | Needed by Qt to start; a minimal installation has few of them | Yes |
| `fonts-dejavu-core` / `dejavu-sans-fonts` / `ttf-dejavu` | Without any font Qt draws every letter as a box | Yes |
| `smartmontools` | Disk health data (SMART): temperature, power-on hours, lifetime reads/writes | Optional |
| `lm-sensors` | Hardware sensors and temperatures | Optional |
| `dmidecode` | RAM speed and module information | Optional |
| `sysbench` | CPU and memory benchmarks | Optional |
| `fio` | Disk benchmark | Optional |
| `glmark2` | GPU benchmark | Optional |
| `pciutils` | Exact GPU model name (`lspci`) | Optional |

"Optional" means the application runs without it; the related values or
benchmarks are then shown as unavailable. Package names differ slightly between
distributions; the installer picks the right ones. If a distribution does not ship
one of the optional packages, the installer skips it and lists it at the end
instead of aborting.

**Python packages** (only inside the project's own virtual environment, not
system-wide): [`PySide6-Essentials`](https://pypi.org/project/PySide6-Essentials/)
(Qt user interface, about 100 MB download) and
[`psutil`](https://pypi.org/project/psutil/) (process and system data). The
installer needs an internet connection for this download.

**Files created**

| Location | Content |
| --- | --- |
| `<project folder>/.venv/` | Virtual environment with the Python packages |
| `~/.local/share/applications/lintask.desktop` | **Lintask** entry in your application menu |
| `~/.config/Lintask/TaskManager.conf` | Your settings (created on first start, readable only by you) |
| `~/.local/state/Lintask/history.sqlite3` | The recorded history (created on first start, readable only by you) |

Nothing else is changed on your system. The optional **Settings →
Set up hardware data with sudo** button additionally installs a small
helper (`/usr/local/libexec/lintask-smartctl`) and a matching sudo rule
(`/etc/sudoers.d/lintask-smartctl`) so SMART and RAM data can be read
without typing your password every time. (The .deb already ships the helper as
`/usr/libexec/lintask/lintask-smartctl` and the Arch package as
`/usr/lib/lintask/lintask-smartctl`; the button then only adds
the sudo rule and the udev rule.) The helper can only run `smartctl` on
block devices and `dmidecode -t memory`, read the per-core energy counters of AMD CPUs (for the
power draw of each CCD), move the memory of *your own* processes to
swap, and empty the page cache; the last two only happen when you ask for them in the
process list or the memory view. The button also makes the CPU energy counters
(RAPL, `/sys/class/powercap/intel-rapl*:*/energy_uj`, on Intel and AMD) readable
for your user group, right away and on every boot through a udev rule
(`/etc/udev/rules.d/99-lintask-rapl.rules`, works with systemd-udevd and
eudev). Since Linux 5.10 the kernel makes them readable only by root (because of
the PLATYPUS side channel, CVE-2020-8694: programs that can read the counters may be
able to derive secrets from them), so without this the CPU power draw (and on Intel the
iGPU power draw) shows *No read permission*. The unlock applies to every program of
your user group, so skip the setup if you run untrusted code under that group. On NixOS `/etc` is read-only: the
setup unlocks the counters until the next reboot and prints the
`services.udev.extraRules` line to add to `/etc/nixos/configuration.nix`.

The button detects your package manager (apt, dnf, pacman, zypper, apk) and opens
your terminal (e.g. Konsole, GNOME Terminal, Ptyxis, Xfce Terminal, kitty,
Alacritty, foot, xterm) to ask for your password. The sudo rule is checked with
`visudo` *before* it is installed, so a faulty rule can never break `sudo`. If no
terminal is found, the application shows the commands to run yourself. `sudo` must
be installed.

On a server without a desktop, run the same setup manually from the project folder
(after installing `smartmontools` and `dmidecode` with your package manager). With
the .deb or the Arch package, skip the two `install` lines and write the packaged
helper (`/usr/libexec/lintask/lintask-smartctl`, on Arch
`/usr/lib/lintask/lintask-smartctl`) into the sudo rule instead:

```bash
sudo install -d -m 0755 /usr/local/libexec
sudo install -m 0755 scripts/lintask-smartctl /usr/local/libexec/lintask-smartctl
tmp="$(mktemp)"
echo "$USER ALL=(root) NOPASSWD: /usr/local/libexec/lintask-smartctl *" > "$tmp"
sudo visudo -cf "$tmp" && sudo install -m 0440 -o root -g root "$tmp" /etc/sudoers.d/lintask-smartctl
rm -f "$tmp"
# CPU power draw (RAPL) readable for your group, right away:
sudo chgrp "$(id -gn)" /sys/class/powercap/intel-rapl*:*/energy_uj
sudo chmod g+r /sys/class/powercap/intel-rapl*:*/energy_uj
# ... and on every boot (not on NixOS, see above):
echo "ACTION==\"add\", SUBSYSTEM==\"powercap\", KERNEL==\"intel-rapl*:*\", TEST==\"energy_uj\", RUN+=\"$(command -v chgrp) $(id -gn) /sys\$devpath/energy_uj\", RUN+=\"$(command -v chmod) g+r /sys\$devpath/energy_uj\"" | sudo tee /etc/udev/rules.d/99-lintask-rapl.rules
sudo udevadm control --reload
```

**Also used if present** (not installed by the script): `lspci` (package
`pciutils`, preinstalled on most systems) for the exact GPU model name,
`nvidia-smi` for NVIDIA GPUs, the `docker` CLI for the Docker tab and `systemctl`
for the services tab.

### Supported distributions

The [Debian package](#debian-package-deb) runs on Debian 13, Ubuntu 24.04, Linux
Mint 22 and newer. Debian 13 ships PySide6 6.8 as system packages, which the package
uses directly. Ubuntu 24.04 and Linux Mint 22 have no PySide6 packages at all, so
there the package downloads PySide6 from PyPI into `/opt/lintask/venv` while
it is being installed (internet connection needed once). On Arch Linux and its
derivatives (Manjaro, EndeavourOS, CachyOS, ...) the [Arch package](#arch-package-pkgbuild)
uses the distribution's own `pyside6` and `python-psutil` packages, so nothing is
downloaded from PyPI. The [RPM package](#rpm-package-fedora-opensuse) does the same
on Fedora and openSUSE Tumbleweed with `python3-pyside6` and `python3-psutil`. The
[AppImage, the tarball and the snap](#appimage-and-tarball-any-distribution) bring
their own Python, PySide6 and psutil and run on any 64-bit x86 distribution with
glibc 2.35 or newer (Ubuntu 22.04, Debian 12, Fedora 36, openSUSE Leap 15.6 and
everything since). The `./install.sh` installer supports:

| Distribution family | Package manager |
| --- | --- |
| Debian, Ubuntu, Linux Mint | `apt` |
| Fedora | `dnf` |
| Arch Linux | `pacman` |
| openSUSE | `zypper` |
| Alpine Linux | `apk` |

At the end it checks that Qt really loads and stops with the names of any missing
libraries instead of reporting success. On Arch, `pacman` fails on a fresh system
because the package database is outdated, and Arch only supports full upgrades:
in a terminal `./install.sh` then offers `pacman -Syu` and `pacman` asks you to
confirm; without a terminal it stops and tells you to run that yourself.

Any other distribution works too if Python 3 (with `venv` and `pip`) is installed:
the installer then skips the system packages and sets up the application anyway.
Install the optional tools yourself if you want the related data.

Note on PySide6: where the distribution ships a current PySide6 (6.6 or newer) as a
system package together with psutil, the installer uses it and downloads nothing.
On Arch Linux it installs `pyside6` and `python-psutil` with `pacman` for exactly
that purpose; on Debian 13 the `python3-pyside6.*` packages are picked up when they
are already installed. The `.venv` then only passes the system packages through. On
all other systems PySide6 is installed with `pip`, which provides it for glibc-based
systems (practically all distributions) on x86-64 and ARM64. Alpine Linux uses musl,
for which `pip` has no PySide6 build; there you need a PySide6 package from the
distribution, which is untested.

## Install

Every release on the [Releases page](https://github.com/Epiklal/lintask/releases)
has a ready-made package for each of these, plus a `SHA256SUMS` file to check the
downloads (`sha256sum -c --ignore-missing SHA256SUMS`):

| Your system | File | Install with | Details |
| --- | --- | --- | --- |
| Debian 13, Ubuntu 24.04, Linux Mint 22 and newer | `lintask_<version>_all.deb` | `sudo apt install ./lintask_*.deb` | [Debian package](#debian-package-deb) |
| Arch Linux, Manjaro, EndeavourOS, CachyOS | `lintask-<version>-1-any.pkg.tar.zst` | `sudo pacman -U ./lintask-*.pkg.tar.zst` | [Arch package](#arch-package-pkgbuild) |
| Fedora, openSUSE Tumbleweed | `lintask-<version>-1.noarch.rpm` | `sudo dnf install ./lintask-*.rpm` / `sudo zypper install ./lintask-*.rpm` | [RPM package](#rpm-package-fedora-opensuse) |
| Any x86-64 distribution (glibc 2.35+) | `lintask-<version>-x86_64.AppImage` | `chmod +x` and start it, nothing to install | [AppImage](#appimage-and-tarball-any-distribution) |
| Any x86-64 distribution (glibc 2.35+) | `lintask-<version>-linux-x86_64.tar.gz` | unpack and start `./lintask` | [Tarball](#appimage-and-tarball-any-distribution) |
| Any distribution with `snapd` | `lintask_<version>_amd64.snap` | `sudo snap install --dangerous --classic ./lintask_*.snap` | [Snap](#snap) |

The `.deb`, the Arch package and the RPM use the Python and Qt of your distribution,
get the menu entry, the systemd service for the server mode and the hardware helper,
and are updated through the package manager. The AppImage, the tarball and the snap
are self-contained (about 60-70 MB). There is no Flatpak, see
[Why there is no Flatpak](#why-there-is-no-flatpak).

To run from source instead, or on a distribution not listed above, use the
installer script:

```bash
git clone https://github.com/Epiklal/lintask.git
cd lintask
./install.sh
```

`sh install.sh` works as well (for example after downloading the project as a ZIP
file, which drops the executable bit). Run the script as your normal user, **not**
with `sudo`: it asks for your password itself when it installs system packages.
Started with `sudo`, it stops with a hint, because the virtual environment and the
menu entry would otherwise end up in root's home directory. If a step fails, the
script prints that step and the most common causes; fix the cause and simply run
`./install.sh` again.

### Debian package (.deb)

Requirements: Debian 13, Ubuntu 24.04, Linux Mint 22 or newer, 64-bit (x86-64 or
ARM64). On Ubuntu and Linux Mint the first installation also needs an internet
connection (see [How PySide6 is provided](#how-pyside6-is-provided)).

**Download:** the latest `lintask_<version>_all.deb` is on the
[Releases page](https://github.com/Epiklal/lintask/releases).
Download it and either double-click it in your file manager (Linux Mint opens it in
the package installer, which also installs the recommended tools) or install it from
a terminal:

```bash
cd ~/Downloads
sudo apt update
sudo apt install ./lintask_*.deb
```

Run `sudo apt update` first on a freshly installed system: its package lists are
as old as the installation medium, and `apt` then fails with 404 errors for the
dependencies.

Do not use `dpkg -i` directly: it does not install the dependencies. If you did,
`sudo apt install -f` completes the installation.

**Build it yourself** (on any Debian-based system; the build itself needs no
internet connection):

```bash
git clone https://github.com/Epiklal/lintask.git
cd lintask
./build-deb.sh
sudo apt install ./dist/lintask_*.deb
```

`build-deb.sh` only needs `dpkg-deb` (package `dpkg`, part of every Debian-based
system); no `debhelper`, no `venv`, no `pip`. It prints the name of the finished file,
e.g. `dist/lintask_1.2.1+20261106.1200.g21adf5a_all.deb` (the version contains
the build time and the Git commit; pass your own with `./build-deb.sh 1.2.3`). If
`dist/` already holds older builds, install the file the script printed instead of
using the `*` wildcard.

The same `.deb` works on every supported distribution: copy it to any other machine
and install it there with `sudo apt install ./lintask_*.deb`, or open it in
your file manager. `apt` resolves the dependencies itself:

- **Depends** (always installed): `python3`, `python3-venv`, `python3-psutil`,
  `libxcb-cursor0` and the Qt runtime libraries (`libxcb-*`, `libxkbcommon-x11-0`,
  `libgl1`, `libegl1`, `libfontconfig1`, `libdbus-1-3`, ...).
- **Recommends** (installed by default; skip with `--no-install-recommends`):
  `python3-pyside6.qtcore`, `python3-pyside6.qtgui`, `python3-pyside6.qtwidgets` and
  `qt6-svg-plugins` (PySide6 from the distribution, where it exists), the Wayland
  client libraries, and the optional tools from
  [What gets installed](#what-gets-installed): `smartmontools`, `dmidecode`,
  `lm-sensors`, `pciutils`, `sudo`, `sysbench`, `fio`, `glmark2-x11`, `qt6-wayland`.
- **Suggests** (not installed automatically): `docker.io`, `nvidia-smi`.

#### How PySide6 is provided

Right after unpacking, the package checks whether PySide6 6.6 or later can be
imported from the system packages:

- **Debian 13 and newer:** yes - nothing else happens, `/opt/lintask` is not
  created.
- **Ubuntu 24.04, Linux Mint 22:** these distributions ship no PySide6 packages, so
  `apt` silently skips those Recommends. The package then creates a virtual
  environment in `/opt/lintask/venv` and installs `PySide6-Essentials` into it
  with `pip` from pypi.org (about 100 MB, a few minutes on a slow connection;
  `psutil` comes from the system package). Nothing is installed into the system
  Python.

If the download fails (no internet, proxy, pypi.org unreachable), the installation
still finishes, with a warning, so `apt` stays usable. The program can't start until
you fix the cause and run `sudo /usr/libexec/lintask/setup-venv`; no
reinstallation is needed. Until then, the launcher names that command in the terminal
or, when started from the menu, in a dialog. The same applies to
`apt install --no-install-recommends`, which only needs the download to succeed.
The launcher `lintask` uses the virtual environment when it exists and the
system packages otherwise.

The package installs:

| Path | Content |
| --- | --- |
| `/usr/share/lintask/` | The application (`main.py`, `app/`, `pages/`, `widgets/`), byte-compiled on installation |
| `/usr/bin/lintask` | Launcher; `lintask --server` starts the server mode |
| `/usr/share/applications/lintask.desktop` | Menu entry **Lintask** |
| `/usr/libexec/lintask/lintask-smartctl` | Helper for SMART and RAM data, *Move to swap* and emptying the cache; **Set up hardware data with sudo** then only adds the sudo rule and the udev rule |
| `/usr/libexec/lintask/setup-venv` | Sets up PySide6 (system packages or `/opt/lintask/venv`); runs automatically during installation |
| `/opt/lintask/venv/` | Only on Ubuntu/Linux Mint: virtual environment with PySide6 from PyPI; removed together with the package |
| `/usr/lib/systemd/system/lintask-server.service` | systemd service for the server mode, not enabled by default (see [Remote monitoring](#remote-monitoring-server-mode)) |
| `/etc/default/lintask-server` | Options for that service, e.g. the token; readable by root only (mode 600) |
| `/usr/share/doc/lintask/` | This README, changelog and copyright |

Your settings stay in `~/.config/Lintask/TaskManager.conf`, as with the
installer script. If you used `./install.sh` on the same machine before, remove its
menu entry (`rm ~/.local/share/applications/lintask.desktop`) so that the menu
starts the packaged version.

### Arch package (PKGBUILD)

On Arch Linux, Manjaro, EndeavourOS, CachyOS and other `pacman`-based systems,
download the latest `lintask-<version>-1-any.pkg.tar.zst` from the
[Releases page](https://github.com/Epiklal/lintask/releases) and install it;
`pacman` pulls in the dependencies from the official repositories:

```bash
cd ~/Downloads
sudo pacman -U ./lintask-*.pkg.tar.zst
```

**Build it yourself** from the repository with the `PKGBUILD` in `packaging/arch/`
(`makepkg` needs `base-devel` and `git`; `-s` installs the dependencies, `-i`
installs the finished package):

```bash
sudo pacman -S --needed base-devel git
git clone https://github.com/Epiklal/lintask.git
cd lintask/packaging/arch
makepkg -si
```

The package depends on the distribution's own `pyside6` and `python-psutil`
packages; there is no `pip` download and no virtual environment. The optional tools
(`smartmontools`, `dmidecode`, `lm_sensors`, `pciutils`, `sysbench`, `fio`,
`glmark2`, `qt6-wayland`, ...) are listed as optional dependencies when the package
is installed; install the ones you want with `pacman`. The package is not in the
AUR, so updates come from the Releases page or are built the same way (see
[Update](#update)).

The installed layout matches the Debian package, with these differences:

| Path | Content |
| --- | --- |
| `/usr/lib/lintask/lintask-smartctl` | Helper for SMART and RAM data, *Move to swap* and emptying the cache (the .deb uses `/usr/libexec/`); **Set up hardware data with sudo** then only adds the sudo rule and the udev rule |
| `/usr/lib/systemd/system/lintask-server.service` | systemd service for the server mode, not enabled by default |
| `/etc/default/lintask-server` | Options for that service, e.g. the token; readable by root only (mode 600), kept as a `.pacsave` file on removal |
| `/usr/share/licenses/lintask/LICENSE` | Copyright information |

There is no `setup-venv` and no `/opt/lintask/venv`. The `.pkg.tar.zst` file
and the `pkg/` and `src/` directories that `makepkg` creates in `packaging/arch/`
are ignored by git.

### RPM package (Fedora, openSUSE)

On Fedora and openSUSE Tumbleweed, download the latest
`lintask-<version>-1.noarch.rpm` from the
[Releases page](https://github.com/Epiklal/lintask/releases) and install it. The
package manager pulls in PySide6 and psutil from the distribution's repositories:

```bash
cd ~/Downloads
sudo dnf install ./lintask-*.noarch.rpm                          # Fedora
sudo zypper install --allow-unsigned-rpm ./lintask-*.noarch.rpm  # openSUSE
```

The package is not signed, which is why `zypper` needs `--allow-unsigned-rpm`;
check the file against `SHA256SUMS` from the same release instead. `smartmontools`,
`dmidecode`, `lm_sensors`, `pciutils` and `sudo` are installed as weak dependencies
if available; `sysbench`, `fio`, `glmark2` and `docker` are suggested and can be
installed with `dnf`/`zypper` when you want them. Where the repositories have no
PySide6 6.6 or newer (for example openSUSE Leap or RHEL-based systems such as Rocky
and Alma), use the [AppImage](#appimage-and-tarball-any-distribution) instead.

**Build it yourself** with `rpmbuild` (package `rpm-build`), or in a Fedora
container with `--docker`:

```bash
git clone https://github.com/Epiklal/lintask.git
cd lintask
./build-rpm.sh            # or: ./build-rpm.sh --docker
sudo dnf install ./dist/lintask-*.noarch.rpm
```

The installed layout matches the Debian package (helper in
`/usr/libexec/lintask/`, service `lintask-server`, configuration in
`/etc/default/lintask-server` with mode 600). A changed configuration is kept as
`.rpmsave` on removal.

### AppImage and tarball (any distribution)

The AppImage and the tarball contain their own Python 3.12, PySide6 and psutil and
need nothing from the distribution except a desktop (X11 or Wayland) and glibc 2.35
or newer on 64-bit x86. Nothing is installed system-wide.

**AppImage** - one file, download it, make it executable and start it:

```bash
cd ~/Downloads
chmod +x lintask-*-x86_64.AppImage
./lintask-*-x86_64.AppImage
```

If it reports that FUSE is missing (`libfuse.so.2`), either install FUSE
(`fuse2`/`libfuse2`) or let it unpack itself on each start:
`APPIMAGE_EXTRACT_AND_RUN=1 ./lintask-*-x86_64.AppImage`. For a menu entry, use a
tool such as Gear Lever or AppImageLauncher, or copy the AppImage to
`~/Applications/`.

**Tarball** - unpack it anywhere and start `lintask` in the folder:

```bash
tar -xzf lintask-*-linux-x86_64.tar.gz -C ~/.local/opt   # any folder works
~/.local/opt/lintask-*-x86_64/lintask
```

For the command and the menu entry, link the launcher and copy the desktop file
and icon from the folder:

```bash
dir=$(echo ~/.local/opt/lintask-*-x86_64)
ln -sf "$dir/lintask" ~/.local/bin/lintask
cp "$dir/share/applications/lintask.desktop" ~/.local/share/applications/
mkdir -p ~/.local/share/icons/hicolor/scalable/apps
cp "$dir/share/icons/hicolor/scalable/apps/lintask.svg" ~/.local/share/icons/hicolor/scalable/apps/
```

Both work like the installer script: settings are in `~/.config/Lintask/`, and
**Settings → Set up hardware data with sudo** installs the helper to
`/usr/local/libexec/lintask-smartctl`. There is no systemd service; for the
server mode see [Run the server permanently](#4-run-the-server-permanently-systemd).
The optional tools (`smartmontools`, `dmidecode`, `lm-sensors`, `sysbench`, ...)
come from your package manager as usual.

**Build them yourself** with `./build-bundle.sh --docker` (Docker builds in an
Ubuntu 22.04 container, which sets the glibc requirement). It downloads a
standalone Python build and the AppImage tools, checked by SHA-256, and writes the
AppImage, the tarball and the snap to `dist/`.

### Snap

The snap is the same bundle as the tarball. It uses *classic* confinement, because
a task manager has to see all processes, services and devices, and it is not in the
Snap Store, so install the file from the
[Releases page](https://github.com/Epiklal/lintask/releases) with `--dangerous`
(no Store signature) and `--classic`:

```bash
cd ~/Downloads
sudo snap install --dangerous --classic ./lintask_*_amd64.snap
lintask
```

The menu entry is created by `snapd`. Snaps installed from a file are not updated
automatically; install the new file the same way (see [Update](#update)).

### Why there is no Flatpak

A Flatpak runs in its own PID namespace and sandbox. Lintask would only see its own
processes, could not reach `systemctl` for the Services tab, the Docker socket, SMART
data or `sudo`, and could not end or prioritise other programs. Opening the sandbox
far enough for that (`--talk-name=org.freedesktop.Flatpak` and running everything
through `flatpak-spawn --host`) would remove what Flatpak is for and is not accepted
on Flathub. Use the [AppImage](#appimage-and-tarball-any-distribution) instead: it
runs on the same distributions without a sandbox.

## Run

Start **Lintask** from your application menu. The entry sits in the *System*
category (Cinnamon: *Administration* / *System Tools*); typing `task` or
`lintask` into the menu search finds it. From a terminal, with the Debian,
Arch or RPM package or the snap:

```bash
lintask
```

with the AppImage or the tarball:

```bash
./lintask-*-x86_64.AppImage
~/.local/opt/lintask-*-x86_64/lintask     # the folder you unpacked the tarball to
```

or from the project folder when installed with `./install.sh`:

```bash
./run.sh
```

If Qt needs an explicitly selected display backend:

```bash
QT_QPA_PLATFORM=wayland ./run.sh      # or: QT_QPA_PLATFORM=wayland lintask
QT_QPA_PLATFORM=xcb ./run.sh          # or: QT_QPA_PLATFORM=xcb lintask
```

## Update

Debian package - download the new `.deb` from the
[Releases page](https://github.com/Epiklal/lintask/releases)
and install it over the old one with `sudo apt install ./lintask_*.deb`, or
build it yourself (if `dist/` holds older builds too, install the file name the
script prints):

```bash
cd lintask
git pull
./build-deb.sh
sudo apt install ./dist/lintask_*.deb
```

An existing `/opt/lintask/venv` with a current PySide6 is kept, so an update
normally needs no download.

Arch package - download the new `.pkg.tar.zst` from the Releases page and install it
with `sudo pacman -U ./lintask-*.pkg.tar.zst`, or pull the new sources and build the
package again (raise `pkgrel` in
the `PKGBUILD` if the version number has not changed, otherwise `pacman` reports the
same version):

```bash
cd lintask
git pull
cd packaging/arch
makepkg -si
```

RPM package - download the new `.rpm` and install it over the old one:

```bash
sudo dnf install ./lintask-*.noarch.rpm                          # Fedora
sudo zypper install --allow-unsigned-rpm ./lintask-*.noarch.rpm  # openSUSE
```

AppImage - download the new file, make it executable and delete the old one.
Tarball - unpack the new archive and delete the old folder (update the
`~/.local/bin/lintask` link if you created one). Snap - install the new file the
same way as the first time:

```bash
sudo snap install --dangerous --classic ./lintask_*_amd64.snap
```

Installer script:

```bash
cd lintask
git pull
./install.sh
```

Your settings are kept in all cases.

## Upgrading from WinTaskManager

Lintask was called WinTaskManager before. On the first start, your settings move from
`~/.config/WinTaskManager/` to `~/.config/Lintask/`, including the server token. The
command `wintaskmanager` keeps working as a link to `lintask`.

Debian package - the new package replaces the old one:

```bash
sudo apt install ./lintask_*.deb
sudo apt purge wintaskmanager      # clears what dpkg still remembers of the old package
```

`/etc/default/wintaskmanager-server`, systemd drop-ins, the sudo rule and the RAPL udev
rule are taken over, and a server that was enabled stays enabled. On Ubuntu and Linux
Mint, PySide6 is downloaded again, because removing the old package deletes
`/opt/wintaskmanager`.

Arch package - `makepkg -si` replaces the old package. Its removal disables the server
and deletes the sudo rule and the RAPL udev rule, so afterwards:

```bash
sudo systemctl enable --now lintask-server.service   # only if you use the server
```

and run **Settings → Set up hardware data with sudo** again. A changed
`/etc/default/wintaskmanager-server` is taken over from its `.pacsave` file.

Installer script - `git pull` and `./install.sh` as usual; the old menu entry is removed.
SMART and RAM data keep working with the old helper; the next run of **Set up hardware
data with sudo** replaces it and its sudo rule.

## Uninstall

Debian package:

```bash
sudo apt purge lintask     # or "apt remove" to keep /etc/default/lintask-server
sudo apt autoremove        # drops the recommended tools if nothing else needs them
rm -r ~/.config/Lintask    # optional: your settings
rm -r ~/.local/state/Lintask   # optional: your history
```

Both `remove` and `purge` delete `/opt/lintask` (the PySide6 virtual
environment on Ubuntu/Linux Mint). `purge` also removes the server configuration, the history the
service recorded, the sudo rule for the packaged helper and the RAPL udev rule; the service is stopped and
disabled automatically.

Arch package:

```bash
sudo pacman -R lintask     # or "pacman -Rs" to drop unneeded dependencies too
rm -r ~/.config/Lintask    # optional: your settings
rm -r ~/.local/state/Lintask   # optional: your history
sudo rm -r /var/lib/private/lintask   # optional: the history the service recorded
```

This also stops and disables the service and removes the sudo rule for the packaged
helper and the RAPL udev rule. The server configuration is kept as
`/etc/default/lintask-server.pacsave` if you changed it.

RPM package:

```bash
sudo dnf remove lintask        # Fedora
sudo zypper remove lintask     # openSUSE
rm -r ~/.config/Lintask ~/.local/state/Lintask   # optional: settings and history
```

Like the Arch package, this stops and disables the service and removes the sudo rule
for the packaged helper and the RAPL udev rule; a changed server configuration is
kept as `/etc/default/lintask-server.rpmsave`.

AppImage, tarball and snap:

```bash
rm lintask-*-x86_64.AppImage                  # AppImage: just delete the file
rm -r ~/.local/opt/lintask-*-x86_64 ~/.local/bin/lintask \
      ~/.local/share/applications/lintask.desktop   # tarball, with the menu entry
sudo snap remove lintask                      # snap
rm -r ~/.config/Lintask ~/.local/state/Lintask   # optional: settings and history
```

Installer script:

```bash
rm ~/.local/share/applications/lintask.desktop
rm -r ~/.config/Lintask ~/.local/state/Lintask
rm -r lintask      # the project folder, including .venv
```

If you used **Set up hardware data with sudo** with the installer script, the
AppImage, the tarball or the snap, also remove the helper, its sudo rule and the
RAPL udev rule (with the .deb, the Arch package or the RPM the helper belongs to the
package and is removed with it):

```bash
sudo rm /etc/sudoers.d/lintask-smartctl /usr/local/libexec/lintask-smartctl
sudo rm /etc/udev/rules.d/99-lintask-rapl.rules
```

If you set up the server as a systemd service (see below), stop and remove it too:

```bash
sudo systemctl disable --now lintask-server
sudo rm /etc/systemd/system/lintask-server.service
sudo rm -r /var/lib/private/lintask   # the history the service recorded
```

The system packages from the table above stay installed; remove them with your
package manager if you no longer need them.

## Feature guide

The tab and button names are the English ones; the German interface shows *Prozesse*,
*Verlauf*, *Leistung*, *Sensoren*, *Dienste* and *Einstellungen* instead.

### Processes

- **Columns**: Name, Status, CPU, RAM, Swap, GPU, GPU memory, PID, User,
  Threads. Above CPU, RAM, swap, GPU and GPU memory
  the header shows the overall usage, e.g. `7%` above *CPU*.
- **Heat map**: the busier a process, the stronger its cells are colored (yellow in
  the Windows 10 design, blue in Windows 11, scheme colors otherwise).
- **Grouping**: sorted by name (the default), processes are split into *Apps* (your
  own processes) and *Background processes*. Processes with the
  same name are combined into one group, e.g. `bash (18)`, with summed values.
  Click the arrow to expand or collapse a group.
- **Sorting**: click a column header; click again to reverse.
- **Search**: filter by process name.
- **End task**: select a process and click the button (Windows 10:
  bottom right, Windows 11: page header). You are asked for confirmation; the process
  first gets a normal terminate signal and is killed only if it does not exit within
  two seconds.
- **Move to swap** (right-click a process or group): asks first; the program keeps running,
  but its memory moves to swap and it reacts slowly the next time it is used. This needs
  swap and the setup under **Settings → Set up hardware data with sudo**. Only your own
  processes are touched, and processes that protect their memory are left alone. Programs
  of other users, Lintask itself and programs the desktop needs cannot be moved. The amount
  shown is what reached swap; memory shared with other programs stays in RAM, and
  *available* may not rise until the system needs the space.
- **Run new task**: enter a command, e.g. `firefox` or
  `gnome-terminal --working-directory=/tmp` (Windows 10: menu *File*, Windows 11:
  page header).
- **Start file** (menu *File*): choose an executable file to start.
- **Drag & drop**: drop executable files from your file manager onto the list to
  start them.
- Program icons come from your desktop icon theme.

### History

Shows how the computer was doing, from the last hour up to the last year: CPU, memory and
swap, how full the root file system is, disk and network throughput, temperatures and
GPU. Recording starts with Lintask and can be switched off with *Record this computer's
history*; **Delete history** removes everything recorded so far.

Lintask takes one sample every 10 seconds and thins the data out as it gets older:

| Age | One value per |
|---|---|
| Up to 24 hours | 10 seconds |
| Up to 30 days | 5 minutes |
| Up to 1 year | 1 hour |

Coarser values keep both the average (the line) and the peak (the band around it), so a
short load is still visible a month later. Only totals are stored, no process names or
command lines. The file stays around 8 to 12 MB (measured with a full year of data) at
`~/.local/state/Lintask/history.sqlite3`.

What to keep in mind:

- Lintask records only while it runs. Time it wasn't running stays empty and shows as a
  gap, never as a line across it.
- Anything shorter than 10 seconds is smoothed out; the graphs of the **Performance** tab
  are the place to watch short spikes.
- The views that use 5-minute or hourly values end at the last finished one, so the
  newest few minutes appear there a little later.

In remote mode the tab shows the server's history, read from the server's own file. The
service records to `/var/lib/lintask/history.sqlite3`; start the server with `--no-history`
to turn that off.

### Performance

The left column shows a small live graph for every device; click one to see details.

- **CPU**: utilization graph for the last 60 seconds. Right-click the graph →
  **Change graph to** → *Overall utilization* / *Logical processors* / *CCDs* switches
  between one graph for the whole CPU, one per logical processor and one per CCD
  (*CCDs* only on CPUs with several); **Per core** toggles the first two. The choice is
  remembered. With few threads and one CCD the grid is laid out like
  on Windows; on CPUs with several CCDs each CCD fills rows of its own, separated by a
  thicker line (and sockets by a thick one). Below: utilization, speed, temperature,
  processes, uptime, cores, logical processors and power draw (if the kernel provides
  it), and on CPUs with several CCDs one line per CCD with its temperature, load, clock
  and (after the hardware data setup) power draw. Boards with several CPUs also show
  *Sockets* and the *Highest temperature*, and list each CPU separately. See
  [CPU and CCD view](#cpu-and-ccd-view).
- **Memory**: RAM as a solid line and swap as a dashed line in one graph, like receive
  and send under Network. Which program holds how much is in the
  [Processes](#processes) tab, in the *RAM* and *Swap* columns.
  - **Values below the graph**: memory in use, available now, cache, swap and memory
    pressure, with a plain rating of whether memory is actually tight. Cache is not
    counted as used, because Linux gives it back on its own as soon as programs need it.
    Memory pressure stays *Unknown* on a kernel without `/proc/pressure/memory`.
  - **Data view**: kernel figures, swap devices, every memory module with speed and
    temperature.
  - **Emptying the cache** is off unless you tick *Offer to empty the cache*, and it
    warns you before it runs. It rarely helps: programs and files load more slowly until
    the cache has filled up again. It needs the setup under **Settings → Set up hardware
    data with sudo**.
- **Disk** (one entry per physical disk): active time; read and write speed,
  lifetime reads/writes, power cycles, power-on hours, used/total space and
  temperature (SMART values see [Hardware data notes](#hardware-data-notes)).
- **Network**: receive (solid line) and send (dashed line). The graph
  scales automatically (shown top right, e.g. `10,0 MBit/s`). Also: adapter, link
  speed, IPv4 address and totals since boot.
- **GPU** (one entry per GPU; AMD, NVIDIA and Intel including Arc):
  - four engine graphs. Click an engine name (e.g. **3D ▾**) to choose what the
    graph shows (3D, copy, video decode, video encode, compute, memory controller,
    PCIe receive/send, ... depending on the driver).
  - right-click a GPU graph for **Show graph as** (choose the metric) and
    **Number of graphs** (show 1 to 10 engine graphs).
  - graphs for dedicated and shared GPU memory.
  - details: utilization, dedicated/shared/total GPU memory, GPU temperature,
    driver, driver version, physical location (PCI bus), PCIe generation and width,
    link status and power draw.
- **Copy**: right-click a device on the left and choose **Copy** to copy its values and
  details as plain text.

### Sensors

Every hardware sensor the Linux kernel exposes (`/sys/class/hwmon`, no root
needed): temperatures, fan speeds, voltages, power and more, with category, value,
unit and source. Refreshes automatically; click a column header to sort.

### Services

All systemd services with description and status (read-only), with search and
**Refresh**. Requires `systemctl`; without it the tab only shows a
short note.

### Docker

All containers (running and stopped) with image, status, CPU %, memory, memory
limit, memory %, GPU % and GPU memory, colored with the same heat map as the process
list. Search by name.

- **Start / Stop / Restart / Remove**: start, stop, restart or remove the
  selected container (removing asks for confirmation).
- **★ Favorite**, **Choose image...** (custom picture) and **Rename...** (custom
  display name) make containers easier to find. These are stored only in your
  settings; the real container is not renamed.

Requires the `docker` CLI and permission to use it (e.g. membership in the `docker`
group).

### Autostart

All XDG autostart entries of your user (`~/.config/autostart`) and of the system
(`/etc/xdg/autostart`) with command, source and status, plus search and refresh.
**Enable/Disable** toggles the selected entry. System entries are never
edited directly: a personal override copy is created in `~/.config/autostart`, as
the XDG specification intends.

### Benchmarks

Choose the tests, set the options and click **Start selected**. See [Benchmarks](#benchmarks) for details. The application stays
responsive while a benchmark runs.

### Settings

- **Appearance**: language (*System default*, *Deutsch*, *English*), design
  (Windows 10 / Windows 11), color scheme and **UI size**. *System default* uses your
  locale and falls back to English; language, design and color scheme apply
  immediately. **UI size** is *Automatic (screen resolution)* by default (see
  [Design and color schemes](#design-and-color-schemes)) or a fixed 75 % to 400 %; it
  takes effect after Lintask is restarted.
- **Window management**: *Always on top* and the *Default start page* (the tab Lintask
  opens with).
- **Refresh rate**: refresh rate of the process list (200-5000 ms)
  and of the performance graphs (100-5000 ms).
- **Remote server**: connect to a machine running in server mode.
- **Hardware data (SMART, memory, CPU power)**: one-time setup for SMART and RAM
  data (see [What gets installed](#what-gets-installed)).
- **Custom style (QSS)**: your own style rules (see [Custom styling](#custom-styling-qss)).

### Menus (Windows 10 design)

- **File**: Run new task, Start file..., Exit.
- **Options**: Always on top (works on X11 and on KDE Plasma, Wayland included; some
  other Wayland compositors ignore it) and **Set default tab**.
- **View**: Style and Color scheme.

The Windows 11 design has no menu bar, just like the original: the commands are in
the page headers, the options in **Settings**.

### Mouse and keyboard tips

- **Ctrl + mouse wheel** over a table makes all rows taller or shorter; the height
  is remembered per table.
- Drag the border between two column headers to resize a column; widths are
  remembered.
- **Right-click** works everywhere, see [Right-click menus](#right-click-menus).
- Window size and position are remembered. Pages scroll when the window is small, so it
  can be made as small as you like.

### Right-click menus

Right-click a row in any table (Processes, Services, Autostart, Docker, Sensors,
Benchmarks, History) and the row is selected first, then a menu shows:

- the same actions as the page's buttons, enabled or disabled just like them. Choosing
  one does exactly what the button does, confirmations included. The process list also
  offers **Move to swap** there.
- **Copy** (the selected rows) and **Copy all** (every row, with the column headers).
  Both copy tab-separated text that pastes cleanly into a spreadsheet; hidden columns
  are left out.

On the **Performance** page right-click a device on the left to copy its values and
details as plain text; on the CPU entry and the CPU graph the menu also switches between
overall utilization, logical processors and CCDs.

## Design and color schemes

Open **Settings → Appearance**:

- **Design**: *Windows 10* (tabs, menu bar, footer) or *Windows 11* (navigation pane
  with icons, page headers, rounded controls, no menu bar or status bar).
- **Color scheme**: Light (default), Dark, Nord, Dracula, Catppuccin
  Mocha, Catppuccin Latte, Gruvbox Dark, Tokyo Night, One Dark, Solarized Dark or
  Solarized Light.

Every color scheme works with both designs and also changes the graph colors and
the heat map. In the Windows 10 design both options are also in the menu under
**View**. Changes apply immediately.

**UI size**: Lintask scales its interface with the screen, so it looks the same on a
720p laptop as on a 4K or 8K monitor. The reference is 1080p and the shorter side of the
screen counts (720p → 75 %, 1440p → 125 %, 4K → 200 %, 8K → 400 %, in steps of 25 %).
With several monitors every screen gets its own factor. Scaling you already set for your
desktop is taken into account, and `QT_SCALE_FACTOR` or `QT_SCREEN_SCALE_FACTORS`
exported by yourself always win. Pick a fixed size under **Settings → Appearance → UI
size** if you prefer; it takes effect after a restart.

## Remote monitoring (server mode)

The same program can run **headless on a server** (no desktop needed) and send its
data to the desktop application on another computer. This is useful for a home
server, NAS or VM.

### 1. Install on the server

Install exactly as on the desktop: on Debian/Ubuntu/Mint download the `.deb` from
the [Releases page](https://github.com/Epiklal/lintask/releases)
(or build it on any machine with `./build-deb.sh`), copy it to the server and run
`sudo apt install ./lintask_*.deb`; on Arch install the `.pkg.tar.zst` with
`sudo pacman -U` (or build it with `cd packaging/arch && makepkg -si`); on Fedora and
openSUSE install the `.rpm`; on any other x86-64 distribution copy the AppImage or
the tarball to the server, or clone the repository and run `./install.sh`. No
desktop environment is needed, but PySide6 is: the server mode uses the same
data-collection code as the desktop application, so the Qt packages (or the virtual
environment) are required even on a headless server. The AppImage and the tarball
bring them along.

### 2. Start the server

```bash
lintask --server                      # Debian, Arch or RPM package, snap
./lintask-*-x86_64.AppImage --server  # AppImage
./lintask-*-x86_64/lintask --server   # tarball
./run.sh --server                     # installer script, from the project folder
```

Example output:

```text
Lintask server running on http://192.168.1.20:8765
Access token: 3f1Vw0...kQ
Press Ctrl+C to quit
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--host ADDRESS` | `0.0.0.0` (all network interfaces) | Address to listen on; use `127.0.0.1` for local/SSH-tunnel access only |
| `--port PORT` | `8765` | TCP port |
| `--token TOKEN` | *random* | Use your own access token instead of a random one. Visible to all users in the process list, so prefer the environment variable `LINTASK_SERVER_TOKEN` |
| `--generate-token` | *(default behavior)* | Generate a random token; kept for compatibility |
| `--no-history` | off | Don't record a history (the service records to `/var/lib/lintask/history.sqlite3`) |
| `--no-auth` | off | Start **without** a token. Anyone who can reach the port can read all data and start benchmarks - only for trusted networks |

Without a token of your own, a **new random token is generated on every start**. For a server
that runs permanently, use a fixed token (see step 4).

If a firewall is active, open the port, e.g. `sudo ufw allow 8765/tcp`.

### 3. Connect from the desktop

Open **Settings → Remote server**, enable **Use data from the server**,
enter the server IP, port and access token, and click **Apply server
connection**. The token is stored in your settings file, which only you can read.

While connected, these tabs show the **server's** data: Processes, Performance,
Sensors, Services, Docker and Autostart. Benchmarks started on the Benchmarks tab
run **on the server**. Disable the checkbox to go back to local data.

In remote mode the application is **read-only**: *End task*, the actions in the
memory view, autostart changes and Docker start/stop/restart/remove are disabled, because
they would act on your local machine rather than on the server. Local-only things such as Docker favorites,
names and pictures still work.

### 4. Run the server permanently (systemd)

Create a fixed token once:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

**Debian, Arch or RPM package:** the service `lintask-server` is already installed
but not enabled. Put the token into `/etc/default/lintask-server` (readable by root
only) and enable the service:

```bash
sudoedit /etc/default/lintask-server     # LINTASK_SERVER_TOKEN=YOUR_TOKEN
sudo systemctl enable --now lintask-server
systemctl status lintask-server
```

Without a token in that file, a new one is generated on every start and written to
the journal (`journalctl -u lintask-server`). The service runs as a dynamic
system user, which is enough for processes, CPU, memory, disks, network and sensors.
For SMART and RAM details (sudo helper), the Docker tab and the disk benchmark, run it
as a real user instead:

```bash
sudo systemctl edit lintask-server
```

```ini
[Service]
DynamicUser=no
User=youruser
```

then restart it with `sudo systemctl restart lintask-server` and set up the
helper and sudo rule for that user (see the end of this section).

**Installer script:** create `/etc/systemd/system/lintask-server.service`
(adjust the path and user):

```ini
[Unit]
Description=Lintask monitoring server
After=network-online.target
Wants=network-online.target

[Service]
User=youruser
EnvironmentFile=/etc/default/lintask-server
ExecStart=/home/youruser/lintask/run.sh --server
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Unit files are readable by every user, so the token goes into a file of its own that
only root can read. Enter `LINTASK_SERVER_TOKEN=YOUR_TOKEN` there and start the service:

```bash
sudo install -m 0600 /dev/null /etc/default/lintask-server
sudoedit /etc/default/lintask-server
sudo systemctl daemon-reload
sudo systemctl enable --now lintask-server
```

For SMART and RAM details on the server, set up the helper and sudo rule once with
the manual commands in [What gets installed](#what-gets-installed) (run them as the
user that runs the server).

### Limits for remote benchmarks

To protect the server, benchmark requests are limited: at most 300 seconds, at most
one thread per CPU core, only one benchmark at a time, and the disk test only runs on
a mount point of one of the server's physical disks.

### API (for your own scripts)

All requests need the header `Authorization: Bearer <token>` (unless `--no-auth`).

```bash
# Full snapshot as JSON
curl -H "Authorization: Bearer $TOKEN" http://SERVER:8765/api/v1/snapshot

# History of the last 24 hours (60 to 31536000 seconds)
curl -H "Authorization: Bearer $TOKEN" "http://SERVER:8765/api/v1/history?seconds=86400"

# Run a benchmark ("cpu", "memory", "gpu" or "disk")
curl -H "Authorization: Bearer $TOKEN" \
     -d '{"kind": "cpu", "cpu_threads": 4, "cpu_seconds": 10}' \
     http://SERVER:8765/api/v1/benchmark
```

The snapshot contains `version`, `timestamp`, `hostname`, `system` (CPU, memory,
network, uptime), `cpu_model`, `gpu`, `processes`, `sensors`, `services`, `docker`,
`docker_error`, `autostart` and `disks`.

The history contains `seconds`, `step` (seconds per row), `now`, `columns` and `rows`, at
most about 720 rows, oldest first. Each row starts with the time, followed by the average
and the peak of each value (`cpu_avg`, `cpu_max`, ...). Rows without data are left out and
values that weren't available are `null`.

Error answers: `401` wrong or missing token, `409` a benchmark is already running, `413`
request too large, `400` invalid request, `503` this server records no history.

## Benchmarks

The **Benchmarks** tab uses established Linux tools instead of custom benchmark
loops:

| Area | Tool | Result |
| --- | --- | --- |
| CPU | `sysbench` | Events per second |
| Memory | `sysbench` | Memory throughput in MiB/s |
| GPU | `glmark2` | Offscreen `refract` scene score |
| Disk | `fio` | Sequential read throughput in MiB/s |

Options: number of CPU threads (1 up to your number of logical processors), CPU test
duration (5-300 seconds), prime limit, and the target filesystem for the disk test.
The disk test uses a temporary 256 MiB file in the selected mounted filesystem and
removes it afterwards. If you may not write to the mount point itself (e.g. `/`),
the file goes into a writable folder on the same disk, such as `~/.cache` or
`/var/tmp`. It does not overwrite existing files or benchmark a raw block
device.

Benchmark results vary with power profiles, cooling, background load, drivers, and
the selected filesystem. Compare runs made under similar conditions.

## Hardware data notes

Hardware reporting is best-effort because Linux drivers and individual devices
expose different data. Unavailable values are shown as *Not available* rather
than guessed.

- **SMART** values require a drive and connection adapter that forward SMART
  commands. Some USB enclosures do not expose all lifetime counters. Most values
  need root rights; use **Set up hardware data with sudo** once (or the manual
  commands in [What gets installed](#what-gets-installed)).
- **RAM speed and module temperature** need `dmidecode` (root, via the same helper)
  and a board that reports them.
- **CPU power draw** appears only when the kernel exposes a compatible energy or
  power sensor: RAPL (Intel since Sandy Bridge, AMD Zen; also the MMIO/TPMI
  variants) or, as a fallback, Zenpower. All CPU packages are added up; the
  whole-platform `psys` zone is skipped so nothing is counted twice. RAPL is
  root-only since Linux 5.10; **Set up hardware data with sudo** makes it
  readable for your user group. In a virtual machine there is usually no sensor.
- **CCDs** are read from the CPU topology (CPUs that share an L3 cache) and need no
  setup. The CCD temperature (`Tccd1`, `Tccd2`, …) comes from the `k10temp` driver;
  older Zen CPUs and some mobile chips do not report it, then only load and clock are
  shown. The **power draw per CCD** is added up from the energy counter of every core
  (AMD only, MSR `0xC001029A`), which only root can read, so it appears after
  **Set up hardware data with sudo**; the helper then streams one sample a second
  through a single sudo call. In a virtual machine there is usually no counter.
- **GPU** metrics use `nvidia-smi` for NVIDIA hardware and the Linux DRM/sysfs
  interface for AMD, Intel, and Nouveau drivers. Which engines are available depends
  on the driver. AMD model names come from libdrm's `amdgpu.ids` (device ID and
  revision), with a copy in the package for systems whose list is too old; other
  cards use `lspci`. Intel integrated graphics
  have no own power sensor; their draw comes from the RAPL `uncore` zone (needs the
  same setup as the CPU) and their utilization from the busiest engine. Old NVIDIA
  cards (e.g. Fermi) report many values as *Not Supported* in `nvidia-smi`; those
  fields stay empty. With the Nouveau driver `nvidia-smi` is not used.
- **Per-process GPU usage** comes from `nvidia-smi` on NVIDIA and otherwise from the
  kernel's DRM fdinfo interface (amdgpu, i915, xe, nouveau).

## Custom styling (QSS)

**Settings → Custom style (QSS)** accepts Qt Style Sheet rules. Pick a
template (whole application, tab bar, buttons, tables, performance tiles, charts)
and click **Insert template**, edit it and click **Apply style**. Your rules are
stored per user and applied on top of the selected design and color scheme.

For example, this changes the chart colors:

```css
LiveChart {
    qproperty-lineColor: #ff8c00;
    qproperty-backgroundColor: #151515;
    qproperty-gridColor: #454545;
}
```

**Reset style** removes all custom rules.

## Security

- The settings file (including the server token) is readable only by your user.
- The history file is readable only by its owner and holds system totals, no process
  names. On a server, anyone with the token can read it through the API.
- The server always requires an access token unless started with `--no-auth`;
  tokens are compared in constant time.
- Remote mode never runs actions on your local machine for data that comes from the
  server.
- Autostart changes only ever touch `.desktop` files in the XDG autostart folders.
- The optional SMART helper runs as root through sudo. It ignores the caller's
  environment and validates its arguments. It can read SMART and memory data, move the
  memory of your own processes to swap, and empty the page cache.
- A token of your own belongs into `LINTASK_SERVER_TOKEN`: `--token` is visible to all
  users in the process list. A token you chose is not printed at startup.
- The client sends the token only to the server you entered: it ignores proxies and
  does not follow redirects.
- The server connection uses plain HTTP, so the data and the token can be read on the
  network path; the server warns about this at startup unless it only listens on
  loopback. On networks you do not trust, start the
  server with `--host 127.0.0.1` and connect through an SSH tunnel, then use
  `127.0.0.1` as the server IP in the settings:

  ```bash
  ssh -L 8765:localhost:8765 user@server
  ```

## Development

```bash
./install.sh
source .venv/bin/activate
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -t .
```

Project layout:

| Path | Content |
| --- | --- |
| `main.py` | Entry point (desktop application or `--server`) |
| `app/main_window.py` | Main window, menus, Windows 10 / 11 stylesheets |
| `app/themes.py` | Color schemes; a new scheme only needs a few base colors plus five chart colors |
| `app/system_info.py` | All data collection (processes, hardware, disks, GPU, Docker, autostart) |
| `app/remote_server.py`, `app/remote_client.py` | Server mode and its client |
| `app/history.py` | History: SQLite store, sampling and recording, free of Qt |
| `app/memory_info.py` | Memory rating and the data view of the memory page |
| `app/hardware_setup.py` | The *Set up hardware data with sudo* setup (helper, sudo and udev rules) |
| `app/ui_scale.py` | UI scaling by screen resolution |
| `app/window_on_top.py` | Always on top, including KDE Plasma Wayland (KWin scripting over D-Bus) |
| `app/i18n.py`, `app/translations_de.py` | Translations |
| `app/settings.py` | Persisted settings |
| `pages/` | One module per tab |
| `widgets/` | Graphs, history chart, performance tiles, Windows 11 navigation pane, tables, right-click menus (`widgets/table_menu.py`) |
| `build-deb.sh`, `packaging/debian/` | Debian package: build script, control file, maintainer scripts, launcher, PySide6 setup, systemd unit |
| `packaging/arch/` | Arch package: `PKGBUILD`, launcher, `.install` script with the pacman hooks (`cd packaging/arch && makepkg -si`) |
| `build-rpm.sh`, `packaging/rpm/` | RPM package for Fedora and openSUSE: build script and `lintask.spec` (`--docker` builds in a Fedora container) |
| `build-bundle.sh`, `packaging/icons/` | Self-contained AppImage, tarball and snap with their own Python, PySide6 and psutil (`--docker` builds in Ubuntu 22.04); the application icon |
| `packaging/test-rpm.sh`, `packaging/test-bundle.sh` | Smoke tests for the RPM and the bundles: install or unpack, start headless, run the unit tests, remove |
| `.github/workflows/build-packages.yml` | GitHub Actions: builds every package, tests it on the distributions it is meant for and attaches all of them to a GitHub Release for `v*` tags |

Generated local files are excluded through `.gitignore`, including `.venv`, Python
bytecode, test caches and the package build directories `build/`, `dist/` and
`packaging/arch/{pkg,src}` together with the built `*.pkg.tar.*` files. User
preferences are stored outside the repository in the current user's Qt settings
directory.

### Releasing a new version

Push a tag that starts with `v`. GitHub Actions then builds every package with the
tag as version and tests it before anything is published:

| Package | Built with | Tested on |
| --- | --- | --- |
| `.deb` | `./build-deb.sh <version>` | Ubuntu (install, start, unit tests, purge) |
| `.pkg.tar.zst` | `makepkg` in `archlinux:latest` | Arch Linux (install, start, unit tests, remove) |
| `.rpm` | `./build-rpm.sh --docker <version>` | Fedora and openSUSE Tumbleweed |
| AppImage, `.tar.gz` | `./build-bundle.sh --docker <version>` | Debian 13, Fedora, Arch Linux, openSUSE Tumbleweed |
| `.snap` | `./build-bundle.sh --docker <version>` | Ubuntu (`snap install --classic`, start, remove) |

When all of them pass, the release job publishes a GitHub Release with every
package and a `SHA256SUMS` file attached:

```bash
git tag v1.2.1
git push origin v1.2.1
```

Every push to `main` and every manual run (**Actions** tab → *Build packages* →
*Run workflow*) builds and tests the packages as well, but only stores them as
workflow artifacts instead of creating a release.

## Contributing

Issues and pull requests are welcome. Keep changes focused, preserve the
non-blocking UI behavior, and include a focused test when adding or changing a
feature.
