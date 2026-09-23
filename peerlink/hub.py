import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from peerlink import __version__


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def audit_as(conn, request_id, actor, action):
    conn.execute("INSERT INTO audit(request,actor,event,created) VALUES (?,?,?,?)",
                 (request_id, actor, action, time.time()))


def cancel_requests(conn, where, params, actor, action):
    rows = conn.execute("SELECT id FROM requests WHERE (" + where + ")" +
                        " AND status NOT IN ('COMPLETED','FAILED','REJECTED','CANCELLED')", params).fetchall()
    if not rows:
        return 0
    conn.execute("UPDATE requests SET status='CANCELLED' WHERE (" + where + ")" +
                 " AND status NOT IN ('COMPLETED','FAILED','REJECTED','CANCELLED')", params)
    for row in rows:
        audit_as(conn, row["id"], actor, action)
    return len(rows)


def password_hash(password):
    salt = secrets.token_bytes(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
    return f"pbkdf2_sha256$310000${salt.hex()}${value.hex()}"


def password_matches(password, encoded):
    try:
        _, rounds, salt, expected = encoded.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual.hex(), expected)
    except (AttributeError, ValueError):
        return False


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
                CREATE TABLE IF NOT EXISTS project_catalog (
                    id TEXT PRIMARY KEY, description TEXT NOT NULL,
                    status TEXT NOT NULL, created_by TEXT NOT NULL, created REAL NOT NULL
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
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    expires REAL NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    expires REAL NOT NULL, created REAL NOT NULL
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
            if "password_hash" not in columns:
                conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            conn.execute("UPDATE users SET status='ACTIVE' WHERE status=''")
            conn.execute("UPDATE users SET is_admin=1 "
                         "WHERE id=(SELECT id FROM users ORDER BY created,rowid LIMIT 1)")
            conn.execute("INSERT OR IGNORE INTO project_catalog(id,description,status,created_by,created) "
                         "SELECT id,MAX(description),'ACTIVE',MIN(owner),? FROM projects GROUP BY id",
                         (time.time(),))

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

    def request_registration(self, name, password):
        with self.connect() as conn:
            conn.execute("INSERT INTO users(id,token,status,is_admin,created,credential_kind,password_hash) "
                         "VALUES (?,?,?,?,?,?,?)", (name, digest(secrets.token_urlsafe(32)),
                         "PENDING", 0, time.time(), "PASSWORD", password_hash(password)))

    def set_password(self, name, password):
        with self.connect() as conn:
            if not conn.execute("SELECT 1 FROM users WHERE id=?", (name,)).fetchone():
                raise KeyError(name)
            conn.execute("UPDATE users SET password_hash=?,credential_kind='PASSWORD',token=? WHERE id=?",
                         (password_hash(password), digest(secrets.token_urlsafe(32)), name))
            conn.execute("DELETE FROM sessions WHERE owner=?", (name,))

    def create_admin(self, name):
        token = secrets.token_urlsafe(32)
        with self.connect() as conn:
            if conn.execute("SELECT 1 FROM users WHERE id=?", (name,)).fetchone():
                raise ValueError("用户已存在")
            conn.execute("INSERT INTO users(id,token,status,is_admin,created) VALUES (?,?,?,?,?)",
                         (name, digest(token), "ACTIVE", 1, time.time()))
        return token

    def create_admin_password(self, name, password):
        with self.connect() as conn:
            if conn.execute("SELECT 1 FROM users WHERE id=?", (name,)).fetchone():
                raise ValueError("用户已存在")
            conn.execute("INSERT INTO users(id,token,status,is_admin,created,credential_kind,password_hash) "
                         "VALUES (?,?,?,?,?,?,?)", (name, digest(secrets.token_urlsafe(32)),
                         "ACTIVE", 1, time.time(), "PASSWORD", password_hash(password)))

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

    def disable_user(self, name, actor):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status,is_admin FROM users WHERE id=?", (name,)).fetchone()
            if not row:
                raise KeyError("User not found")
            if row["status"] != "ACTIVE":
                raise ValueError("User is not active")
            if row["is_admin"]:
                admins = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=1 AND status='ACTIVE'").fetchone()[0]
                if admins <= 1:
                    raise ValueError("Cannot disable the last active administrator")
            cancel_requests(conn, "sender=? OR receiver=?", (name, name), actor, "user_disabled")
            conn.execute("DELETE FROM sessions WHERE owner=?", (name,))
            conn.execute("DELETE FROM pairing_codes WHERE owner=?", (name,))
            conn.execute("DELETE FROM projects WHERE owner=?", (name,))
            conn.execute("DELETE FROM devices WHERE owner=?", (name,))
            conn.execute("UPDATE users SET status='DISABLED',token=? WHERE id=?",
                         (digest(secrets.token_urlsafe(32)), name))

    def enable_user(self, name):
        with self.connect() as conn:
            row = conn.execute("SELECT status FROM users WHERE id=?", (name,)).fetchone()
            if not row:
                raise KeyError("User not found")
            if row["status"] != "DISABLED":
                raise ValueError("User is not disabled")
            conn.execute("UPDATE users SET status='ACTIVE' WHERE id=?", (name,))


class DeviceInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class PairDeviceInput(DeviceInput):
    code: str = Field(min_length=8, max_length=200)


class ProjectInput(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    path: str = Field(min_length=1, max_length=2000)
    description: str = Field(default="", max_length=1000)
    runtime: Literal["mock", "codex-docker"] = "mock"


class CatalogProjectInput(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    description: str = Field(min_length=1, max_length=1000)


class CatalogDecisionInput(BaseModel):
    action: Literal["approve", "reject", "retire", "activate"]


class QuestionInput(BaseModel):
    receiver: str = Field(min_length=1, max_length=80)
    project: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=12000)


class DecisionInput(BaseModel):
    action: Literal["approve", "reject", "cancel"]

class RegistrationInput(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9._-]{1,80}$")
    password: str = Field(min_length=10, max_length=128)

class LoginInput(RegistrationInput):
    pass

class UserDecisionInput(BaseModel):
    action: Literal["approve", "reject", "disable", "enable"]

class PasswordChangeInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)

class LeaseInput(BaseModel):
    lease: str = Field(min_length=1, max_length=200)


class ResultInput(LeaseInput):
    action: Literal["draft_ready", "send", "reject", "fail"]
    content: Optional[str] = Field(default=None, max_length=100000)


def create_app(db_path=None):
    store = Store(db_path or os.environ.get("PEERLINK_DB", ".peerlink/hub.db"))
    app = FastAPI(title="Peerlink Collaboration", version=__version__)
    app.state.store = store

    def actor(authorization: str = Header(default=""), peerlink_session: str = Cookie(default="")):
        with store.connect() as conn:
            if peerlink_session:
                row = conn.execute("SELECT u.id FROM sessions s JOIN users u ON u.id=s.owner "
                                   "WHERE s.token=? AND s.expires>? AND u.status='ACTIVE'",
                                   (digest(peerlink_session), time.time())).fetchone()
                if row:
                    return {"kind": "user", "owner": row["id"], "id": row["id"]}
            if authorization.startswith("Bearer "):
                token = digest(authorization[7:])
                row = conn.execute("SELECT id FROM users WHERE token=? AND status='ACTIVE' "
                                   "AND credential_kind='LOGIN'", (token,)).fetchone()
                if row:
                    return {"kind": "user", "owner": row["id"], "id": row["id"]}
                row = conn.execute("SELECT d.id,d.owner FROM devices d JOIN users u ON u.id=d.owner "
                                   "WHERE d.token=? AND u.status='ACTIVE'", (token,)).fetchone()
                if row:
                    return {"kind": "device", "owner": row["owner"], "id": row["id"]}
        raise HTTPException(401, "凭证无效")

    def user(current=Depends(actor)):
        if current["kind"] != "user":
            raise HTTPException(403, "需要用户凭证，设备不能代替用户审批")
        return current

    def member(current=Depends(actor)):
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
        audit_as(conn, request_id, current["id"], action)

    def expire(conn):
        now = time.time()
        rows = conn.execute("SELECT id FROM requests WHERE status IN ('RUNNING','WAITING_OUTPUT_APPROVAL') "
                            "AND expires < ?", (now,)).fetchall()
        conn.execute("UPDATE requests SET status='FAILED', error='设备执行租约超时；请重新发起请求' "
                     "WHERE status IN ('RUNNING','WAITING_OUTPUT_APPROVAL') AND expires < ?",
                     (now,))
        for row in rows:
            audit_as(conn, row["id"], "system", "lease_expired")

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

    @app.get("/downloads/peerlink.whl", include_in_schema=False)
    @app.get(f"/downloads/peerlink-{__version__}-py3-none-any.whl", include_in_schema=False)
    def client_package():
        filename = f"peerlink-{__version__}-py3-none-any.whl"
        default = Path(store.path).resolve().parent.parent / "downloads" / filename
        package = Path(os.environ.get("PEERLINK_CLIENT_PACKAGE", default))
        if not package.is_file():
            raise HTTPException(404, "客户端安装包尚未发布")
        return FileResponse(package, media_type="application/octet-stream", filename=filename)

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
            store.request_registration(body.username, body.password)
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "用户名已被占用") from error
        return {"username": body.username, "status": "PENDING"}

    @app.post("/api/login")
    def login(body: LoginInput, request: Request, response: Response):
        with store.connect() as conn:
            row = conn.execute("SELECT status,password_hash FROM users WHERE id=?", (body.username,)).fetchone()
            if not row or not password_matches(body.password, row["password_hash"]):
                raise HTTPException(401, "用户名或密码错误")
            if row["status"] == "PENDING":
                raise HTTPException(403, "账户正在等待管理员审批")
            if row["status"] != "ACTIVE":
                raise HTTPException(403, "账户已停用，请联系管理员")
            session = secrets.token_urlsafe(32)
            conn.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
            conn.execute("INSERT INTO sessions(token,owner,expires,created) VALUES (?,?,?,?)",
                         (digest(session), body.username, time.time() + 604800, time.time()))
        response.set_cookie("peerlink_session", session, max_age=604800, httponly=True,
                            secure=request.url.scheme == "https", samesite="lax", path="/")
        return {"username": body.username, "ok": True}

    @app.post("/api/account/password")
    def change_password(body: PasswordChangeInput, response: Response, current=Depends(user)):
        with store.connect() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE id=?", (current["owner"],)).fetchone()
            if not row or not password_matches(body.current_password, row["password_hash"]):
                raise HTTPException(401, "当前密码不正确")
        store.set_password(current["owner"], body.new_password)
        response.delete_cookie("peerlink_session", path="/")
        return {"ok": True, "sessions_revoked": True}

    @app.post("/api/sessions/revoke")
    def revoke_sessions(response: Response, current=Depends(user)):
        with store.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM sessions WHERE owner=?", (current["owner"],)).fetchone()[0]
            conn.execute("DELETE FROM sessions WHERE owner=?", (current["owner"],))
        response.delete_cookie("peerlink_session", path="/")
        return {"ok": True, "revoked": count}

    @app.post("/api/logout")
    def logout(response: Response, peerlink_session: str = Cookie(default="")):
        if peerlink_session:
            with store.connect() as conn:
                conn.execute("DELETE FROM sessions WHERE token=?", (digest(peerlink_session),))
        response.delete_cookie("peerlink_session", path="/")
        return {"ok": True}

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
            elif body.action == "reject":
                store.reject_user(username)
            elif body.action == "disable":
                if username == current["owner"]:
                    raise ValueError("不能停用当前登录的管理员账号")
                store.disable_user(username, current["owner"])
            else:
                store.enable_user(username)
        except KeyError as error:
            raise HTTPException(404, "用户不存在") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        status = {"approve": "ACTIVE", "reject": "REMOVED", "disable": "DISABLED", "enable": "ACTIVE"}[body.action]
        return {"username": username, "status": status}

    @app.get("/api/peers")
    def peers(current=Depends(member)):
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

    @app.post("/api/pairing-codes")
    def create_pairing_code(current=Depends(user)):
        code = secrets.token_urlsafe(18)
        now = time.time()
        with store.connect() as conn:
            conn.execute("DELETE FROM pairing_codes WHERE expires<=? OR owner=?", (now, current["owner"]))
            conn.execute("INSERT INTO pairing_codes VALUES (?,?,?,?)",
                         (digest(code), current["owner"], now + 600, now))
        return {"code": code, "expires_in": 600}

    @app.post("/api/device-pair")
    def pair_device(body: PairDeviceInput):
        token, device_id, now = secrets.token_urlsafe(32), secrets.token_hex(12), time.time()
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT owner FROM pairing_codes WHERE code=? AND expires>?",
                               (digest(body.code), now)).fetchone()
            if not row:
                raise HTTPException(401, "配对码无效或已过期")
            conn.execute("DELETE FROM pairing_codes WHERE code=?", (digest(body.code),))
            conn.execute("INSERT INTO devices VALUES (?,?,?,?,?)",
                         (device_id, row["owner"], body.name, digest(token), now))
        return {"id": device_id, "token": token, "owner": row["owner"]}

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
            cancel_requests(conn, "device=? AND receiver=?", (device_id, current["owner"]),
                            current["owner"], "device_revoked")
        return {"ok": True}

    @app.get("/api/catalog/projects")
    def catalog_projects(current=Depends(member)):
        with store.connect() as conn:
            role = conn.execute("SELECT is_admin FROM users WHERE id=?", (current["owner"],)).fetchone()
            if role and role[0]:
                rows = conn.execute("SELECT id,description,status,created_by,created FROM project_catalog "
                                    "ORDER BY CASE WHEN status='PENDING' THEN 0 ELSE 1 END,created,id")
            else:
                rows = conn.execute("SELECT id,description,status,created_by,created FROM project_catalog "
                                    "WHERE status='ACTIVE' OR created_by=? ORDER BY created,id",
                                    (current["owner"],))
            return [dict(row) for row in rows]

    @app.post("/api/catalog/projects")
    def add_catalog_project(body: CatalogProjectInput, current=Depends(member)):
        with store.connect() as conn:
            role = conn.execute("SELECT is_admin FROM users WHERE id=?", (current["owner"],)).fetchone()
            status = "ACTIVE" if current["kind"] == "user" and role and role[0] else "PENDING"
            try:
                conn.execute("INSERT INTO project_catalog VALUES (?,?,?,?,?)",
                             (body.id, body.description, status, current["owner"], time.time()))
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, "项目标识已存在") from error
        return {"id": body.id, "status": status}

    @app.post("/api/admin/catalog/projects/{project_id}/decision")
    def decide_catalog_project(project_id: str, body: CatalogDecisionInput, current=Depends(admin)):
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM project_catalog WHERE id=?", (project_id,)).fetchone()
            if not row:
                raise HTTPException(404, "项目不存在")
            if row["status"] == "PENDING" and body.action in ("approve", "reject"):
                if body.action == "approve":
                    conn.execute("UPDATE project_catalog SET status='ACTIVE' WHERE id=?", (project_id,))
                    status = "ACTIVE"
                else:
                    conn.execute("DELETE FROM project_catalog WHERE id=?", (project_id,))
                    status = "REMOVED"
            elif row["status"] == "ACTIVE" and body.action == "retire":
                conn.execute("UPDATE project_catalog SET status='RETIRED' WHERE id=?", (project_id,))
                cancel_requests(conn, "project=?", (project_id,), current["owner"], "project_retired")
                status = "RETIRED"
            elif row["status"] == "RETIRED" and body.action == "activate":
                conn.execute("UPDATE project_catalog SET status='ACTIVE' WHERE id=?", (project_id,))
                status = "ACTIVE"
            else:
                raise HTTPException(409, "项目当前状态不支持该操作")
        return {"id": project_id, "status": status}

    @app.put("/api/projects")
    def register_project(body: ProjectInput, current=Depends(device)):
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            catalog = conn.execute("SELECT status FROM project_catalog WHERE id=?", (body.id,)).fetchone()
            if not catalog or catalog["status"] != "ACTIVE":
                raise HTTPException(403, "项目尚未加入云端目录或未经管理员批准")
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
            cancel_requests(conn, "receiver=? AND project=? AND device=?",
                            (current["owner"], project_id, current["id"]), current["owner"], "project_removed")
        return {"ok": True}

    @app.get("/api/projects")
    def projects(owner: str, current=Depends(member)):
        columns = "p.id,p.description,p.runtime,p.device"
        if owner == current["owner"]:
            columns += ",p.path"
        with store.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT " + columns + " FROM projects p JOIN project_catalog c ON c.id=p.id "
                "WHERE p.owner=? AND c.status='ACTIVE'", (owner,))]

    @app.post("/api/requests")
    def ask(body: QuestionInput, current=Depends(member)):
        request_id = secrets.token_hex(12)
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            project = conn.execute("SELECT p.* FROM projects p JOIN project_catalog c ON c.id=p.id "
                                   "WHERE p.owner=? AND p.id=? AND c.status='ACTIVE'",
                                   (body.receiver, body.project)).fetchone()
            if not project:
                raise HTTPException(404, "项目未注册")
            conn.execute("INSERT INTO requests(id,sender,receiver,project,device,question,status,created) "
                         "VALUES (?,?,?,?,?,?,?,?)", (request_id, current["owner"], body.receiver,
                         body.project, project["device"], body.question, "WAITING_APPROVAL", time.time()))
            event(conn, request_id, current, "created")
        return {"id": request_id, "status": "WAITING_APPROVAL"}

    @app.get("/api/requests")
    def requests(current=Depends(member)):
        with store.connect() as conn:
            expire(conn)
            rows = conn.execute("SELECT id,sender,receiver,project,question,status,created,response,error "
                                "FROM requests WHERE sender=? OR receiver=? ORDER BY created DESC LIMIT 200",
                                (current["owner"], current["owner"]))
            return [dict(row) for row in rows]

    @app.get("/api/requests/{request_id}")
    def get_request(request_id: str, current=Depends(member)):
        with store.connect() as conn:
            row = dict(load(conn, request_id))
            if current["owner"] not in (row["sender"], row["receiver"]):
                raise HTTPException(403, "无权查看")
            expire(conn)
            row = dict(load(conn, request_id))
            for key in ("lease", "expires", "device"):
                row.pop(key)
            return row

    @app.post("/api/requests/{request_id}/decision")
    def decision(request_id: str, body: DecisionInput, current=Depends(actor)):
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
                if current["kind"] != "user":
                    raise HTTPException(403, "设备不能代替用户审批")
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
