#!/usr/bin/env bash
# Builds self-contained bundles that bring their own Python, PySide6 and psutil
# and therefore run on any x86_64 distribution with glibc >= 2.35:
#     dist/lintask-<version>-x86_64.AppImage
#     dist/lintask-<version>-linux-x86_64.tar.gz
#     dist/lintask_<version>_amd64.snap          (classic confinement)
#
# Usage:    ./build-bundle.sh [--docker] [VERSION]     (or  VERSION=1.2.3 ./build-bundle.sh)
# The bundles take their glibc requirement from the build system, so build them
# on Ubuntu 22.04 - "--docker" does that in an ubuntu:22.04 container.
# Needs curl, sha256sum, mksquashfs (squashfs-tools), patchelf and the xcb libraries
# listed in DOCKER_PACKAGES below.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

PKG=lintask
BASE_VERSION=1.2.1
BUILD_IMAGE=ubuntu:22.04
DOCKER_PACKAGES="ca-certificates curl file patchelf squashfs-tools xz-utils
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0
    libxcb-xkb1 libxkbcommon0 libxkbcommon-x11-0"

PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
PYTHON_SHA256=ce4f6d0a6cfdb3bed6e44c2f9affd85943c76a42e25ad3a259002f31d6fb8a20
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64"
RUNTIME_SHA256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d

# Qt's xcb platform plugin needs these, but not every desktop system has them
# (Fedora and Arch often lack libxcb-cursor). They go next to the Qt libraries,
# where RUNPATH=$ORIGIN finds them - LD_LIBRARY_PATH would leak into every
# program Lintask starts. They get the same RUNPATH, because libxcb-image and
# libxcb-cursor need libxcb-util, which is missing just as often.
BUNDLED_LIBS="libxcb-cursor.so.0 libxcb-icccm.so.4 libxcb-image.so.0 libxcb-keysyms.so.1
    libxcb-render-util.so.0 libxcb-util.so.1 libxcb-xkb.so.1 libxkbcommon.so.0 libxkbcommon-x11.so.0"

DOCKER=0
if [[ "${1:-}" == "--docker" ]]; then
    DOCKER=1
    shift
fi
if [[ -n "${1:-}" ]]; then
    VERSION="$1"
elif [[ -z "${VERSION:-}" ]]; then
    # Date and time keep versions ascending, the commit makes them traceable.
    stamp="$(date -u +%Y%m%d.%H%M)"
    commit="$(git rev-parse --short HEAD 2>/dev/null || true)"
    VERSION="${BASE_VERSION}+${stamp}${commit:+.g$commit}"
fi

if [[ "$DOCKER" == 1 ]]; then
    echo "== Building in $BUILD_IMAGE =="
    exec docker run --rm -v "$APP_DIR:/src" -w /src \
        -e VERSION="$VERSION" -e HOST_IDS="$(id -u):$(id -g)" -e DOCKER_PACKAGES="$DOCKER_PACKAGES" \
        "$BUILD_IMAGE" bash -c '
            set -e
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            apt-get install -y -qq --no-install-recommends $DOCKER_PACKAGES >/dev/null
            rc=0
            ./build-bundle.sh "$VERSION" || rc=$?
            chown -R "$HOST_IDS" dist build 2>/dev/null || true
            exit $rc'
fi

# Snap versions: at most 32 characters, no leading or trailing punctuation.
if ! [[ "$VERSION" =~ ^[A-Za-z0-9]([A-Za-z0-9:.+~-]{0,30}[A-Za-z0-9])?$ ]]; then
    echo "Version '$VERSION' is not valid for a snap (max. 32 characters of A-Z a-z 0-9 : . + ~ -)." >&2
    exit 1
fi
[[ "$(uname -m)" == x86_64 ]] || { echo "Only x86_64 is supported." >&2; exit 1; }
for tool in curl sha256sum mksquashfs patchelf tar; do
    command -v "$tool" >/dev/null 2>&1 || { echo "$tool is missing." >&2; exit 1; }
done
for f in main.py app pages widgets scripts/lintask-smartctl lintask.desktop.in requirements.txt \
         packaging/icons/lintask.svg; do
    [[ -e "$f" ]] || { echo "Missing: $f" >&2; exit 1; }
done

BUILD=build/bundle
DOWNLOADS=build/downloads
OUT_DIR=dist
ROOT="$BUILD/$PKG"
APPIMAGE="$OUT_DIR/$PKG-$VERSION-x86_64.AppImage"
TARBALL="$OUT_DIR/$PKG-$VERSION-linux-x86_64.tar.gz"
SNAP="$OUT_DIR/${PKG}_${VERSION}_amd64.snap"

# Downloads are kept between builds and checked every time.
fetch() {
    local url="$1" sha="$2" target="$DOWNLOADS/$3"
    if [[ ! -f "$target" ]] || ! echo "$sha  $target" | sha256sum -c --status; then
        echo "Downloading $url"
        curl -fsSL --retry 3 -o "$target.part" "$url"
        echo "$sha  $target.part" | sha256sum -c --quiet
        mv "$target.part" "$target"
    fi
}
mkdir -p "$DOWNLOADS" "$OUT_DIR"
fetch "$PYTHON_URL" "$PYTHON_SHA256" python.tar.gz
fetch "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256" appimagetool
fetch "$RUNTIME_URL" "$RUNTIME_SHA256" runtime-x86_64
chmod +x "$DOWNLOADS/appimagetool"

echo "== Building the bundle for $VERSION =="
rm -rf "$BUILD"
mkdir -p "$ROOT/bin" "$ROOT/app" "$ROOT/share/applications" "$ROOT/share/icons/hicolor/scalable/apps"
tar -xzf "$DOWNLOADS/python.tar.gz" -C "$ROOT"
PY="$ROOT/python/bin/python3"
PY_LIB="$(echo "$ROOT"/python/lib/python3.*)"
SITE="$PY_LIB/site-packages"

"$PY" -m pip install --quiet --disable-pip-version-check --no-cache-dir --no-compile \
    --only-binary=:all: -r requirements.txt
"$PY" -c 'import PySide6, psutil; print("PySide6", PySide6.__version__, "/ psutil", psutil.__version__)'

# What Lintask does not use: pip, the test suite and Tk, the Qt developer tools,
# QML/Quick and the other modules beyond QtCore/QtGui/QtWidgets.
rm -rf "$SITE"/pip "$SITE"/pip-* "$PY_LIB"/ensurepip "$PY_LIB"/test "$PY_LIB"/idlelib \
       "$PY_LIB"/tkinter "$PY_LIB"/turtledemo "$PY_LIB"/lib-dynload/_tkinter.* \
       "$ROOT"/python/lib/libtcl* "$ROOT"/python/lib/libtk* "$ROOT"/python/lib/tcl* "$ROOT"/python/lib/tk* \
       "$ROOT"/python/lib/itcl* "$ROOT"/python/lib/thread* "$ROOT"/python/include "$ROOT"/python/share \
       "$ROOT"/python/bin/idle3* "$ROOT"/python/bin/pip* "$ROOT"/python/bin/pydoc3*
QT="$SITE/PySide6"
rm -rf "$QT"/assistant "$QT"/designer "$QT"/linguist "$QT"/lrelease "$QT"/lupdate "$QT"/qml* \
       "$QT"/svgtoqml "$QT"/balsam* "$QT"/doc "$QT"/glue "$QT"/include "$QT"/typesystems "$QT"/scripts \
       "$QT"/Qt/metatypes "$QT"/Qt/qml "$QT"/Qt/libexec "$QT"/Qt/translations/{assistant,designer,linguist,qtquick}* \
       "$QT"/Qt/plugins/{designer,qmltooling,sqldrivers,qmllint,wayland-graphics-integration-server} \
       "$QT"/Qt/plugins/{egldeviceintegrations,vectorimageformats} "$QT"/Qt/plugins/imageformats/libqpdf.so \
       "$QT"/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so \
       "$QT"/Qt/plugins/platforms/libq{vnc,vkkhrdisplay,eglfs}.so "$QT"/libpyside6qml.*
find "$SITE" -name '*.pyi' -delete
for module in QtQml QtQuick QtQuickControls2 QtQuickWidgets QtQuickTest QtDesigner QtUiTools QtSql QtTest \
              QtHelp QtLabsStyleKit QtXml QtConcurrent; do
    rm -f "$QT/$module".*.so "$QT/$module"Features.*.so
done
for lib in Qml Quick Labs Lottie Designer Help Sql Test UiTools WaylandCompositor WaylandEglCompositor \
           ShaderTools VirtualKeyboard Pdf EglFs; do
    rm -f "$QT"/Qt/lib/libQt6"$lib"*.so*
done

for lib in $BUNDLED_LIBS; do
    path="$(ldconfig -p | awk -v l="$lib" '$1 == l && /x86-64/ { print $NF; exit }')"
    [[ -n "$path" ]] || { echo "$lib not found - install the packages in DOCKER_PACKAGES." >&2; exit 1; }
    cp -L "$path" "$QT/Qt/lib/$lib"
    patchelf --set-rpath '$ORIGIN' "$QT/Qt/lib/$lib"
done

# Every library and plugin that is left must still find the Qt, PySide and
# shiboken libraries it was linked against. System libraries such as X11,
# fontconfig or glib come from the host and are not checked here.
missing="$(find "$ROOT/python" -name '*.so*' -type f -print0 \
    | xargs -0 -n 50 ldd 2>/dev/null | grep -E 'lib(Qt6|pyside6|shiboken6|python3)[^ ]* => not found' \
    | sort -u || true)"
if [[ -n "$missing" ]]; then
    echo "Unresolved libraries after stripping the bundle:" >&2
    echo "$missing" >&2
    exit 1
fi

# The program itself, laid out as in the source tree (the settings page finds
# scripts/lintask-smartctl next to main.py).
cp main.py "$ROOT/app/"
cp -r app pages widgets "$ROOT/app/"
install -D -m 0755 scripts/lintask-smartctl "$ROOT/app/scripts/lintask-smartctl"
find "$ROOT/app" \( -name __pycache__ -o -name '*.py[cod]' -o -name '*.swp' -o -name '.DS_Store' \) \
    -prune -exec rm -rf {} +
# The bundles are read-only, so compile now; unchecked-hash skips the mtime check.
"$PY" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$ROOT/app" "$PY_LIB" >/dev/null

cat > "$ROOT/bin/$PKG" <<'EOF'
#!/bin/sh
# Starts Lintask with its own Python; works through symlinks (AppImage AppRun,
# a link in ~/.local/bin, the snap command).
here="$(dirname "$(readlink -f "$0")")"
root="$(dirname "$here")"
# -E -s: no PYTHON* variables and no user site-packages from the host
exec "$root/python/bin/python3" -E -s "$root/app/main.py" "$@"
EOF
chmod 0755 "$ROOT/bin/$PKG"

sed -e "s|^Exec=.*|Exec=$PKG|" -e "s|^Icon=.*|Icon=$PKG|" lintask.desktop.in > "$ROOT/share/applications/$PKG.desktop"
install -m 0644 packaging/icons/lintask.svg "$ROOT/share/icons/hicolor/scalable/apps/$PKG.svg"
cp README.md "$ROOT/"
[[ -f packaging/debian/copyright ]] && cp packaging/debian/copyright "$ROOT/LICENSE"

chmod -R u+rwX,go+rX,go-w "$ROOT"
echo "Bundle size: $(du -sh "$ROOT" | cut -f1)"

# --- tar.gz: unpack anywhere and start ./lintask ---------------------------
echo "== $TARBALL =="
TAR_DIR="$BUILD/tar/$PKG-$VERSION-x86_64"
mkdir -p "$TAR_DIR"
cp -a "$ROOT/." "$TAR_DIR/"
ln -s "bin/$PKG" "$TAR_DIR/$PKG"
rm -f "$TARBALL"
tar --owner=0 --group=0 --numeric-owner --sort=name -C "$BUILD/tar" -czf "$TARBALL" "$PKG-$VERSION-x86_64"

# --- AppImage --------------------------------------------------------------
echo "== $APPIMAGE =="
APPDIR="$BUILD/$PKG.AppDir"
mkdir -p "$APPDIR"
cp -a "$ROOT/." "$APPDIR/"
ln -s "bin/$PKG" "$APPDIR/AppRun"
cp "$ROOT/share/applications/$PKG.desktop" "$APPDIR/$PKG.desktop"
cp packaging/icons/lintask.svg "$APPDIR/$PKG.svg"
ln -s "$PKG.svg" "$APPDIR/.DirIcon"
rm -f "$APPIMAGE"
# Without FUSE (containers, CI) the tool unpacks itself instead of mounting.
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 VERSION="$VERSION" "$DOWNLOADS/appimagetool" --no-appstream \
    --runtime-file "$DOWNLOADS/runtime-x86_64" "$APPDIR" "$APPIMAGE"
chmod 0755 "$APPIMAGE"

# --- snap (classic: a task manager has to see the whole system) ------------
echo "== $SNAP =="
SNAP_DIR="$BUILD/snap"
mkdir -p "$SNAP_DIR"
cp -a "$ROOT/." "$SNAP_DIR/"
mkdir -p "$SNAP_DIR/meta/gui"
cat > "$SNAP_DIR/meta/snap.yaml" <<EOF
name: $PKG
version: '$VERSION'
summary: Task manager for Linux in the style of the Windows Task Manager
description: |
  Processes, performance graphs for CPU, memory, disks, network and GPUs,
  services, autostart entries, Docker containers, sensors and benchmarks.
base: core24
confinement: classic
grade: stable
architectures: [amd64]
apps:
  $PKG:
    command: bin/$PKG
EOF
sed -e "s|^Icon=.*|Icon=\${SNAP}/meta/gui/$PKG.svg|" "$ROOT/share/applications/$PKG.desktop" \
    > "$SNAP_DIR/meta/gui/$PKG.desktop"
cp packaging/icons/lintask.svg "$SNAP_DIR/meta/gui/$PKG.svg"
rm -f "$SNAP"
if command -v snap >/dev/null 2>&1 && snap pack --help >/dev/null 2>&1; then
    snap pack "$SNAP_DIR" --filename="$SNAP"
else
    # Same format as "snap pack" produces
    mksquashfs "$SNAP_DIR" "$SNAP" -noappend -comp xz -no-fragments -no-progress -all-root -quiet
fi

echo
ls -lh "$APPIMAGE" "$TARBALL" "$SNAP"
echo
echo "AppImage: chmod +x $APPIMAGE && ./$APPIMAGE"
echo "tar.gz:   tar -xzf $TARBALL && ./$PKG-$VERSION-x86_64/$PKG"
echo "snap:     sudo snap install --dangerous --classic ./$SNAP"
