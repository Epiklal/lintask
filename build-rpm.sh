#!/usr/bin/env bash
# Builds an RPM package  dist/lintask-<version>-1.noarch.rpm  for Fedora,
# openSUSE and other RPM distributions (plus the source RPM):
#     sudo dnf install ./dist/lintask-*.noarch.rpm
#     sudo zypper install ./dist/lintask-*.noarch.rpm
#
# Usage:    ./build-rpm.sh [--docker] [VERSION]
# Needs rpmbuild (package "rpm-build"); with --docker it runs in a Fedora
# container instead. Package sources: packaging/rpm/lintask.spec
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

PKG=lintask
BASE_VERSION=1.2.1
STAGE=build/rpm
OUT_DIR=dist

if [[ "${1:-}" == "--docker" ]]; then
    shift
    exec docker run --rm -v "$APP_DIR:/src" -w /src -e VERSION="${1:-${VERSION:-}}" \
        -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" fedora:latest sh -c '
            dnf -y -q install rpm-build python3 git-core >/dev/null
            git config --global --add safe.directory /src
            ./build-rpm.sh "$VERSION"
            chown -R "$HOST_UID:$HOST_GID" build dist'
fi

if [[ -n "${1:-}" ]]; then
    VERSION="$1"
elif [[ -z "${VERSION:-}" ]]; then
    # Date and time keep versions ascending, the commit makes them traceable.
    stamp="$(date -u +%Y%m%d.%H%M)"
    commit="$(git rev-parse --short HEAD 2>/dev/null || true)"
    VERSION="${BASE_VERSION}+${stamp}${commit:+.g$commit}"
fi
# RPM versions must not contain "-".
VERSION="${VERSION//-/.}"

if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "rpmbuild is missing (package rpm-build) - or run  $0 --docker" >&2
    exit 1
fi

echo "== Building $PKG $VERSION (RPM) =="
rm -rf "$STAGE"
mkdir -p "$STAGE/SOURCES" "$OUT_DIR"
# The source tarball: only what the package needs, without caches.
tar -czf "$STAGE/SOURCES/$PKG-$VERSION.tar.gz" \
    --exclude=__pycache__ --exclude='*.py[cod]' --exclude='*.swp' \
    --transform "s|^|$PKG-$VERSION/|" \
    main.py app pages widgets scripts/lintask-smartctl lintask.desktop.in README.md \
    packaging/arch/lintask packaging/debian/lintask-server.service \
    packaging/debian/lintask-server.default packaging/debian/copyright

rpmbuild -ba packaging/rpm/lintask.spec \
    --define "_topdir $APP_DIR/$STAGE" \
    --define "pkg_version $VERSION" \
    --define "dist %{nil}"

cp "$STAGE"/RPMS/noarch/*.rpm "$STAGE"/SRPMS/*.src.rpm "$OUT_DIR/"
ls -l "$OUT_DIR"/$PKG-"$VERSION"-*.rpm
