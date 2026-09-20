import json
import os
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from peerlink.client import Client
from peerlink.connector import run_runtime, save_json, validate_project
from peerlink.hub import Store


@pytest.mark.parametrize("url", ["http://example.com", "ftp://localhost", "https://secret@example.com", "https://example.com?token=secret"])
def test_remote_requires_clean_https(url):
    with pytest.raises(ValueError):
        Client(url, "secret")


def test_local_mapping_cannot_escape(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    config = {"id": "device", "owner": "bob", "projects": {"demo": {"path": str(project)}}}
    task = {"device": "device", "receiver": "bob", "project": "demo", "path": "/etc"}
    assert validate_project(config, task)["path"] == str(project)
    project.rmdir()
    project.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        validate_project(config, task)


def test_private_state_permissions(tmp_path):
    path = tmp_path / "config.json"
    save_json(path, {"token": "secret"})
    assert path.stat().st_mode & 0o777 == 0o600


def test_mock_is_explicit_and_does_not_read_project(tmp_path):
    answer = run_runtime({"id": "demo", "path": "/does/not/exist", "runtime": "mock"}, "问题", tmp_path / "pending")
    assert "MOCK" in answer
    assert "未调用模型或读取项目内容" in answer


def test_codex_requires_explicit_credentials(tmp_path):
    with pytest.raises(ValueError, match="专用认证目录"):
        run_runtime({"id": "demo", "runtime": "codex-docker", "path": str(tmp_path)}, "问题", tmp_path / "pending")


def test_unknown_runtime_rejected(tmp_path):
    with pytest.raises(ValueError, match="不支持"):
        run_runtime({"runtime": "shell"}, "问题", tmp_path / "pending")


def test_codex_mount_options_cannot_be_injected(tmp_path):
    (tmp_path / "auth.json").write_text("{}")
    with pytest.raises(ValueError, match="逗号"):
        run_runtime({"runtime": "codex-docker", "path": "/project,readonly=false"}, "问题", tmp_path / "pending", tmp_path)


def test_real_http_cli_connector_roundtrip(tmp_path):
    import sys
    database = tmp_path / "hub.db"
    store = Store(database)
    alex, bob = store.add_user("alex"), store.add_user("bob")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    hub = f"http://127.0.0.1:{port}"
    server = subprocess.Popen([sys.executable, "-m", "peerlink.cli", "hub", "--db", str(database), "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    worker = None
    state = tmp_path / "bob"
    env = {**os.environ, "PEERLINK_HUB": hub, "PEERLINK_TOKEN": bob}
    def cli(*args):
        return subprocess.run([sys.executable, "-m", "peerlink.cli", "--state", str(state), *args], env=env, capture_output=True, text=True, timeout=20, check=True).stdout
    try:
        for attempt in range(100):
            try:
                if httpx.get(hub + "/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            pytest.fail("Hub 未启动")
        cli("connect", "--name", "bob-test")
        project = tmp_path / "project"
        project.mkdir()
        cli("project-add", "demo", str(project))
        asker = Client(hub, alex)
        owner = Client(hub, bob)
        task = asker.call("POST", "/api/requests", json={"receiver": "bob", "project": "demo", "question": "背景是什么？"})
        owner.call("POST", f"/api/requests/{task['id']}/decision", json={"action": "approve"})
        worker = subprocess.Popen([sys.executable, "-m", "peerlink.cli", "--state", str(state), "work"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        draft = state / "drafts" / (task["id"] + ".pending.json")
        for attempt in range(100):
            if draft.exists() and "answer" in json.loads(draft.read_text()):
                break
            time.sleep(0.05)
        else:
            pytest.fail("Connector 未生成草稿")
        row = asker.call("GET", f"/api/requests/{task['id']}")
        assert row["status"] == "WAITING_OUTPUT_APPROVAL"
        assert row["response"] is None
        assert "MOCK" in cli("review", task["id"])
        edited = tmp_path / "edited.txt"
        edited.write_text("本人审核并修改后的答案")
        cli("review", task["id"], "--send", "--answer-file", str(edited))
        row = asker.call("GET", f"/api/requests/{task['id']}")
        assert row["status"] == "COMPLETED"
        assert row["response"] == "本人审核并修改后的答案"
        assert alex not in (state / "connector.json").read_text()
        assert bob not in (state / "connector.json").read_text()
    finally:
        for process in (worker, server):
            if process:
                process.terminate()
                process.wait(timeout=10)
