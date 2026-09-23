import json
import subprocess
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from fastapi.testclient import TestClient

from peerlink import __version__
from peerlink.hub import create_app, digest
from peerlink.releases import PLUGIN_VERSION


def test_public_page_redirects_http_domain_to_https(tmp_path):
    client = TestClient(create_app(tmp_path / "hub.db"))
    page = client.get("/")
    assert page.status_code == 200
    assert 'location.protocol==="http:"' in page.text
    assert 'https://peerlink.jd.com' in page.text


def test_workspace_explains_new_member_setup_and_account_isolation(tmp_path):
    client = TestClient(create_app(tmp_path / "hub.db"))

    page = client.get("/")
    script = client.get("/app.js")

    assert page.status_code == 200
    assert script.status_code == 200
    assert "新手开始指南" in page.text
    assert "项目目录与本机路径" in page.text
    assert "网页只生成命令，不上传路径或文件" in page.text
    assert 'id="binding-path"' in page.text
    assert 'id="release-notice"' in page.text
    assert "/app.js?v=20260923-local-agent-bridge" in page.text
    assert "Bridge 联通验证（不调用模型）" in page.text
    assert "没有 app-server 可执行程序时请选择手动 Skill 模式" in page.text
    assert 'export PEERLINK_STATE="$HOME/.peerlink-${owner.replace' in script.text
    assert "project-add" in script.text


def test_public_release_metadata_matches_packaged_plugin_manifest(tmp_path):
    client = TestClient(create_app(tmp_path / "hub.db"))

    response = client.get("/api/releases")

    manifest = json.loads((Path(__file__).parents[1] / "plugins/peerlink/.codex-plugin/plugin.json").read_text())
    assert response.status_code == 200
    assert response.json() == {
        "cli_version": __version__,
        "plugin_version": PLUGIN_VERSION,
        "plugin_marketplace": "peerlink-team",
    }
    assert manifest["version"] == PLUGIN_VERSION


def test_client_wheel_has_a_stable_download_url(tmp_path, monkeypatch):
    package = tmp_path / f"peerlink-{__version__}-py3-none-any.whl"
    package.write_bytes(b"test wheel")
    monkeypatch.setenv("PEERLINK_CLIENT_PACKAGE", str(package))
    client = TestClient(create_app(tmp_path / "hub.db"))

    response = client.get("/downloads/peerlink.whl")

    assert response.status_code == 200
    assert response.content == b"test wheel"
    assert f"peerlink-{__version__}-py3-none-any.whl" in response.headers["content-disposition"]


@pytest.fixture
def setup(tmp_path):
    app = create_app(tmp_path / "hub.db")
    client = TestClient(app)
    tokens = {name: app.state.store.register_user(name) for name in ("alex", "bob", "carol")}
    app.state.store.approve_user("alex")
    app.state.store.approve_user("bob")
    app.state.store.approve_user("carol")
    with app.state.store.connect() as conn:
        conn.execute("UPDATE users SET is_admin=1 WHERE id='alex'")
        conn.execute("INSERT INTO project_catalog VALUES (?,?,?,?,?)",
                     ("recommendation", "Recommendation project", "ACTIVE", "alex", time.time()))
    headers = {name: {"Authorization": "Bearer " + token} for name, token in tokens.items()}
    device = client.post("/api/devices", headers=headers["bob"], json={"name": "bob-mac"}).json()
    headers["device"] = {"Authorization": "Bearer " + device["token"]}
    response = client.put("/api/projects", headers=headers["device"], json={
        "id": "recommendation", "path": "/private/bob/recommendation", "runtime": "mock"})
    assert response.status_code == 200
    return app, client, headers, device


def test_registration_requires_admin_approval(tmp_path):
    app = create_app(tmp_path / "hub.db")
    client = TestClient(app, base_url="https://testserver")
    credentials = {"username": "dylan", "password": "a-secure-password"}
    result = client.post("/api/register", json=credentials).json()
    assert result["username"] == "dylan"
    assert result["status"] == "PENDING"
    assert "token" not in result
    assert "receipt" not in result
    assert client.post("/api/login", json=credentials).status_code == 403

    admin_token = app.state.store.create_admin("bob")
    admin_headers = {"Authorization": "Bearer " + admin_token}
    users = client.get("/api/admin/users", headers=admin_headers).json()
    assert [row["id"] for row in users if row["status"] == "PENDING"] == ["dylan"]
    assert client.post("/api/admin/users/dylan/decision", headers=admin_headers, json={"action": "approve"}).status_code == 200
    login = client.post("/api/login", json=credentials)
    assert login.status_code == 200
    assert "token" not in login.json()
    assert login.cookies.get("peerlink_session")
    assert client.get("/api/me").json()["is_admin"] is False
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_password_admin_can_log_in(tmp_path):
    app = create_app(tmp_path / "hub.db")
    app.state.store.create_admin_password("owner.1", "a-secure-password")
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/login", json={
        "username": "owner.1", "password": "a-secure-password"}).status_code == 200


def test_local_http_login_cookie_authenticates_following_requests(tmp_path):
    app = create_app(tmp_path / "hub.db")
    app.state.store.create_admin_password("owner", "a-secure-password")
    client = TestClient(app, base_url="http://127.0.0.1")

    login = client.post("/api/login", json={
        "username": "owner", "password": "a-secure-password"})

    assert login.status_code == 200
    assert "secure" not in login.headers["set-cookie"].lower()
    assert client.get("/api/me").json() == {
        "kind": "user", "owner": "owner", "id": "owner", "is_admin": True}


def test_unpaired_status_is_a_normal_json_state(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "peerlink.cli", "--state", str(tmp_path / "not-paired"), "status"],
        capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "paired": False, "owner": None, "device": None, "hub": None, "projects": [], "agents": []}
    assert "Traceback" not in result.stderr


def test_rejected_registration_is_removed(tmp_path):
    app = create_app(tmp_path / "hub.db")
    client = TestClient(app)
    token = app.state.store.register_user("erica")
    admin_token = app.state.store.create_admin("owner")
    admin_headers = {"Authorization": "Bearer " + admin_token}
    assert client.post("/api/admin/users/erica/decision", headers=admin_headers, json={"action": "reject"}).status_code == 200
    assert client.get("/api/requests", headers={"Authorization": "Bearer " + token}).status_code == 401


def test_registration_accepts_unique_username_only(tmp_path):
    app = create_app(tmp_path / "hub.db")
    client = TestClient(app)
    body = {"username": "dylan", "password": "a-secure-password"}
    assert client.post("/api/register", json=body).status_code == 200
    assert client.post("/api/register", json=body).status_code == 409
    assert client.post("/api/register", json={**body, "username": "bad name"}).status_code == 422


def test_registration_accepts_erp_with_dot(tmp_path):
    app = create_app(tmp_path / "hub.db")
    client = TestClient(app)
    response = client.post("/api/register", json={"username": "yujunjie.50", "password": "a-secure-password"})
    assert response.status_code == 200
    assert response.json()["username"] == "yujunjie.50"
    assert client.post("/api/register", json={"username": "项目成员", "password": "a-secure-password"}).status_code == 422


def test_pairing_code_binds_one_device_and_expires_after_use(tmp_path):
    app = create_app(tmp_path / "hub.db")
    app.state.store.request_registration("dylan", "a-secure-password")
    app.state.store.approve_user("dylan")
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/login", json={"username": "dylan", "password": "a-secure-password"}).status_code == 200
    code = client.post("/api/pairing-codes").json()["code"]
    paired = client.post("/api/device-pair", json={"name": "dylan-mac", "code": code})
    assert paired.status_code == 200
    assert paired.json()["owner"] == "dylan"
    assert client.post("/api/device-pair", json={"name": "second", "code": code}).status_code == 401
    headers = {"Authorization": "Bearer " + paired.json()["token"]}
    assert client.get("/api/peers", headers=headers).status_code == 200


def test_admin_seeds_catalog_and_member_proposal_requires_approval(tmp_path):
    app = create_app(tmp_path / "hub.db")
    app.state.store.create_admin_password("owner", "a-secure-password")
    app.state.store.request_registration("member", "another-secure-password")
    app.state.store.approve_user("member")
    admin = TestClient(app, base_url="https://testserver")
    member = TestClient(app, base_url="https://testserver")
    assert admin.post("/api/login", json={"username": "owner", "password": "a-secure-password"}).status_code == 200
    assert member.post("/api/login", json={"username": "member", "password": "another-secure-password"}).status_code == 200
    seeded = admin.post("/api/catalog/projects", json={"id": "core", "description": "Core project"})
    assert seeded.json()["status"] == "ACTIVE"
    proposed = member.post("/api/catalog/projects", json={"id": "new-tool", "description": "New tool"})
    assert proposed.json()["status"] == "PENDING"
    rows = admin.get("/api/catalog/projects").json()
    assert {row["id"]: row["status"] for row in rows} == {"core": "ACTIVE", "new-tool": "PENDING"}
    assert admin.post("/api/admin/catalog/projects/new-tool/decision",
                      json={"action": "approve"}).json()["status"] == "ACTIVE"


def test_paired_device_can_propose_catalog_project_for_admin_approval(setup):
    app, client, headers, device = setup
    proposed = client.post("/api/catalog/projects", headers=headers["device"], json={
        "id": "device-proposal", "description": "Proposed from the paired connector"})

    assert proposed.status_code == 200
    assert proposed.json()["status"] == "PENDING"
    approved = client.post("/api/admin/catalog/projects/device-proposal/decision",
                           headers=headers["alex"], json={"action": "approve"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "ACTIVE"


def test_device_can_only_bind_active_catalog_project(tmp_path):
    app = create_app(tmp_path / "hub.db")
    token = app.state.store.create_admin("owner")
    client = TestClient(app)
    device = client.post("/api/devices", headers={"Authorization": "Bearer " + token},
                         json={"name": "mac"}).json()
    headers = {"Authorization": "Bearer " + device["token"]}
    body = {"id": "unknown", "path": "/tmp/project", "description": "x", "runtime": "mock"}
    assert client.put("/api/projects", headers=headers, json=body).status_code == 403


def test_pending_user_is_not_discoverable(tmp_path):
    app = create_app(tmp_path / "hub.db")
    client = TestClient(app)
    active_token = app.state.store.create_admin("owner")
    app.state.store.register_user("pending")
    peers = client.get(
        "/api/peers", headers={"Authorization": "Bearer " + active_token}
    ).json()
    assert peers == ["owner"]


def test_existing_users_are_activated_and_first_is_admin(tmp_path):
    db_path = tmp_path / "hub.db"
    app = create_app(db_path)
    with app.state.store.connect() as conn:
        conn.execute("DROP TABLE users")
        conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE)")
        conn.execute("INSERT INTO users VALUES ('legacy', ?)", (digest("legacy-token"),))
    migrated = TestClient(create_app(db_path))
    with create_app(db_path).state.store.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id='legacy'").fetchone()
    assert row["status"] == "ACTIVE"
    assert row["is_admin"] == 1
    assert migrated.get("/api/requests", headers={"Authorization": "Bearer legacy-token"}).status_code == 200


def question(client, headers):
    response = client.post("/api/requests", headers=headers["alex"], json={
        "receiver": "bob", "project": "recommendation", "question": "为什么换模型？"})
    assert response.status_code == 200
    return response.json()["id"]


def approved(setup):
    app, client, headers, device = setup
    request_id = question(client, headers)
    response = client.post(f"/api/requests/{request_id}/decision", headers=headers["bob"], json={"action": "approve"})
    assert response.status_code == 200
    return request_id


def claimed(setup):
    request_id = approved(setup)
    app, client, headers, device = setup
    task = client.post("/api/connector/claim", headers=headers["device"]).json()
    assert task["id"] == request_id
    return task


def test_complete_flow_and_no_draft_upload(setup):
    app, client, headers, device = setup
    task = claimed(setup)
    endpoint = f"/api/connector/{task['id']}/result"
    base = {"lease": task["lease"]}
    assert client.post(endpoint, headers=headers["device"], json={**base, "action": "send", "content": "绕过草稿"}).status_code == 409
    assert client.post(endpoint, headers=headers["device"], json={**base, "action": "draft_ready", "content": "私密草稿"}).status_code == 400
    assert client.post(endpoint, headers=headers["device"], json={**base, "action": "draft_ready"}).status_code == 200
    row = client.get(f"/api/requests/{task['id']}", headers=headers["alex"]).json()
    assert row["response"] is None
    assert "lease" not in row
    assert client.post(endpoint, headers=headers["device"], json={**base, "action": "send", "content": "审核后的答案"}).status_code == 200
    row = client.get(f"/api/requests/{task['id']}", headers=headers["alex"]).json()
    assert row["response"] == "审核后的答案"
    assert row["status"] == "COMPLETED"
    with app.state.store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit WHERE request=?", (task["id"],)).fetchone()[0] == 5


def test_codex_desktop_claim_is_explicit_and_can_target_request(setup):
    app, client, headers, device = setup
    removed = client.delete("/api/projects/recommendation", headers=headers["device"])
    assert removed.status_code == 200
    update = client.put("/api/projects", headers=headers["device"], json={
        "id": "recommendation", "path": "/private/bob/recommendation", "runtime": "codex-desktop"})
    assert update.status_code == 200
    first_id = approved(setup)
    target_id = approved(setup)

    assert client.post("/api/connector/claim", headers=headers["device"], json={
        "exclude_runtime": "codex-desktop"}).json() is None
    task = client.post("/api/connector/claim", headers=headers["device"], json={
        "request_id": target_id}).json()

    assert task["id"] == target_id
    assert task["sender"] == "alex"
    assert client.get(f"/api/requests/{first_id}", headers=headers["bob"]).json()["status"] == "WAITING_DEVICE"


@pytest.mark.parametrize("identity", ["alex", "carol", "device"])
def test_only_recipient_can_approve(setup, identity):
    app, client, headers, device = setup
    request_id = question(client, headers)
    assert client.post(f"/api/requests/{request_id}/decision", headers=headers[identity], json={"action": "approve"}).status_code == 403
    assert client.post("/api/connector/claim", headers=headers["device"]).json() is None


def test_private_paths_and_requests(setup):
    app, client, headers, device = setup
    assert "path" not in client.get("/api/projects?owner=bob", headers=headers["alex"]).json()[0]
    assert "path" not in client.get("/api/projects?owner=bob", headers=headers["bob"]).json()[0]
    request_id = question(client, headers)
    assert client.get(f"/api/requests/{request_id}", headers=headers["carol"]).status_code == 403
    assert client.get("/api/requests").status_code == 401
    assert client.get("/api/requests", headers=headers["device"]).status_code == 200


def test_forbidden_request_read_does_not_expire_other_users_lease(setup):
    task = claimed(setup)
    app, client, headers, device = setup
    with app.state.store.connect() as conn:
        conn.execute("UPDATE requests SET expires=? WHERE id=?", (time.time() - 1, task["id"]))

    assert client.get("/api/requests/not-a-request", headers=headers["carol"]).status_code == 404
    assert client.get(f"/api/requests/{task['id']}", headers=headers["carol"]).status_code == 403
    with app.state.store.connect() as conn:
        status = conn.execute("SELECT status FROM requests WHERE id=?", (task["id"],)).fetchone()[0]
        assert status == "RUNNING"

    visible = client.get(f"/api/requests/{task['id']}", headers=headers["bob"])
    assert visible.status_code == 200
    assert visible.json()["status"] == "FAILED"
    with app.state.store.connect() as conn:
        event = conn.execute("SELECT actor,event FROM audit WHERE request=? ORDER BY id DESC LIMIT 1",
                             (task["id"],)).fetchone()
    assert tuple(event) == ("system", "lease_expired")


def test_device_auth_rejects_disabled_owner(setup):
    app, client, headers, device = setup
    with app.state.store.connect() as conn:
        conn.execute("UPDATE users SET status='DISABLED' WHERE id='bob'")

    assert client.get("/api/peers", headers=headers["device"]).status_code == 401


def test_password_change_and_session_revoke_invalidate_all_sessions(tmp_path):
    app = create_app(tmp_path / "hub.db")
    app.state.store.create_admin_password("owner", "a-secure-password")
    first = TestClient(app, base_url="https://testserver")
    second = TestClient(app, base_url="https://testserver")
    credentials = {"username": "owner", "password": "a-secure-password"}
    assert first.post("/api/login", json=credentials).status_code == 200
    assert second.post("/api/login", json=credentials).status_code == 200

    changed = first.post("/api/account/password", json={
        "current_password": "a-secure-password", "new_password": "another-secure-password"})
    assert changed.status_code == 200
    assert first.get("/api/me").status_code == 401
    assert second.get("/api/me").status_code == 401
    assert first.post("/api/login", json={
        "username": "owner", "password": "another-secure-password"}).status_code == 200

    revoked = first.post("/api/sessions/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] == 1
    assert first.get("/api/me").status_code == 401


def test_cannot_disable_last_active_administrator(tmp_path):
    app = create_app(tmp_path / "hub.db")
    app.state.store.create_admin_password("owner", "a-secure-password")
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/login", json={
        "username": "owner", "password": "a-secure-password"}).status_code == 200

    response = client.post("/api/admin/users/owner/decision", json={"action": "disable"})

    assert response.status_code == 409
    assert client.get("/api/me").status_code == 200


def test_catalog_project_can_be_retired_and_reactivated_with_audit(setup):
    app, client, headers, device = setup
    request_id = question(client, headers)
    assert client.post(f"/api/requests/{request_id}/decision", headers=headers["bob"],
                       json={"action": "approve"}).status_code == 200

    retired = client.post("/api/admin/catalog/projects/recommendation/decision",
                          headers=headers["alex"], json={"action": "retire"})
    assert retired.status_code == 200
    assert retired.json()["status"] == "RETIRED"
    assert client.get("/api/projects?owner=bob", headers=headers["alex"]).json() == []
    assert client.post("/api/requests", headers=headers["alex"], json={
        "receiver": "bob", "project": "recommendation", "question": "unavailable"}).status_code == 404
    with app.state.store.connect() as conn:
        row = conn.execute("SELECT status FROM requests WHERE id=?", (request_id,)).fetchone()
        audit = conn.execute("SELECT actor,event FROM audit WHERE request=? ORDER BY id DESC LIMIT 1",
                             (request_id,)).fetchone()
    assert row["status"] == "CANCELLED"
    assert tuple(audit) == ("alex", "project_retired")

    active = client.post("/api/admin/catalog/projects/recommendation/decision",
                         headers=headers["alex"], json={"action": "activate"})
    assert active.status_code == 200
    assert active.json()["status"] == "ACTIVE"
    assert len(client.get("/api/projects?owner=bob", headers=headers["alex"]).json()) == 1


def test_device_revocation_bulk_cancel_is_audited(setup):
    task = claimed(setup)
    app, client, headers, device = setup
    assert client.delete("/api/devices/" + device["id"], headers=headers["bob"]).status_code == 200
    with app.state.store.connect() as conn:
        event = conn.execute("SELECT actor,event FROM audit WHERE request=? ORDER BY id DESC LIMIT 1",
                             (task["id"],)).fetchone()
    assert tuple(event) == ("bob", "device_revoked")


def test_project_removal_bulk_cancel_is_audited(setup):
    task = claimed(setup)
    app, client, headers, device = setup
    assert client.delete("/api/projects/recommendation", headers=headers["device"]).status_code == 200
    with app.state.store.connect() as conn:
        event = conn.execute("SELECT actor,event FROM audit WHERE request=? ORDER BY id DESC LIMIT 1",
                             (task["id"],)).fetchone()
    assert tuple(event) == ("bob", "project_removed")


def test_disabling_user_revokes_access_and_audits_unfinished_requests(setup):
    task = claimed(setup)
    app, client, headers, device = setup
    with app.state.store.connect() as conn:
        conn.execute("INSERT INTO requests(id,sender,receiver,project,device,question,status,created) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     ("already-done", "bob", "alex", "recommendation", "irrelevant", "done",
                      "COMPLETED", time.time()))
    disabled = client.post("/api/admin/users/bob/decision", headers=headers["alex"],
                           json={"action": "disable"})

    assert disabled.status_code == 200
    assert disabled.json()["status"] == "DISABLED"
    assert client.get("/api/peers", headers=headers["device"]).status_code == 401
    assert client.get("/api/peers", headers=headers["bob"]).status_code == 401
    with app.state.store.connect() as conn:
        row = conn.execute("SELECT status FROM requests WHERE id=?", (task["id"],)).fetchone()
        completed = conn.execute("SELECT status FROM requests WHERE id='already-done'").fetchone()
        event = conn.execute("SELECT actor,event FROM audit WHERE request=? ORDER BY id DESC LIMIT 1",
                             (task["id"],)).fetchone()
    assert row["status"] == "CANCELLED"
    assert completed["status"] == "COMPLETED"
    assert tuple(event) == ("alex", "user_disabled")

    assert client.post("/api/admin/users/bob/decision", headers=headers["alex"],
                       json={"action": "enable"}).status_code == 200
    assert client.get("/api/peers", headers=headers["bob"]).status_code == 401


def test_device_can_send_and_cancel_but_cannot_approve(setup):
    app, client, headers, device = setup
    result = client.post("/api/requests", headers=headers["device"], json={
        "receiver": "alex", "project": "missing", "question": "hello"})
    assert result.status_code == 404
    request_id = question(client, headers)
    assert client.post(f"/api/requests/{request_id}/decision", headers=headers["device"],
                       json={"action": "approve"}).status_code == 403
    own = client.post("/api/requests", headers=headers["device"], json={
        "receiver": "bob", "project": "recommendation", "question": "self check"}).json()
    assert client.post(f"/api/requests/{own['id']}/decision", headers=headers["device"],
                       json={"action": "cancel"}).status_code == 200


def test_claim_is_atomic(setup):
    approved(setup)
    app, client, headers, device = setup
    def claim_task(unused):
        return client.post("/api/connector/claim", headers=headers["device"]).json()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(claim_task, range(6)))
    assert sum(result is not None for result in results) == 1


def test_offline_request_survives_restart(setup):
    request_id = approved(setup)
    app, client, headers, device = setup
    restarted = TestClient(create_app(app.state.store.path))
    task = restarted.post("/api/connector/claim", headers=headers["device"]).json()
    assert task["id"] == request_id


@pytest.mark.parametrize("change", ["cancel", "expire", "unregister", "revoke"])
def test_stale_execution_cannot_send(setup, change):
    task = claimed(setup)
    app, client, headers, device = setup
    if change == "cancel":
        client.post(f"/api/requests/{task['id']}/decision", headers=headers["alex"], json={"action": "cancel"})
    elif change == "expire":
        with app.state.store.connect() as conn:
            conn.execute("UPDATE requests SET expires=? WHERE id=?", (time.time() - 1, task["id"]))
    elif change == "unregister":
        client.delete("/api/projects/recommendation", headers=headers["device"])
    else:
        client.delete(f"/api/devices/{device['id']}", headers=headers["bob"])
    assert client.post(f"/api/connector/{task['id']}/result", headers=headers["device"], json={
        "action": "draft_ready", "lease": task["lease"]}).status_code in (401, 409)


def test_project_rebinding_requires_original_device_and_runtime(setup):
    app, client, headers, device = setup
    assert client.put("/api/projects", headers=headers["device"], json={
        "id": "recommendation", "path": "/different", "runtime": "mock"}).status_code == 200
    assert client.put("/api/projects", headers=headers["device"], json={
        "id": "recommendation", "runtime": "codex-desktop"}).status_code == 409
    another = client.post("/api/devices", headers=headers["bob"], json={"name": "second"}).json()
    assert client.put("/api/projects", headers={"Authorization": "Bearer " + another["token"]}, json={
        "id": "recommendation", "path": "/different", "runtime": "mock"}).status_code == 409


def test_wrong_lease_and_device_rejected(setup):
    task = claimed(setup)
    app, client, headers, device = setup
    endpoint = f"/api/connector/{task['id']}/heartbeat"
    assert client.post(endpoint, headers=headers["device"], json={"lease": "wrong"}).status_code == 409
    another = client.post("/api/devices", headers=headers["carol"], json={"name": "carol"}).json()
    assert client.post(endpoint, headers={"Authorization": "Bearer " + another["token"]}, json={"lease": task["lease"]}).status_code == 403


def test_terminal_decisions_cannot_be_repeated(setup):
    app, client, headers, device = setup
    request_id = question(client, headers)
    endpoint = f"/api/requests/{request_id}/decision"
    assert client.post(endpoint, headers=headers["bob"], json={"action": "reject"}).status_code == 200
    assert client.post(endpoint, headers=headers["bob"], json={"action": "approve"}).status_code == 409
    assert client.post(endpoint, headers=headers["alex"], json={"action": "cancel"}).status_code == 409
