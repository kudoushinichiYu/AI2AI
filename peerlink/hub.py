import hashlib
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        with self.connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL DEFAULT 0,
                    credential_kind TEXT NOT NULL DEFAULT 'LOGIN'
                );
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                    token TEXT NOT NULL UNIQUE, seen REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    owner TEXT NOT NULL, id TEXT NOT NULL, device TEXT NOT NULL,
                    path TEXT NOT NULL, description TEXT NOT NULL, runtime TEXT NOT NULL,
                    PRIMARY KEY(owner, id)
                );
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, sender TEXT NOT NULL, receiver TEXT NOT NULL,
                    project TEXT NOT NULL, device TEXT NOT NULL, question TEXT NOT NULL,
                    status TEXT NOT NULL, created REAL NOT NULL, lease TEXT,
                    expires REAL, response TEXT, error TEXT
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, request TEXT NOT NULL, actor TEXT NOT NULL,
                    event TEXT NOT NULL, created REAL NOT NULL
                );
            """)
        self.migrate()

    def migrate(self):
        with self.connect() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
            if "status" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'ACTIVE'")
            if "is_admin" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            if "created" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN created REAL NOT NULL DEFAULT 0")
            if "credential_kind" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN credential_kind TEXT NOT NULL DEFAULT 'LOGIN'")
            conn.execute("UPDATE users SET status='ACTIVE' WHERE status=''")
            conn.execute("UPDATE users SET is_admin=1 "
                         "WHERE id=(SELECT id FROM users ORDER BY created,rowid LIMIT 1)")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def add_user(self, name):
        raise NotImplementedError("Use register_user or create_admin instead")

    def register_user(self, name):
        token = secrets.token_urlsafe(32)
        with self.connect() as conn:
            conn.execute("INSERT INTO users(id,token,status,is_admin,created) VALUES (?,?,?,?,?)",
                         (name, digest(token), "PENDING", 0, time.time()))
        return token

    def request_registration(self, name):
        receipt = secrets.token_urlsafe(32)
        with self.connect() as conn:
            conn.execute("INSERT INTO users(id,token,status,is_admin,created,credential_kind) "
                         "VALUES (?,?,?,?,?,?)",
                         (name, digest(receipt), "PENDING", 0, time.time(), "REGISTRATION"))
        return receipt

    def claim_registration(self, name, receipt):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT status,credential_kind FROM users WHERE id=? AND token=?",
                (name, digest(receipt)),
            ).fetchone()
            if not row or row["credential_kind"] != "REGISTRATION":
                raise PermissionError("注册回执无效或已使用")
            if row["status"] == "PENDING":
                return {"username": name, "status": "PENDING"}
            if row["status"] != "ACTIVE":
                raise PermissionError("注册申请不可用")
            login_token = secrets.token_urlsafe(32)
            conn.execute(
                "UPDATE users SET token=?,credential_kind='LOGIN' WHERE id=? AND token=?",
                (digest(login_token), name, digest(receipt)),
            )
            return {"username": name, "status": "ACTIVE", "token": login_token}

    def create_admin(self, name):
        token = secrets.token_urlsafe(32)
        with self.connect() as conn:
            if conn.execute("SELECT 1 FROM users WHERE id=?", (name,)).fetchone():
                raise ValueError("用户已存在")
            conn.execute("INSERT INTO users(id,token,status,is_admin,created) VALUES (?,?,?,?,?)",
                         (name, digest(token), "ACTIVE", 1, time.time()))
        return token

    def approve_user(self, name):
        with self.connect() as conn:
            row = conn.execute("SELECT status FROM users WHERE id=?", (name,)).fetchone()
            if not row:
                raise KeyError("用户不存在")
            if row["status"] != "PENDING":
                raise ValueError("用户不在待审批状态")
            conn.execute("UPDATE users SET status='ACTIVE' WHERE id=?", (name,))

    def reject_user(self, name):
        with self.connect() as conn:
            row = conn.execute("SELECT status FROM users WHERE id=?", (name,)).fetchone()
            if not row:
                raise KeyError("用户不存在")
            if row["status"] != "PENDING":
                raise ValueError("用户不在待审批状态")
            conn.execute("DELETE FROM users WHERE id=?", (name,))


class DeviceInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProjectInput(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    path: str = Field(min_length=1, max_length=2000)
    description: str = Field(default="", max_length=1000)
    runtime: Literal["mock", "codex-docker"] = "mock"


class QuestionInput(BaseModel):
    receiver: str = Field(min_length=1, max_length=80)
    project: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=12000)


class DecisionInput(BaseModel):
    action: Literal["approve", "reject", "cancel"]

class RegistrationInput(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9._-]{1,80}$")

class UserDecisionInput(BaseModel):
    action: Literal["approve", "reject"]

class RegistrationStatusInput(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9._-]{1,80}$")
    receipt: str = Field(min_length=1, max_length=200)


class LeaseInput(BaseModel):
    lease: str = Field(min_length=1, max_length=200)


class ResultInput(LeaseInput):
    action: Literal["draft_ready", "send", "reject", "fail"]
    content: Optional[str] = Field(default=None, max_length=100000)


def create_app(db_path=None):
    store = Store(db_path or os.environ.get("PEERLINK_DB", ".peerlink/hub.db"))
    app = FastAPI(title="Peerlink Collaboration", version="0.1.0")
    app.state.store = store

    def actor(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "需要 Bearer Token")
        token = digest(authorization[7:])
        with store.connect() as conn:
            row = conn.execute("SELECT id,is_admin FROM users "
                               "WHERE token=? AND status='ACTIVE' AND credential_kind='LOGIN'", (token,)).fetchone()
            if row:
                return {"kind": "user", "owner": row["id"], "id": row["id"]}
            row = conn.execute("SELECT id,owner FROM devices WHERE token=?", (token,)).fetchone()
            if row:
                return {"kind": "device", "owner": row["owner"], "id": row["id"]}
        raise HTTPException(401, "凭证无效")

    def user(current=Depends(actor)):
        if current["kind"] != "user":
            raise HTTPException(403, "需要用户凭证，设备不能代替用户审批")
        return current

    def device(current=Depends(actor)):
        if current["kind"] != "device":
            raise HTTPException(403, "需要设备凭证")
        return current

    def admin(current=Depends(user)):
        with store.connect() as conn:
            if not conn.execute("SELECT is_admin FROM users WHERE id=?", (current["id"],)).fetchone()[0]:
                raise HTTPException(403, "需要管理员权限")
        return current

    def event(conn, request_id, current, action):
        conn.execute("INSERT INTO audit(request,actor,event,created) VALUES (?,?,?,?)",
                     (request_id, current["id"], action, time.time()))

    def expire(conn):
        conn.execute("UPDATE requests SET status='FAILED', error='设备执行租约超时；请重新发起请求' "
                     "WHERE status IN ('RUNNING','WAITING_OUTPUT_APPROVAL') AND expires < ?",
                     (time.time(),))

    def load(conn, request_id):
        row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise HTTPException(404, "请求不存在")
        return row

    def check_lease(row, current, lease):
        if row["device"] != current["id"] or row["receiver"] != current["owner"]:
            raise HTTPException(403, "不是该设备的任务")
        if row["status"] not in ("RUNNING", "WAITING_OUTPUT_APPROVAL"):
            raise HTTPException(409, "任务不再可执行")
        if row["lease"] != lease or row["expires"] < time.time():
            raise HTTPException(409, "租约失效")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(Path(__file__).parent / "static/index.html")

    @app.get("/app.js", include_in_schema=False)
    def javascript():
        return FileResponse(Path(__file__).parent / "static/app.js")

    @app.get("/health")
    def health():
        with store.connect() as conn:
            conn.execute("SELECT 1")
        return {"ok": True}

    @app.get("/api/me")
    def me(current=Depends(user)):
        with store.connect() as conn:
            role = conn.execute("SELECT is_admin FROM users WHERE id=?", (current["id"],)).fetchone()[0]
        return {**current, "is_admin": bool(role)}

    @app.post("/api/register")
    def register(body: RegistrationInput):
        try:
            receipt = store.request_registration(body.username)
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "用户名已被占用") from error
        return {"username": body.username, "receipt": receipt, "status": "PENDING"}

    @app.post("/api/register/status")
    def registration_status(body: RegistrationStatusInput):
        try:
            return store.claim_registration(body.username, body.receipt)
        except PermissionError as error:
            raise HTTPException(401, str(error)) from error

    @app.get("/api/admin/users")
    def users(current=Depends(admin)):
        with store.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id,status,is_admin,created FROM users ORDER BY CASE WHEN status='PENDING' THEN 0 ELSE 1 END,created")]

    @app.post("/api/admin/users/{username}/decision")
    def user_decision(username: str, body: UserDecisionInput, current=Depends(admin)):
        try:
            if body.action == "approve":
                store.approve_user(username)
            else:
                store.reject_user(username)
        except KeyError as error:
            raise HTTPException(404, "用户不存在") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"username": username, "status": "ACTIVE" if body.action == "approve" else "REMOVED"}

    @app.get("/api/peers")
    def peers(current=Depends(user)):
        with store.connect() as conn:
            return [row["id"] for row in conn.execute(
                "SELECT id FROM users WHERE status='ACTIVE' ORDER BY id")]

    @app.post("/api/devices")
    def register_device(body: DeviceInput, current=Depends(user)):
        token, device_id = secrets.token_urlsafe(32), secrets.token_hex(12)
        with store.connect() as conn:
            conn.execute("INSERT INTO devices VALUES (?,?,?,?,?)",
                         (device_id, current["owner"], body.name, digest(token), time.time()))
        return {"id": device_id, "token": token, "owner": current["owner"]}

    @app.get("/api/devices")
    def devices(current=Depends(user)):
        with store.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id,name,seen FROM devices WHERE owner=?", (current["owner"],))]

    @app.delete("/api/devices/{device_id}")
    def revoke_device(device_id: str, current=Depends(user)):
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM devices WHERE id=? AND owner=?", (device_id, current["owner"]))
            conn.execute("DELETE FROM projects WHERE device=? AND owner=?", (device_id, current["owner"]))
            conn.execute("UPDATE requests SET status='CANCELLED' WHERE device=? AND receiver=? "
                         "AND status NOT IN ('COMPLETED','FAILED','REJECTED','CANCELLED')",
                         (device_id, current["owner"]))
        return {"ok": True}

    @app.put("/api/projects")
    def register_project(body: ProjectInput, current=Depends(device)):
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM projects WHERE owner=? AND id=?",
                               (current["owner"], body.id)).fetchone()
            if row and row["device"] != current["id"]:
                raise HTTPException(409, "该项目已绑定其他设备；先撤销旧注册")
            if row and any(row[key] != getattr(body, key) for key in ("path", "runtime")):
                raise HTTPException(409, "路径或 Runtime 变更需要先撤销注册并重新授权")
            conn.execute("INSERT OR REPLACE INTO projects VALUES (?,?,?,?,?,?)",
                         (current["owner"], body.id, current["id"], body.path, body.description, body.runtime))
        return {"ok": True}

    @app.delete("/api/projects/{project_id}")
    def remove_project(project_id: str, current=Depends(device)):
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM projects WHERE owner=? AND id=? AND device=?",
                         (current["owner"], project_id, current["id"]))
            conn.execute("UPDATE requests SET status='CANCELLED' WHERE receiver=? AND project=? "
                         "AND device=? AND status NOT IN ('COMPLETED','FAILED','REJECTED','CANCELLED')",
                         (current["owner"], project_id, current["id"]))
        return {"ok": True}

    @app.get("/api/projects")
    def projects(owner: str, current=Depends(user)):
        columns = "id,description,runtime,device"
        if owner == current["owner"]:
            columns += ",path"
        with store.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT " + columns + " FROM projects WHERE owner=?", (owner,))]

    @app.post("/api/requests")
    def ask(body: QuestionInput, current=Depends(user)):
        request_id = secrets.token_hex(12)
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            project = conn.execute("SELECT * FROM projects WHERE owner=? AND id=?",
                                   (body.receiver, body.project)).fetchone()
            if not project:
                raise HTTPException(404, "项目未注册")
            conn.execute("INSERT INTO requests(id,sender,receiver,project,device,question,status,created) "
                         "VALUES (?,?,?,?,?,?,?,?)", (request_id, current["owner"], body.receiver,
                         body.project, project["device"], body.question, "WAITING_APPROVAL", time.time()))
            event(conn, request_id, current, "created")
        return {"id": request_id, "status": "WAITING_APPROVAL"}

    @app.get("/api/requests")
    def requests(current=Depends(user)):
        with store.connect() as conn:
            expire(conn)
            rows = conn.execute("SELECT id,sender,receiver,project,question,status,created,response,error "
                                "FROM requests WHERE sender=? OR receiver=? ORDER BY created DESC LIMIT 200",
                                (current["owner"], current["owner"]))
            return [dict(row) for row in rows]

    @app.get("/api/requests/{request_id}")
    def get_request(request_id: str, current=Depends(user)):
        with store.connect() as conn:
            expire(conn)
            row = dict(load(conn, request_id))
            if current["owner"] not in (row["sender"], row["receiver"]):
                raise HTTPException(403, "无权查看")
            for key in ("lease", "expires", "device"):
                row.pop(key)
            return row

    @app.post("/api/requests/{request_id}/decision")
    def decision(request_id: str, body: DecisionInput, current=Depends(user)):
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = load(conn, request_id)
            if body.action == "cancel":
                if row["sender"] != current["owner"]:
                    raise HTTPException(403, "仅发送方可取消")
                if row["status"] in ("COMPLETED", "FAILED", "REJECTED", "CANCELLED"):
                    raise HTTPException(409, "任务已结束")
                status = "CANCELLED"
            else:
                if row["receiver"] != current["owner"]:
                    raise HTTPException(403, "仅接收方可审批")
                if row["status"] != "WAITING_APPROVAL":
                    raise HTTPException(409, "任务已审批")
                status = "WAITING_DEVICE" if body.action == "approve" else "REJECTED"
            conn.execute("UPDATE requests SET status=? WHERE id=?", (status, request_id))
            event(conn, request_id, current, body.action)
        return {"status": status}

    @app.post("/api/connector/claim")
    def claim(current=Depends(device)):
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            expire(conn)
            conn.execute("UPDATE devices SET seen=? WHERE id=?", (time.time(), current["id"]))
            row = conn.execute("SELECT * FROM requests WHERE device=? AND receiver=? "
                               "AND status='WAITING_DEVICE' ORDER BY created LIMIT 1",
                               (current["id"], current["owner"])).fetchone()
            if not row:
                return None
            lease = secrets.token_urlsafe(24)
            conn.execute("UPDATE requests SET status='RUNNING',lease=?,expires=? WHERE id=?",
                         (lease, time.time() + 120, row["id"]))
            event(conn, row["id"], current, "claimed")
            return {"id": row["id"], "receiver": row["receiver"], "project": row["project"],
                    "device": row["device"], "question": row["question"], "lease": lease}

    @app.post("/api/connector/{request_id}/heartbeat")
    def heartbeat(request_id: str, body: LeaseInput, current=Depends(device)):
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = load(conn, request_id)
            check_lease(row, current, body.lease)
            conn.execute("UPDATE requests SET expires=? WHERE id=?", (time.time() + 120, request_id))
            conn.execute("UPDATE devices SET seen=? WHERE id=?", (time.time(), current["id"]))
        return {"ok": True}

    @app.post("/api/connector/{request_id}/result")
    def result(request_id: str, body: ResultInput, current=Depends(device)):
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = load(conn, request_id)
            check_lease(row, current, body.lease)
            if body.action != "send" and body.content is not None:
                raise HTTPException(400, "草稿或错误正文不得上传")
            if body.action == "draft_ready":
                if row["status"] != "RUNNING":
                    raise HTTPException(409, "状态错误")
                status, content = "WAITING_OUTPUT_APPROVAL", None
            elif body.action == "send":
                if row["status"] != "WAITING_OUTPUT_APPROVAL" or not body.content or not body.content.strip():
                    raise HTTPException(409, "需要本地确认后的非空答案")
                status, content = "COMPLETED", body.content
            else:
                status, content = ("REJECTED" if body.action == "reject" else "FAILED"), None
            conn.execute("UPDATE requests SET status=?,response=? WHERE id=?", (status, content, request_id))
            event(conn, request_id, current, body.action)
        return {"status": status}

    return app
