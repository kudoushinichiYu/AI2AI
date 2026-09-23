"""Thin Relay routes: discover agents and route approved work to connected devices."""

import json
import secrets
import time
from typing import Literal, Optional

from fastapi import Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from peerlink.protocol import (AGENT_ID_PATTERN, MESSAGE_ID_PATTERN, AgentResponse,
                               DeviceHeartbeat, message_from_row)


MESSAGE_TTL_SECONDS = 24 * 60 * 60


class AgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=AGENT_ID_PATTERN)
    description: str = Field(default="", max_length=1000)
    visibility: Literal["private", "team", "allowlist"] = "private"
    allowlist: list[str] = Field(default_factory=list, max_length=50)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receiver: str = Field(min_length=1, max_length=80)
    agent_id: str = Field(pattern=AGENT_ID_PATTERN)
    content: str = Field(min_length=1, max_length=10000)
    message_id: Optional[str] = Field(default=None, pattern=MESSAGE_ID_PATTERN)
    thread_id: Optional[str] = Field(default=None, pattern=MESSAGE_ID_PATTERN)


def can_access(row, sender):
    if sender == row["owner"]:
        return True
    if row["visibility"] == "team":
        return True
    if row["visibility"] == "allowlist":
        return sender in json.loads(row["allowlist"])
    return False


class RelayManager:
    def __init__(self):
        self.connections = {}

    def online(self, device_id):
        return device_id in self.connections

    async def attach(self, device_id, socket):
        previous = self.connections.get(device_id)
        self.connections[device_id] = socket
        if previous is not None and previous is not socket:
            await previous.close(code=1001)

    def detach(self, device_id, socket):
        if self.connections.get(device_id) is socket:
            self.connections.pop(device_id, None)

    async def send(self, device_id, envelope):
        socket = self.connections.get(device_id)
        if socket is None:
            return False
        try:
            await socket.send_json(envelope)
            return True
        except (OSError, RuntimeError, WebSocketDisconnect):
            self.detach(device_id, socket)
            return False


def install_relay_routes(app, store, member, device, digest, audit_as, expire):
    manager = RelayManager()
    app.state.relay = manager

    @app.websocket("/api/bridge/ws")
    async def bridge_socket(socket: WebSocket):
        authorization = socket.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            await socket.close(code=1008)
            return
        with store.connect() as conn:
            identity = conn.execute(
                "SELECT d.id,d.owner FROM devices d JOIN users u ON u.id=d.owner "
                "WHERE d.token=? AND u.status='ACTIVE'", (digest(authorization[7:]),)
            ).fetchone()
        if identity is None:
            await socket.close(code=1008)
            return
        device_id = identity["id"]
        await socket.accept()
        await manager.attach(device_id, socket)
        try:
            await socket.send_json({"version": "1", "type": "device.hello", "device_id": device_id})
            with store.connect() as conn:
                pending = conn.execute(
                    "SELECT * FROM requests WHERE device=? AND transport='bridge' "
                    "AND status='WAITING_DEVICE' ORDER BY created", (device_id,)
                ).fetchall()
            for row in pending:
                if not await manager.send(device_id, message_from_row(row)):
                    return
            while True:
                frame = await socket.receive_text()
                if len(frame) > 50000:
                    await socket.close(code=1009)
                    return
                try:
                    payload = json.loads(frame)
                    kind = payload.get("type")
                    if kind == "device.heartbeat":
                        DeviceHeartbeat.model_validate(payload)
                        with store.connect() as conn:
                            conn.execute("UPDATE devices SET seen=? WHERE id=?", (time.time(), device_id))
                        await socket.send_json({"version": "1", "type": "device.heartbeat", "ok": True})
                    elif kind == "agent.response":
                        response = AgentResponse.model_validate(payload)
                        with store.connect() as conn:
                            row = conn.execute("SELECT device,status FROM requests WHERE id=? AND transport='bridge'",
                                               (response.message_id,)).fetchone()
                        if not row or row["device"] != device_id:
                            await socket.close(code=1008)
                            return
                    else:
                        await socket.send_json({"version": "1", "type": "agent.error", "error_code": "UNKNOWN_TYPE"})
                except (ValueError, TypeError, ValidationError, AttributeError):
                    await socket.send_json({"version": "1", "type": "agent.error", "error_code": "BAD_FRAME"})
        except WebSocketDisconnect:
            pass
        finally:
            manager.detach(device_id, socket)

    @app.put("/api/bridge/agents")
    def register_agent(body: AgentInput, current=Depends(device)):
        allowed = sorted(set(body.allowlist))
        if body.visibility != "allowlist" and allowed:
            raise HTTPException(400, "只有 allowlist 模式可以指定成员白名单")
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            catalog = conn.execute("SELECT status FROM project_catalog WHERE id=?", (body.id,)).fetchone()
            if not catalog or catalog["status"] != "ACTIVE":
                raise HTTPException(403, "项目尚未加入云端目录或未经管理员批准")
            existing = conn.execute("SELECT device FROM agent_registry WHERE owner=? AND id=?",
                                    (current["owner"], body.id)).fetchone()
            if existing and existing["device"] != current["id"]:
                raise HTTPException(409, "Agent 已绑定其他设备；先撤销旧注册")
            if allowed:
                active_users = {row["id"] for row in conn.execute(
                    "SELECT id FROM users WHERE status='ACTIVE' AND id IN (" +
                    ",".join("?" for _ in allowed) + ")", allowed)}
                if set(allowed) != active_users:
                    raise HTTPException(400, "白名单包含未激活的成员")
            conn.execute(
                "INSERT OR REPLACE INTO agent_registry(owner,id,device,description,visibility,allowlist) "
                "VALUES (?,?,?,?,?,?)",
                (current["owner"], body.id, current["id"], body.description,
                 body.visibility, json.dumps(allowed)),
            )
        return {"id": body.id, "owner": current["owner"], "online": manager.online(current["id"])}

    @app.delete("/api/bridge/agents/{agent_id}")
    def remove_agent(agent_id: str, current=Depends(device)):
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            deleted = conn.execute("DELETE FROM agent_registry WHERE owner=? AND id=? AND device=?",
                                   (current["owner"], agent_id, current["id"]))
            if not deleted.rowcount:
                raise HTTPException(404, "本机未注册该 Agent")
            rows = conn.execute("SELECT id FROM requests WHERE receiver=? AND project=? AND device=? "
                                "AND transport='bridge' AND status NOT IN ('COMPLETED','FAILED','REJECTED','CANCELLED')",
                                (current["owner"], agent_id, current["id"])).fetchall()
            for row in rows:
                conn.execute("UPDATE requests SET status='CANCELLED' WHERE id=?", (row["id"],))
                audit_as(conn, row["id"], current["owner"], "agent_removed")
        return {"ok": True}

    @app.get("/api/bridge/agents")
    def list_agents(owner: Optional[str] = None, current=Depends(member)):
        with store.connect() as conn:
            query = ("SELECT a.* FROM agent_registry a JOIN users u ON u.id=a.owner "
                     "JOIN project_catalog c ON c.id=a.id WHERE u.status='ACTIVE' AND c.status='ACTIVE'")
            params = []
            if owner:
                query += " AND a.owner=?"
                params.append(owner)
            rows = conn.execute(query + " ORDER BY a.owner,a.id", params).fetchall()
        return [{"owner": row["owner"], "id": row["id"], "description": row["description"],
                 "visibility": row["visibility"], "online": manager.online(row["device"])}
                for row in rows if can_access(row, current["owner"])]

    @app.post("/api/bridge/messages")
    async def send_message(body: MessageInput, current=Depends(member)):
        message_id = body.message_id or secrets.token_hex(12)
        thread_id = body.thread_id or message_id
        now = time.time()
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            expire(conn)
            existing = conn.execute("SELECT * FROM requests WHERE id=?", (message_id,)).fetchone()
            if existing:
                if (existing["transport"] != "bridge" or existing["sender"] != current["owner"]
                        or existing["receiver"] != body.receiver or existing["project"] != body.agent_id
                        or existing["question"] != body.content or existing["thread_id"] != thread_id):
                    raise HTTPException(409, "message_id 已用于其他内容")
                return {"id": message_id, "thread_id": thread_id, "status": existing["status"]}
            agent = conn.execute(
                "SELECT a.* FROM agent_registry a JOIN project_catalog c ON c.id=a.id "
                "JOIN users u ON u.id=a.owner WHERE a.owner=? AND a.id=? "
                "AND c.status='ACTIVE' AND u.status='ACTIVE'",
                (body.receiver, body.agent_id),
            ).fetchone()
            if not agent or not can_access(agent, current["owner"]):
                raise HTTPException(404, "Agent 不存在或无权访问")
            if not manager.online(agent["device"]):
                raise HTTPException(409, "DEVICE_OFFLINE")
            conn.execute(
                "INSERT INTO requests(id,sender,receiver,project,device,question,status,created,"
                "transport,thread_id,retain_until) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (message_id, current["owner"], body.receiver, body.agent_id, agent["device"],
                 body.content, "WAITING_APPROVAL", now, "bridge", thread_id, now + MESSAGE_TTL_SECONDS),
            )
            audit_as(conn, message_id, current["owner"], "created")
        announced = await manager.send(agent["device"], {
            "version": "1", "type": "agent.approval_requested", "message_id": message_id,
            "sender": current["owner"], "agent_id": body.agent_id,
        })
        if not announced:
            with store.connect() as conn:
                conn.execute("UPDATE requests SET status='FAILED',error='DEVICE_OFFLINE' WHERE id=?",
                             (message_id,))
                audit_as(conn, message_id, "system", "delivery_failed")
            return {"id": message_id, "thread_id": thread_id,
                    "status": "FAILED", "error": "DEVICE_OFFLINE"}
        return {"id": message_id, "thread_id": thread_id, "status": "WAITING_APPROVAL"}

    return manager
