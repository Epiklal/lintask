#!/bin/sh
# Smoke test for the bundles from build-bundle.sh, run inside a container of
# the distribution to test (the repository mounted, desktop libraries installed):
#     packaging/test-bundle.sh dist/lintask-*-x86_64.AppImage dist/lintask-*-linux-x86_64.tar.gz
# Checks that the AppImage and the tarball start (headless and, if Xvfb is
# there, on X11) and runs the unit tests with the bundled Python and Qt.
set -eu

[ $# -eq 2 ] || { echo "Usage: $0 APPIMAGE TARBALL" >&2; exit 2; }
appimage="$(readlink -f "$1")"
tarball="$(readlink -f "$2")"
repo="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Runs the GUI for a few seconds; it has to stay up until the timeout.
starts() {
    rc=0
    timeout -k 5 15 "$@" >"$work/log" 2>&1 || rc=$?
    if [ "$rc" != 124 ]; then
        cat "$work/log" >&2
        echo "FAILED (rc=$rc): $*" >&2
        exit 1
    fi
    echo "ok: $*"
}

# Containers have no FUSE, the AppImage runtime then unpacks itself.
export APPIMAGE_EXTRACT_AND_RUN=1
"$appimage" --server --help >/dev/null
echo "ok: AppImage --server --help"
QT_QPA_PLATFORM=offscreen starts "$appimage"

tar -xzf "$tarball" -C "$work"
dir="$(echo "$work"/lintask-*-x86_64)"
"$dir/lintask" --server --help >/dev/null
echo "ok: tarball --server --help"
QT_QPA_PLATFORM=offscreen starts "$dir/lintask"

if command -v Xvfb >/dev/null 2>&1; then
    Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 &
    xvfb=$!
    sleep 2
    DISPLAY=:99 QT_QPA_PLATFORM=xcb starts "$appimage"
    kill "$xvfb"
fi

# The unit tests with the bundled interpreter and Qt (from the repository,
# since some of them read the packaging files).
cd "$repo"
rc=0
QT_QPA_PLATFORM=offscreen "$dir/python/bin/python3" -E -s -B -m unittest discover -s tests -t . \
    >"$work/tests.log" 2>&1 || rc=$?
if [ "$rc" != 0 ]; then
    cat "$work/tests.log" >&2
    exit "$rc"
fi
tail -3 "$work/tests.log"
