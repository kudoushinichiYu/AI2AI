import plistlib
from pathlib import Path

import peerlink.service as service


def test_launchd_service_runs_worker_and_restarts(tmp_path):
    definition = service.launchd_definition(tmp_path, tmp_path / "auth")
    assert definition["Label"] == "com.peerlink.connector"
    assert definition["RunAtLoad"] is True
    assert definition["KeepAlive"] == {"SuccessfulExit": False}
    assert definition["ProgramArguments"][-2:] == ["--auth-dir", str((tmp_path / "auth").resolve())]
    assert plistlib.loads(plistlib.dumps(definition))["Label"] == "com.peerlink.connector"


def test_systemd_service_is_user_scoped_and_hardened(tmp_path):
    unit = service.systemd_definition(tmp_path)
    assert "ExecStart=" in unit
    assert "peerlink.cli" in unit
    assert "NoNewPrivileges=true" in unit
    assert "WantedBy=default.target" in unit


def test_service_install_requires_paired_device(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "service_path", lambda platform=None: tmp_path / "agent.plist")
    try:
        service.install_service(tmp_path)
    except ValueError as error:
        assert "peerlink connect" in str(error)
    else:
        raise AssertionError("未绑定设备不应安装服务")


def test_notify_is_best_effort(monkeypatch):
    monkeypatch.setattr(service.sys, "platform", "darwin")
    monkeypatch.setattr(service.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(service.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    service.notify("title", "message")
