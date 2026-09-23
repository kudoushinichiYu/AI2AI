"""Public release metadata and conservative update checks."""

import re
import shlex

from peerlink import __version__
from peerlink.client import Client


PLUGIN_VERSION = "0.5.0+codex.20260923"
PLUGIN_MARKETPLACE = "peerlink-team"
PLUGIN_ID = "peerlink@peerlink-team"
PUBLIC_HUB = "https://peerlink.jd.com"


def release_metadata():
    return {
        "cli_version": __version__,
        "plugin_version": PLUGIN_VERSION,
        "plugin_marketplace": PLUGIN_MARKETPLACE,
    }


def version_key(value):
    """Parse the numeric release portion; reject malformed server metadata."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\+[0-9A-Za-z.-]+)?", value)
    return tuple(map(int, match.groups())) if match else None


def check_releases(hub, installed_cli=__version__, installed_plugin=PLUGIN_VERSION):
    client = Client(hub)
    try:
        remote = client.call("GET", "/api/releases", timeout=4)
    finally:
        client.http.close()

    latest_cli = remote.get("cli_version") if isinstance(remote, dict) else None
    latest_plugin = remote.get("plugin_version") if isinstance(remote, dict) else None
    marketplace = remote.get("plugin_marketplace") if isinstance(remote, dict) else None
    cli_key, latest_cli_key = version_key(installed_cli), version_key(latest_cli)
    plugin_key, latest_plugin_key = version_key(installed_plugin), version_key(latest_plugin)
    if not cli_key or not latest_cli_key or not plugin_key or not latest_plugin_key:
        raise ValueError("Hub 返回的版本信息格式无效")
    if marketplace != PLUGIN_MARKETPLACE:
        raise ValueError("Hub 返回的插件源不是受支持的 Peerlink Marketplace")

    base = hub.rstrip("/")
    return {
        "checked": True,
        "cli": {
            "installed": installed_cli,
            "latest": latest_cli,
            "update_available": latest_cli_key > cli_key,
            "install_command": f"python3 -m pip install --user --upgrade "
                               f"{shlex.quote(base + '/downloads/peerlink.whl')}",
        },
        "plugin": {
            "bundled": installed_plugin,
            "latest": latest_plugin,
            "update_available": latest_plugin_key > plugin_key,
            "marketplace": PLUGIN_MARKETPLACE,
            "plugin_id": PLUGIN_ID,
            "refresh_command": f"codex plugin marketplace upgrade {PLUGIN_MARKETPLACE}",
            "reinstall_commands": [
                f"codex plugin remove {PLUGIN_ID}",
                f"codex plugin add {PLUGIN_ID}",
            ],
        },
    }
