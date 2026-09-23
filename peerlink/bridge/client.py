"""Outbound WebSocket Bridge. It never listens on a local port."""

import asyncio
import json
import threading
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from peerlink.bridge.backends import create_backend
from peerlink.bridge.registry import allowed_sender, load_agents, validate_workspace
from peerlink.bridge.storage import BridgeState
from peerlink.connector import configured, keep_leases, notify, save_json, work
from peerlink.protocol import AgentMessage, AgentResponse


def websocket_url(hub):
    parsed = urlparse(hub)
    return parsed._replace(scheme="wss" if parsed.scheme == "https" else "ws",
                           path="/api/bridge/ws", params="", query="", fragment="").geturl()


class BridgeRunner:
    def __init__(self, state):
        self.state = Path(state)
        self.config, self.client = configured(self.state)
        self.storage = BridgeState(self.state / "bridge.db")
        self.tasks = {}
        self.locks = {}

    def register_agents(self):
        for agent in load_agents(self.state).values():
            metadata = {key: agent[key] for key in ("id", "description", "visibility", "allowlist")}
            try:
                self.client.call("PUT", "/api/bridge/agents", json=metadata)
            except httpx.HTTPError as error:
                status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else "连接错误"
                print(f"Agent {agent['id']} 注册失败：HTTP {status}；"
                      "检查云端项目目录和设备状态。", flush=True)

    async def handle_message(self, payload, socket):
        try:
            message = AgentMessage.model_validate(payload)
        except ValidationError:
            return
        if message.receiver != self.config["owner"]:
            return
        task = await asyncio.to_thread(self.client.call, "POST", "/api/connector/claim",
                                       json={"request_id": message.message_id, "transport": "bridge"})
        if not task:
            return
        if any((task.get("id") != message.message_id,
                task.get("sender") != message.sender,
                task.get("receiver") != message.receiver,
                task.get("project") != message.agent_id,
                task.get("question") != message.content,
                task.get("thread_id") != message.thread_id,
                task.get("transport") != "bridge",
                task.get("device") != self.config["id"])):
            await self._fail(task)
            return
        path = self.state / "drafts" / (message.message_id + ".pending.json")
        if not self.storage.reserve(message.message_id, message.agent_id, message.sender):
            await self._fail(task)
            return
        try:
            save_json(path, task)
            agent = load_agents(self.state).get(message.agent_id)
            if not agent or not allowed_sender(agent, message.sender, self.config["owner"]):
                raise ValueError("本地 Agent 权限不允许此成员访问")
            if validate_workspace(agent["workspace"]) != agent["workspace"]:
                raise ValueError("Agent 项目路径已变更")
            lock = self.locks.setdefault(message.agent_id, asyncio.Lock())
            async with lock:
                backend = create_backend(agent["backend"])
                mapped_thread = self.storage.thread(message.thread_id, message.agent_id, message.sender)
                answer = await asyncio.wait_for(
                    backend.answer(message.content, agent["workspace"], mapped_thread), timeout=300,
                )
            if not answer.text.strip() or len(answer.text) > 100000:
                raise ValueError("Agent 答案为空或超过长度限制")
            task["answer"] = answer.text
            task["runtime"] = agent["backend"]
            save_json(path, task)
            await asyncio.to_thread(
                self.client.call, "POST", f"/api/connector/{message.message_id}/result",
                json={"lease": task["lease"], "action": "draft_ready"},
            )
            if answer.thread_id:
                self.storage.map_thread(message.thread_id, message.agent_id, message.sender,
                                        answer.thread_id)
            self.storage.finish(message.message_id, "DRAFT_READY")
            notify("Peerlink 草稿已就绪", f"{message.agent_id} 的答案等待你审核发送")
            try:
                await socket.send(json.dumps(AgentResponse(
                    message_id=message.message_id, status="draft_ready").model_dump()))
            except Exception:
                # The HTTP result already committed the draft. A dropped socket must
                # not turn a reviewable local answer into a failed request.
                pass
        except (Exception, asyncio.CancelledError):
            self.storage.finish(message.message_id, "FAILED")
            await self._fail(task)
            if path.exists():
                path.rename(path.with_suffix(".stopped"))
            notify("Peerlink 本地任务未完成", f"{message.agent_id} 的请求未生成可发送草稿")
            try:
                await socket.send(json.dumps(AgentResponse(
                    message_id=message.message_id, status="failed", error_code="LOCAL_FAILURE"
                ).model_dump()))
            except Exception:
                pass

    async def _fail(self, task):
        try:
            await asyncio.to_thread(
                self.client.call, "POST", f"/api/connector/{task['id']}/result",
                json={"lease": task["lease"], "action": "fail"},
            )
        except (httpx.HTTPError, KeyError):
            pass

    async def _heartbeat(self, socket):
        while True:
            await asyncio.sleep(30)
            await socket.send(json.dumps({"version": "1", "type": "device.heartbeat"}))

    async def run(self, auth_dir=None):
        try:
            from websockets.asyncio.client import connect
        except ImportError as error:
            raise RuntimeError("缺少 websockets 依赖；请更新 Peerlink 客户端") from error
        stopped = threading.Event()
        keeper_config, keeper_client = configured(self.state)
        keeper = threading.Thread(target=keep_leases,
                                  args=(self.state, keeper_client, stopped), daemon=True)
        keeper.start()
        # Keep older Mock/Docker/desktop-Skill registrations working during migration.
        if self.config.get("projects"):
            threading.Thread(target=work, args=(self.state, False, auth_dir), daemon=True).start()
        delay = 1
        try:
            while True:
                try:
                    await asyncio.to_thread(self.register_agents)
                    async with connect(
                        websocket_url(self.config["hub"]),
                        additional_headers={"Authorization": "Bearer " + self.config["token"]},
                        max_size=50000,
                    ) as socket:
                        delay = 1
                        heartbeat = asyncio.create_task(self._heartbeat(socket))
                        try:
                            async for raw in socket:
                                payload = json.loads(raw)
                                kind = payload.get("type")
                                if kind == "agent.message":
                                    message_id = payload.get("message_id")
                                    if message_id not in self.tasks:
                                        running = asyncio.create_task(self.handle_message(payload, socket))
                                        self.tasks[message_id] = running
                                        running.add_done_callback(lambda _, mid=message_id: self.tasks.pop(mid, None))
                                elif kind == "agent.approval_requested":
                                    notify("Peerlink 收到新问题", f"{payload.get('sender', '成员')} 想询问 "
                                           f"{payload.get('agent_id', '项目')}；请在网页审批")
                                elif kind == "agent.cancel":
                                    running = self.tasks.get(payload.get("message_id"))
                                    if running:
                                        running.cancel()
                        finally:
                            heartbeat.cancel()
                            await asyncio.gather(heartbeat, return_exceptions=True)
                except (OSError, httpx.HTTPError, ValueError, RuntimeError, json.JSONDecodeError) as error:
                    print(f"Peerlink Bridge 连接中断：{type(error).__name__}；稍后重连。", flush=True)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
        finally:
            stopped.set()
            keeper.join(timeout=20)
            keeper_client.http.close()
            self.client.http.close()


def run_bridge(state, auth_dir=None):
    asyncio.run(BridgeRunner(state).run(auth_dir))
