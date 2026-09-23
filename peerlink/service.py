import os
import hashlib
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


SERVICE_NAME = "com.peerlink.connector"


def service_name(state=None):
    if state is None or Path(state).expanduser().resolve() == (Path.home() / ".peerlink").resolve():
        return SERVICE_NAME
    suffix = hashlib.sha256(str(Path(state).expanduser().resolve()).encode()).hexdigest()[:10]
    return f"{SERVICE_NAME}.{suffix}"


def worker_command(state, auth_dir=None):
    command = [sys.executable, "-m", "peerlink.cli", "--state", str(Path(state).resolve()),
               "bridge", "start"]
    if auth_dir:
        command.extend(["--auth-dir", str(Path(auth_dir).expanduser().resolve())])
    return command


def launchd_definition(state, auth_dir=None, log_dir=None):
    log_dir = Path(log_dir or Path(state) / "logs").expanduser().resolve()
    command = worker_command(state, auth_dir)
    return {
        "Label": service_name(state),
        "ProgramArguments": command,
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Background",
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", os.defpath)},
        "StandardOutPath": str(log_dir / "connector.log"),
        "StandardErrorPath": str(log_dir / "connector.error.log"),
    }


def systemd_definition(state, auth_dir=None):
    command = " ".join(_systemd_quote(value) for value in worker_command(state, auth_dir))
    service_path_value = os.environ.get("PATH", os.defpath).replace("%", "%%")
    return "\n".join([
        "[Unit]",
        "Description=Peerlink Connector",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        f'Environment="PATH={service_path_value}"',
        f"ExecStart={command}",
        "Restart=on-failure",
        "RestartSec=5",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ])


def _systemd_quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def service_path(platform=None, state=None):
    platform = platform or sys.platform
    if platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{service_name(state)}.plist"
    if platform.startswith("linux"):
        suffix = "" if service_name(state) == SERVICE_NAME else "-" + service_name(state).split(".")[-1]
        return Path.home() / ".config" / "systemd" / "user" / f"peerlink-connector{suffix}.service"
    raise ValueError("后台服务目前只支持 macOS 和 Linux")


def install_service(state, auth_dir=None):
    state = Path(state).expanduser().resolve()
    if not (state / "connector.json").is_file():
        raise ValueError("设备尚未绑定，请先运行 peerlink connect")
    if auth_dir and not (Path(auth_dir).expanduser().resolve() / "auth.json").is_file():
        raise ValueError("--auth-dir 中未找到 auth.json")
    target = service_path(state=state)
    target.parent.mkdir(parents=True, exist_ok=True)
    (state / "logs").mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform == "darwin":
        target.write_bytes(plistlib.dumps(launchd_definition(state, auth_dir)))
        os.chmod(target, 0o600)
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", domain, str(target)], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True)
        subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{service_name(state)}"], check=True)
    else:
        target.write_text(systemd_definition(state, auth_dir))
        os.chmod(target, 0o600)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", target.name], check=True)
    return target


def remove_service(state=None):
    target = service_path(state=state)
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(target)], capture_output=True)
    else:
        subprocess.run(["systemctl", "--user", "disable", "--now", target.name], capture_output=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    if target.exists():
        target.unlink()
    return target


def service_status(state=None):
    target = service_path(state=state)
    if not target.exists():
        return {"installed": False, "path": str(target), "running": False}
    if sys.platform == "darwin":
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{service_name(state)}"], capture_output=True
        )
    else:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", target.name], capture_output=True
        )
    return {"installed": True, "path": str(target), "running": result.returncode == 0}


def notify(title, message):
    """Best-effort local notification; never lets desktop integration stop work."""
    try:
        if sys.platform == "darwin" and shutil.which("osascript"):
            script = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"
            subprocess.run(["osascript", "-e", script, title, message], capture_output=True, timeout=10)
        elif sys.platform.startswith("linux") and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass
