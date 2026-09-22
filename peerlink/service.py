import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


SERVICE_NAME = "com.peerlink.connector"


def worker_command(state, auth_dir=None):
    command = [sys.executable, "-m", "peerlink.cli", "--state", str(Path(state).resolve()), "work"]
    if auth_dir:
        command.extend(["--auth-dir", str(Path(auth_dir).expanduser().resolve())])
    return command


def launchd_definition(state, auth_dir=None, log_dir=None):
    log_dir = Path(log_dir or Path(state) / "logs").expanduser().resolve()
    command = worker_command(state, auth_dir)
    return {
        "Label": SERVICE_NAME,
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


def service_path(platform=None):
    platform = platform or sys.platform
    if platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_NAME}.plist"
    if platform.startswith("linux"):
        return Path.home() / ".config" / "systemd" / "user" / "peerlink-connector.service"
    raise ValueError("后台服务目前只支持 macOS 和 Linux")


def install_service(state, auth_dir=None):
    state = Path(state).expanduser().resolve()
    if not (state / "connector.json").is_file():
        raise ValueError("设备尚未绑定，请先运行 peerlink connect")
    if auth_dir and not (Path(auth_dir).expanduser().resolve() / "auth.json").is_file():
        raise ValueError("--auth-dir 中未找到 auth.json")
    target = service_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    (state / "logs").mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform == "darwin":
        target.write_bytes(plistlib.dumps(launchd_definition(state, auth_dir)))
        os.chmod(target, 0o600)
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", domain, str(target)], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True)
        subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{SERVICE_NAME}"], check=True)
    else:
        target.write_text(systemd_definition(state, auth_dir))
        os.chmod(target, 0o600)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", target.name], check=True)
    return target


def remove_service():
    target = service_path()
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(target)], capture_output=True)
    else:
        subprocess.run(["systemctl", "--user", "disable", "--now", target.name], capture_output=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    if target.exists():
        target.unlink()
    return target


def service_status():
    target = service_path()
    if not target.exists():
        return {"installed": False, "path": str(target), "running": False}
    if sys.platform == "darwin":
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{SERVICE_NAME}"], capture_output=True
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
