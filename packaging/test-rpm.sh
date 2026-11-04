#!/bin/sh
# Smoke test for the RPM from build-rpm.sh, run as root inside a Fedora or
# openSUSE container with the repository mounted:
#     packaging/test-rpm.sh dist/lintask-*.noarch.rpm
# Installs the package with its dependencies, starts the app headless, runs the
# unit tests against the installed PySide6 and removes the package again.
set -eu

[ $# -eq 1 ] || { echo "Usage: $0 RPM" >&2; exit 2; }
rpm="$(readlink -f "$1")"
repo="$(cd "$(dirname "$0")/.." && pwd)"

if command -v dnf >/dev/null 2>&1; then
    dnf -y -q install "$rpm" >/dev/null
    remove="dnf -y -q remove lintask"
else
    # gawk: some unit tests run awk, which a Tumbleweed container lacks.
    zypper -n -q --no-gpg-checks install --allow-unsigned-rpm gawk "$rpm"
    remove="zypper -n -q remove lintask"
fi

test -x /usr/bin/lintask
test -L /usr/bin/wintaskmanager
test -f /usr/lib/systemd/system/lintask-server.service
test "$(stat -c %a /etc/default/lintask-server)" = 600
ls /usr/libexec/lintask/lintask-smartctl /usr/lib/lintask/lintask-smartctl 2>/dev/null | grep -q .

lintask --server --help >/dev/null
echo "ok: lintask --server --help"
rc=0
QT_QPA_PLATFORM=offscreen timeout -k 5 15 lintask >/tmp/lintask.log 2>&1 || rc=$?
if [ "$rc" != 124 ]; then
    cat /tmp/lintask.log >&2
    echo "FAILED (rc=$rc): lintask" >&2
    exit 1
fi
echo "ok: lintask (offscreen)"

cd "$repo"
rc=0
QT_QPA_PLATFORM=offscreen python3 -B -m unittest discover -s tests -t . >/tmp/tests.log 2>&1 || rc=$?
if [ "$rc" != 0 ]; then
    cat /tmp/tests.log >&2
    exit "$rc"
fi
tail -3 /tmp/tests.log

$remove >/dev/null 2>&1
test ! -e /usr/bin/lintask
test ! -e /usr/share/lintask
echo "ok: removed"
