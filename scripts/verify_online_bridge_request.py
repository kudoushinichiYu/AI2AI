"""Human-approved production Relay probe using a temporary private Echo Agent.

The probe reuses an existing paired device credential but never edits its state.
It does not read a real project directory, approve work, or send a draft for the
owner. Its temporary Agent registration is removed when the probe exits.
"""

import argparse
import asyncio
import json
import secrets
import tempfile
import time
from contextlib import suppress
from pathlib import Path

import httpx

from peerlink.bridge.client import BridgeRunner
from peerlink.bridge.registry import add_agent
from peerlink.connector import save_json


async def wait_for_agent(client, owner, project):
    for _ in range(60):
        response = await client.get("/api/bridge/agents", params={"owner": owner})
        response.raise_for_status()
        if any(item["id"] == project and item["online"] for item in response.json()):
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("线上 Bridge 未将临时 Agent 标记为在线")


async def run_probe(source, owner, project, minutes):
    original = json.loads((source / "connector.json").read_text())
    if original.get("owner") != owner or original.get("hub") != "https://peerlink.jd.com":
        raise ValueError("状态目录不是预期的线上配对身份")
    if not original.get("token") or not original.get("id"):
        raise ValueError("状态目录缺少配对设备凭证")

    hub = original["hub"]
    marker = secrets.token_hex(12)
    question = f"Peerlink 线上 Bridge 完整链路测试 {marker}：请原样确认已到达本机。"
    with tempfile.TemporaryDirectory(prefix="peerlink-online-request-") as directory:
        root = Path(directory)
        state = root / "state"
        workspace = root / "empty-echo-workspace"
        workspace.mkdir()
        save_json(state / "connector.json", {**original, "projects": {}})
        add_agent(state, project, workspace, backend="echo", visibility="private",
                  description="Temporary private Echo deployment verification")

        headers = {"Authorization": "Bearer " + original["token"]}
        async with httpx.AsyncClient(base_url=hub, headers=headers, timeout=10) as client:
            catalog = await client.get("/api/catalog/projects")
            catalog.raise_for_status()
            if not any(row["id"] == project and row["status"] == "ACTIVE"
                       for row in catalog.json()):
                raise RuntimeError("测试项目未在云端目录中启用")
            agents = await client.get("/api/bridge/agents", params={"owner": owner})
            agents.raise_for_status()
            if any(row["id"] == project for row in agents.json()):
                raise RuntimeError("该账号已有同名 Agent；拒绝覆盖现有注册")
            legacy = await client.get("/api/projects", params={"owner": owner})
            legacy.raise_for_status()
            if any(row["id"] == project for row in legacy.json()):
                raise RuntimeError("该账号已有同名旧项目绑定；拒绝并行测试")

            background = asyncio.create_task(BridgeRunner(state).run())
            try:
                await wait_for_agent(client, owner, project)
                sent = await client.post("/api/bridge/messages", json={
                    "receiver": owner, "agent_id": project, "message_id": marker,
                    "content": question,
                })
                sent.raise_for_status()
                if sent.json().get("status") != "WAITING_APPROVAL":
                    raise RuntimeError("请求未进入待本人审批状态")

                print(json.dumps({
                    "hub": hub, "identity": owner, "request_id": marker,
                    "agent": project, "backend": "echo", "visibility": "private",
                    "approve": "请本人登录线上网页，在提问与请求中批准该测试请求",
                    "review": f"./.venv/bin/python -m peerlink.cli --state {state} review {marker}",
                    "send": "本人阅读草稿后如确认可分享，请在 review 命令末尾加 --send",
                    "expires_in_minutes": minutes,
                    "real_project_files_read": False,
                }, ensure_ascii=False, indent=2), flush=True)

                deadline = time.monotonic() + minutes * 60
                previous = None
                while time.monotonic() < deadline:
                    item = await client.get(f"/api/requests/{marker}")
                    item.raise_for_status()
                    status = item.json()["status"]
                    if status != previous:
                        print(json.dumps({"request_id": marker, "status": status}), flush=True)
                        previous = status
                    if status == "COMPLETED":
                        if item.json().get("response") != "echo: " + question:
                            raise AssertionError("线上最终回复与原始问题不匹配")
                        print(json.dumps({
                            "identity": owner, "request_id": marker,
                            "public_wss_downstream": "passed",
                            "reviewed_http_upstream": "passed",
                            "response_exact_match": True,
                            "real_project_files_read": False,
                        }, ensure_ascii=False, indent=2), flush=True)
                        return
                    if status in ("FAILED", "REJECTED", "CANCELLED"):
                        raise RuntimeError(f"线上测试请求结束于 {status}")
                    await asyncio.sleep(1)
                raise TimeoutError("等待本人审批和发送超时；临时 Agent 将移除")
            finally:
                background.cancel()
                with suppress(asyncio.CancelledError):
                    await background
                removed = await client.delete(f"/api/bridge/agents/{project}")
                if removed.status_code not in (200, 404):
                    print(f"警告：临时 Agent 移除失败（HTTP {removed.status_code}）", flush=True)
                else:
                    print("临时线上 Agent 已移除", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Peerlink online human-approved Bridge probe")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--project", default="ai-outbound")
    parser.add_argument("--minutes", type=int, default=45)
    args = parser.parse_args()
    if not 1 <= args.minutes <= 60:
        parser.error("--minutes 必须在 1 到 60 之间")
    asyncio.run(run_probe(args.state.expanduser().resolve(), args.owner,
                          args.project, args.minutes))


if __name__ == "__main__":
    main()
