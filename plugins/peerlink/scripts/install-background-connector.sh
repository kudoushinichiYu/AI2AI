#!/bin/sh
set -eu

if ! command -v peerlink >/dev/null 2>&1; then
  echo "peerlink CLI is not installed. Install the Peerlink Python package first." >&2
  exit 1
fi

exec peerlink service-install "$@"
