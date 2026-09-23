#!/bin/sh
set -eu

package_version=$(sed -n 's/^__version__ = "\([^"]*\)"$/\1/p' peerlink/__init__.py)
if [ -z "$package_version" ]; then
    echo "Could not read the package version from peerlink/__init__.py" >&2
    exit 1
fi

if command -v uv >/dev/null 2>&1; then
    uv build --wheel --out-dir dist --no-create-gitignore
else
    python -m build --wheel --outdir dist
fi
wheel="dist/peerlink-$package_version-py3-none-any.whl"
if [ ! -s "$wheel" ]; then
    echo "Expected the current Peerlink wheel at $wheel" >&2
    exit 1
fi
printf 'Built client package: %s\n' "$wheel"
