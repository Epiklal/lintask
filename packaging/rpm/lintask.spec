# RPM package for Lintask (Fedora, openSUSE and other RPM distributions).
# Built by build-rpm.sh, which packs the checkout into Source0:
#     ./build-rpm.sh [VERSION]
#     sudo dnf install ./dist/lintask-*.noarch.rpm      (Fedora)
#     sudo zypper install ./dist/lintask-*.noarch.rpm   (openSUSE)
# PySide6 and psutil come as system packages, so no venv is needed.

%{!?pkg_version: %global pkg_version 1.1.3}

Name:           lintask
Version:        %{pkg_version}
Release:        1%{?dist}
Summary:        Task manager for Linux: processes, performance, services, benchmarks
# The project has no license file yet (see packaging/debian/copyright).
License:        LicenseRef-Unspecified
URL:            https://github.com/Epiklal/lintask
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3
Requires:       python3 >= 3.9
Requires:       python3dist(pyside6) >= 6.6
Requires:       python3dist(psutil)
# SMART values, memory modules, temperatures, GPU detection, the sudo rule.
Recommends:     smartmontools
Recommends:     dmidecode
Recommends:     (lm_sensors or sensors)
Recommends:     pciutils
Recommends:     sudo
# Benchmarks and the container overview.
Suggests:       sysbench
Suggests:       fio
Suggests:       glmark2
Suggests:       docker

%description
Lintask is a task manager for Linux in the style of the Windows Task Manager:
processes, performance graphs for CPU, memory, disks, network and GPUs,
services, autostart, Docker containers, sensors, benchmarks, a history and
remote monitoring of other machines through a small HTTP server.

%prep
%autosetup -n %{name}-%{version}

%build
# Nothing to build, the bytecode is created in %%install.

%install
share=%{buildroot}%{_datadir}/%{name}
install -d "$share"
cp -p main.py "$share/"
cp -rp app pages widgets "$share/"
find "$share" \( -name __pycache__ -o -name '*.py[cod]' -o -name '*.swp' -o -name '.DS_Store' \) \
    -prune -exec rm -rf {} +
find "$share" -type d -exec chmod 755 {} +
# Not executable, so brp-mangle-shebangs leaves main.py alone.
find "$share" -type f -exec chmod 644 {} +
# Bytecode goes into the package too, so rpm knows it and removes it later.
python3 -m compileall -q -d %{_datadir}/%{name} "$share"

install -Dm755 packaging/arch/lintask %{buildroot}%{_bindir}/%{name}
# The old command keeps working after the rename.
ln -s %{name} %{buildroot}%{_bindir}/wintaskmanager
# Privileged helper for smartctl/dmidecode; the app creates the sudo rule for it.
install -Dm755 scripts/lintask-smartctl %{buildroot}%{_libexecdir}/%{name}/lintask-smartctl

# Menu entry: same template as install.sh, only with the launcher from /usr/bin.
install -d %{buildroot}%{_datadir}/applications
sed -e 's|^Exec=.*|TryExec=lintask\nExec=lintask|' lintask.desktop.in \
    > %{buildroot}%{_datadir}/applications/%{name}.desktop
chmod 644 %{buildroot}%{_datadir}/applications/%{name}.desktop

# Remote monitoring as a systemd service (optional, see %%post).
install -Dm644 packaging/debian/lintask-server.service \
    %{buildroot}/usr/lib/systemd/system/lintask-server.service
install -Dm600 packaging/debian/lintask-server.default \
    %{buildroot}%{_sysconfdir}/default/%{name}-server

install -Dm644 packaging/debian/copyright %{buildroot}%{_datadir}/licenses/%{name}/LICENSE

%post
systemctl daemon-reload >/dev/null 2>&1 || :
if [ "$1" -eq 1 ]; then
    cat <<'MSG'
Lintask: start it from the application menu or run  lintask  in a terminal.
Remote monitoring (optional):  sudo systemctl enable --now lintask-server
    Access token and port: /etc/default/lintask-server
MSG
fi

%preun
if [ "$1" -eq 0 ]; then
    systemctl disable --now lintask-server.service >/dev/null 2>&1 || :
fi

%postun
systemctl daemon-reload >/dev/null 2>&1 || :
if [ "$1" -ge 1 ]; then
    systemctl try-restart lintask-server.service >/dev/null 2>&1 || :
else
    # Also remove what the app set up (sudo rule for the helper, udev rule), but
    # only a sudo rule pointing at the packaged helper.
    if grep -qsE '/usr/(lib|libexec)/lintask/' /etc/sudoers.d/lintask-smartctl; then
        rm -f /etc/sudoers.d/lintask-smartctl
    fi
    rm -f /etc/udev/rules.d/99-lintask-rapl.rules
    # Leftovers such as __pycache__ from runs as root.
    rm -rf %{_datadir}/%{name}
fi

%files
%license %{_datadir}/licenses/%{name}/LICENSE
%doc README.md
%{_bindir}/%{name}
%{_bindir}/wintaskmanager
%{_datadir}/%{name}
%{_libexecdir}/%{name}
%{_datadir}/applications/%{name}.desktop
/usr/lib/systemd/system/lintask-server.service
%config(noreplace) %attr(600,root,root) %{_sysconfdir}/default/%{name}-server

%changelog
* Wed Nov 04 2026 Epiklal <https://github.com/Epiklal> - 1.1.3-1
- RPM, AppImage, tarball and snap packages built and tested in CI.

* Wed Nov 04 2026 Epiklal <https://github.com/Epiklal> - 1.1.2-1
- RPM package next to the .deb and the Arch package.
