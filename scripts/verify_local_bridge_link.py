"""Verify a paired local identity can send to and receive from a new local Relay.

This does not approve or execute a request. It never changes the production Hub
or the original state directory. A temporary, mode-0600 state copy is removed
when the probe exits.
"""

import argparse
import asyncio
import json
import secrets
import socket
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path

import httpx
import uvicorn

from peerlink.bridge.client import BridgeRunner
from peerlink.bridge.registry import add_agent
from peerlink.connector import save_json
from peerlink.hub import Store, create_app, digest


async def verify(source, expected_owner, project, root, notifications):
    config = json.loads((source / "connector.json").read_text())
    if config.get("owner") != expected_owner:
        raise ValueError("状态目录与预期 ERP 身份不符")
    if config.get("hub") != "https://peerlink.jd.com":
        raise ValueError("状态目录不是预期的线上配对设备")
    if not config.get("token") or not config.get("id"):
        raise ValueError("状态目录缺少配对设备凭证")

    local_state = root / "state"
    workspace = root / "workspace"
    workspace.mkdir()
    store = Store(root / "hub.db")
    store.create_admin(expected_owner)
    with store.connect() as conn:
        conn.execute("INSERT INTO devices(id,owner,name,token,seen) VALUES (?,?,?,?,?)",
                     (config["id"], expected_owner, "local-bridge-probe", digest(config["token"]), 0))
        conn.execute("INSERT INTO project_catalog VALUES (?,?,?,?,?)",
                     (project, "Local transport probe", "ACTIVE", expected_owner, time.time()))

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    hub = f"http://127.0.0.1:{port}"
    save_json(local_state / "connector.json", {**config, "hub": hub, "projects": {}})
    add_agent(local_state, project, workspace, visibility="private")
    server = uvicorn.Server(uvicorn.Config(create_app(root / "hub.db"),
                                          host="127.0.0.1", port=port,
                                          access_log=False, log_level="error"))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    runner = BridgeRunner(local_state)

    async def probe_heartbeat(socket):
        while True:
            await socket.send(json.dumps({"version": "1", "type": "device.heartbeat"}))
            await asyncio.sleep(0.3)

    runner._heartbeat = probe_heartbeat
    background = asyncio.create_task(runner.run())
    headers = {"Authorization": "Bearer " + config["token"]}
    try:
        async with httpx.AsyncClient(base_url=hub, headers=headers, timeout=3) as client:
            for _ in range(100):
                try:
                    listed = await client.get("/api/bridge/agents", params={"owner": expected_owner})
                    if listed.status_code == 200 and any(
                        agent["id"] == project and agent["online"] for agent in listed.json()
                    ):
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("Bridge 未连到本机 Relay")

            for _ in range(100):
                with store.connect() as conn:
                    seen = conn.execute("SELECT seen FROM devices WHERE id=?", (config["id"],)).fetchone()[0]
                if seen > 0:
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("Bridge 的 WebSocket 心跳未到达 Relay")

            marker = secrets.token_hex(12)
            response = await client.post("/api/bridge/messages", json={
                "receiver": expected_owner, "agent_id": project,
                "message_id": marker,
                "content": "Peerlink 本机双向传输探针；不要批准执行。",
            })
            response.raise_for_status()
            if response.json().get("status") != "WAITING_APPROVAL":
                raise AssertionError("向 Relay 发送探针后状态异常")
            for _ in range(100):
                if any(project in message for _, message in notifications):
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("Relay 下发通知未被本机 Bridge 接收")

            request = await client.get(f"/api/requests/{marker}")
            request.raise_for_status()
            if request.json().get("status") != "WAITING_APPROVAL":
                raise AssertionError("未审批探针不应被执行")
            cancelled = await client.post(f"/api/requests/{marker}/decision",
                                          json={"action": "cancel"})
            cancelled.raise_for_status()
            return {"identity": expected_owner, "device": config["id"],
                    "relay": hub, "upload": "passed", "download": "passed",
                    "websocket_heartbeat_up": "passed",
                    "websocket_notification_down": "passed",
                    "approval_boundary": "request stayed WAITING_APPROVAL until cancelled"}
    finally:
        background.cancel()
        with suppress(asyncio.CancelledError):
            await background
        server.should_exit = True
        server_thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description="Local Peerlink Bridge identity transport probe")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--project", default="ai-outbound")
    args = parser.parse_args()
    notifications = []
    import peerlink.bridge.client as bridge_client
    original_notify = bridge_client.notify
    bridge_client.notify = lambda title, message: notifications.append((title, message))
    try:
        with tempfile.TemporaryDirectory(prefix="peerlink-local-link-") as directory:
            result = asyncio.run(verify(args.state.expanduser().resolve(), args.owner,
                                        args.project, Path(directory), notifications))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        bridge_client.notify = original_notify


if __name__ == "__main__":
    main()
