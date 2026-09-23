"""Interactive, loopback-only Peerlink request/reply verification.

Uses the selected real paired device credential against an ephemeral local Hub.
Only the human owner may approve the request in the web UI and send the Echo
draft with `peerlink review --send`. Nothing is sent to the production Hub.
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


async def wait_for_ready(client, owner, project):
    for _ in range(100):
        try:
            response = await client.get("/api/bridge/agents", params={"owner": owner})
            if response.status_code == 200 and any(
                agent["id"] == project and agent["online"] for agent in response.json()
            ):
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.05)
    raise RuntimeError("本机 Bridge 未连接到临时 Relay")


async def run_probe(source, owner, project, root, minutes):
    original = json.loads((source / "connector.json").read_text())
    if original.get("owner") != owner or original.get("hub") != "https://peerlink.jd.com":
        raise ValueError("状态目录不是预期的线上配对身份")
    if not original.get("token") or not original.get("id"):
        raise ValueError("状态目录缺少配对设备凭证")

    password = secrets.token_urlsafe(18)
    store = Store(root / "hub.db")
    store.create_admin_password(owner, password)
    with store.connect() as conn:
        conn.execute("INSERT INTO devices(id,owner,name,token,seen) VALUES (?,?,?,?,?)",
                     (original["id"], owner, "interactive-local-probe", digest(original["token"]), 0))
        conn.execute("INSERT INTO project_catalog VALUES (?,?,?,?,?)",
                     (project, "Local Echo request test", "ACTIVE", owner, time.time()))

    workspace = root / "workspace"
    workspace.mkdir()
    local_state = root / "state"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    hub = f"http://127.0.0.1:{port}"
    save_json(local_state / "connector.json", {**original, "hub": hub, "projects": {}})
    add_agent(local_state, project, workspace, backend="echo", visibility="private")

    server = uvicorn.Server(uvicorn.Config(create_app(root / "hub.db"),
                                          host="127.0.0.1", port=port,
                                          access_log=False, log_level="error"))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    background = None
    try:
        background = asyncio.create_task(BridgeRunner(local_state).run())
        headers = {"Authorization": "Bearer " + original["token"]}
        async with httpx.AsyncClient(base_url=hub, headers=headers, timeout=4) as client:
            await wait_for_ready(client, owner, project)
            marker = secrets.token_hex(12)
            sent = await client.post("/api/bridge/messages", json={
                "receiver": owner, "agent_id": project, "message_id": marker,
                "content": "Peerlink 本机完整链路测试：请原样确认这条消息已到达本机。",
            })
            sent.raise_for_status()
            if sent.json().get("status") != "WAITING_APPROVAL":
                raise RuntimeError("测试请求没有进入待本人审批状态")

            print(json.dumps({
                "test_hub": hub, "test_user": owner, "test_password": password,
                "request_id": marker, "state": str(local_state),
                "approve": "请本人登录测试网页，在提问与请求中批准该请求",
                "review": f"./.venv/bin/python -m peerlink.cli --state {local_state} review {marker}",
                "send": "阅读草稿后，如确认可分享，请本人在上一条 review 命令末尾加 --send",
                "expires_in_minutes": minutes,
                "production_hub_unchanged": True,
            }, ensure_ascii=False, indent=2), flush=True)

            deadline = time.monotonic() + minutes * 60
            last_status = None
            while time.monotonic() < deadline:
                item = await client.get(f"/api/requests/{marker}")
                item.raise_for_status()
                status = item.json()["status"]
                if status != last_status:
                    print(json.dumps({"request_id": marker, "status": status},
                                     ensure_ascii=False), flush=True)
                    last_status = status
                if status == "COMPLETED":
                    response = item.json().get("response", "")
                    if response != "echo: Peerlink 本机完整链路测试：请原样确认这条消息已到达本机。":
                        raise AssertionError("收到的最终答案与测试消息不匹配")
                    print(json.dumps({"identity": owner, "request_id": marker,
                                      "content_down": "passed", "draft_up": "passed",
                                      "human_approval_and_review": "observed",
                                      "production_hub_unchanged": True},
                                     ensure_ascii=False, indent=2), flush=True)
                    return
                if status in ("FAILED", "REJECTED", "CANCELLED"):
                    raise RuntimeError(f"测试请求结束于 {status}")
                await asyncio.sleep(1)
            raise TimeoutError("等待本人审批和草稿发送超时；临时服务将自动清理")
    finally:
        if background is not None:
            background.cancel()
            with suppress(asyncio.CancelledError):
                await background
        server.should_exit = True
        server_thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description="Peerlink local interactive request probe")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--project", default="ai-outbound")
    parser.add_argument("--minutes", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.minutes <= 60:
        parser.error("--minutes 必须在 1 到 60 之间")
    import peerlink.bridge.client as bridge_client
    original_notify = bridge_client.notify
    bridge_client.notify = lambda *_: None
    try:
        with tempfile.TemporaryDirectory(prefix="peerlink-local-request-") as directory:
            asyncio.run(run_probe(args.state.expanduser().resolve(), args.owner,
                                  args.project, Path(directory), args.minutes))
    finally:
        bridge_client.notify = original_notify


if __name__ == "__main__":
    main()
