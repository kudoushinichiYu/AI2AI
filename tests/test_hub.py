import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from fastapi.testclient import TestClient

from peerlink.hub import create_app, digest


@pytest.fixture
def setup(tmp_path):
    app = create_app(tmp_path / "hub.db")
    client = TestClient(app)
    tokens = {name: app.state.store.register_user(name) for name in ("alex", "bob", "carol")}
    app.state.store.approve_user("alex")
    app.state.store.approve_user("bob")
    app.state.store.approve_user("carol")
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


@pytest.mark.parametrize("identity", ["alex", "carol", "device"])
def test_only_recipient_can_approve(setup, identity):
    app, client, headers, device = setup
    request_id = question(client, headers)
    assert client.post(f"/api/requests/{request_id}/decision", headers=headers[identity], json={"action": "approve"}).status_code == 403
    assert client.post("/api/connector/claim", headers=headers["device"]).json() is None


def test_private_paths_and_requests(setup):
    app, client, headers, device = setup
    assert "path" not in client.get("/api/projects?owner=bob", headers=headers["alex"]).json()[0]
    assert "path" in client.get("/api/projects?owner=bob", headers=headers["bob"]).json()[0]
    request_id = question(client, headers)
    assert client.get(f"/api/requests/{request_id}", headers=headers["carol"]).status_code == 403
    assert client.get("/api/requests").status_code == 401
    assert client.get("/api/requests", headers=headers["device"]).status_code == 403


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


def test_project_rebinding_requires_unregister(setup):
    app, client, headers, device = setup
    assert client.put("/api/projects", headers=headers["device"], json={
        "id": "recommendation", "path": "/different", "runtime": "mock"}).status_code == 409
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
