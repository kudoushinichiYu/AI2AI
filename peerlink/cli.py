import argparse
import getpass
import json
import os
import re
import shutil
import secrets
import sys
from pathlib import Path

import httpx

from peerlink.client import Client
from peerlink.connector import (configured, desktop_context, desktop_submit, review,
                                save_json, work)
from peerlink.releases import PUBLIC_HUB, check_releases
from peerlink.service import install_service, remove_service, service_status


def discover_bridge_agents(client, owner):
    """Keep the new CLI usable while a team's Hub is still on pre-Bridge 0.4.x."""
    try:
        return client.call("GET", "/api/bridge/agents", params={"owner": owner})
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            return []
        raise


def main():
    parser = argparse.ArgumentParser(description="Peerlink 云端 Hub / 本地 Connector / 协作 CLI")
    parser.add_argument("--state", default=os.environ.get("PEERLINK_STATE", str(Path.home() / ".peerlink")))
    sub = parser.add_subparsers(dest="command", required=True)
    server = sub.add_parser("hub")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8000)
    server.add_argument("--db", default=os.environ.get("PEERLINK_DB", ".peerlink/hub.db"))
    init_admin = sub.add_parser("init-admin")
    init_admin.add_argument("name")
    init_admin.add_argument("--db", default=os.environ.get("PEERLINK_DB", ".peerlink/hub.db"))
    setup = sub.add_parser("connect")
    setup.add_argument("--name", required=True)
    setup.add_argument("--hub", default=os.environ.get("PEERLINK_HUB", "https://peerlink.jd.com"))
    setup.add_argument("--code", required=True)
    project = sub.add_parser("project-add")
    project.add_argument("id")
    project.add_argument("path")
    project.add_argument("--description", default="")
    project.add_argument("--runtime", choices=["mock", "codex-desktop", "codex-docker"], default="mock")
    remove = sub.add_parser("project-remove")
    remove.add_argument("id")
    agent = sub.add_parser("agent")
    agent_actions = agent.add_subparsers(dest="agent_command", required=True)
    agent_add = agent_actions.add_parser("add")
    agent_add.add_argument("id")
    agent_add.add_argument("workspace")
    agent_add.add_argument("--backend", choices=["echo", "codex-app-server"], default="echo")
    agent_add.add_argument("--visibility", choices=["private", "team", "allowlist"], default="private")
    agent_add.add_argument("--allow-user", action="append", default=[])
    agent_add.add_argument("--description", default="")
    agent_remove = agent_actions.add_parser("remove")
    agent_remove.add_argument("id")
    agent_actions.add_parser("list")
    bridge = sub.add_parser("bridge")
    bridge_actions = bridge.add_subparsers(dest="bridge_command", required=True)
    bridge_start = bridge_actions.add_parser("start")
    bridge_start.add_argument("--auth-dir")
    listed_agents = sub.add_parser("agents")
    listed_agents.add_argument("--owner")
    send = sub.add_parser("send")
    send.add_argument("receiver")
    send.add_argument("agent")
    send.add_argument("message")
    send.add_argument("--thread")
    send.add_argument("--message-id")
    sub.add_parser("catalog")
    propose = sub.add_parser("project-propose")
    propose.add_argument("id")
    propose.add_argument("description")
    worker = sub.add_parser("work")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--auth-dir")
    desktop_context_parser = sub.add_parser("desktop-context")
    desktop_context_parser.add_argument("id")
    desktop_submit = sub.add_parser("desktop-submit")
    desktop_submit.add_argument("id")
    service_install = sub.add_parser("service-install")
    service_install.add_argument("--auth-dir")
    sub.add_parser("service-status")
    sub.add_parser("service-remove")
    inspect = sub.add_parser("review")
    inspect.add_argument("id", nargs="?")
    actions = inspect.add_mutually_exclusive_group()
    actions.add_argument("--send", action="store_true")
    actions.add_argument("--reject", action="store_true")
    inspect.add_argument("--answer-file")
    sub.add_parser("peers")
    listing = sub.add_parser("projects")
    listing.add_argument("owner")
    ask = sub.add_parser("ask")
    ask.add_argument("receiver")
    ask.add_argument("project")
    ask.add_argument("question")
    sub.add_parser("requests")
    sub.add_parser("status")
    sub.add_parser("update-check")
    install_skill = sub.add_parser("skill-install")
    install_skill.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    install_skill.add_argument("--force", action="store_true")
    get = sub.add_parser("get")
    get.add_argument("id")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("id")
    args = parser.parse_args()
    state = Path(args.state).expanduser().resolve()
    if args.command == "hub":
        import uvicorn
        from peerlink.hub import create_app
        uvicorn.run(create_app(args.db), host=args.host, port=args.port)
        return
    if args.command == "skill-install":
        source = Path(__file__).parent / "bundled_skill"
        target = Path(args.codex_home).expanduser().resolve() / "skills" / "peerlink"
        if target.exists():
            if not args.force:
                parser.error(f"Skill 已存在：{target}；确认替换时使用 --force")
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        print(f"Peerlink Skill 已安装：{target}")
        return
    if args.command == "init-admin":
        from peerlink.hub import Store
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", args.name):
            parser.error("用户名只允许字母、数字、点、下划线和短横线，最长 80 字符")
        password = getpass.getpass("管理员密码（至少 10 位）：")
        if len(password) < 10 or password != getpass.getpass("再次输入密码："):
            parser.error("密码少于 10 位或两次输入不一致")
        Store(args.db).create_admin_password(args.name, password)
        print("管理员账号已创建；请使用用户名和密码登录")
        return
    if args.command == "work":
        work(state, args.once, args.auth_dir)
        return
    if args.command == "bridge":
        from peerlink.bridge.client import run_bridge
        run_bridge(state, args.auth_dir)
        return
    if args.command == "agent":
        from peerlink.bridge.registry import (add_agent, load_agents, registry_path,
                                              validate_workspace)
        if args.agent_command == "list":
            print(json.dumps(load_agents(state), ensure_ascii=False, indent=2))
            return
        config, client = configured(state)
        if args.agent_command == "remove":
            client.call("DELETE", "/api/bridge/agents/" + args.id)
            agents = load_agents(state)
            agents.pop(args.id, None)
            save_json(registry_path(state), agents)
            print("Agent 已从本机和云端移除")
            return
        workspace = validate_workspace(args.workspace)
        existing = load_agents(state).get(args.id)
        if existing and existing["workspace"] != workspace:
            parser.error("本机已注册同名 Agent；先运行 agent remove 再重新绑定")
        client.call("PUT", "/api/bridge/agents", json={
            "id": args.id, "description": args.description,
            "visibility": args.visibility, "allowlist": args.allow_user,
        })
        add_agent(state, args.id, workspace, args.backend, args.description,
                  args.visibility, args.allow_user)
        print("Agent 已注册；本机路径仅保存在 agents.json")
        return
    if args.command == "desktop-context":
        desktop_context(state, args.id)
        return
    if args.command == "desktop-submit":
        desktop_submit(state, args.id, sys.stdin.read(100001))
        return
    if args.command == "service-install":
        target = install_service(state, args.auth_dir)
        print(f"Peerlink 后台 Connector 已安装并启动：{target}")
        return
    if args.command == "service-status":
        print(json.dumps(service_status(state), ensure_ascii=False, indent=2))
        return
    if args.command == "service-remove":
        target = remove_service(state)
        print(f"Peerlink 后台 Connector 已停止并移除：{target}")
        return
    if args.command == "review":
        review(state, args.id, "send" if args.send else "reject" if args.reject else None, args.answer_file)
        return
    if args.command in ("project-add", "project-remove"):
        config, client = configured(state)
        if args.command == "project-add":
            path = Path(args.path).expanduser().resolve(strict=True)
            if not path.is_dir() or path == Path.home() or path == Path("/"):
                parser.error("请选择具体项目目录，不允许注册整个 Home 或根目录")
            project = {"id": args.id, "path": str(path), "description": args.description, "runtime": args.runtime}
            previous = config.get("projects", {}).get(args.id)
            if previous and (previous["path"] != project["path"] or previous["runtime"] != project["runtime"]):
                parser.error("本机路径或 Runtime 变更需要先运行 project-remove")
            client.call("PUT", "/api/projects", json={key: project[key] for key in ("id", "description", "runtime")})
            config["projects"][args.id] = project
        else:
            client.call("DELETE", "/api/projects/" + args.id)
            config["projects"].pop(args.id, None)
        save_json(state / "connector.json", config)
        print("项目注册已更新")
        return
    if args.command == "connect":
        if (state / "connector.json").exists():
            parser.error("此状态目录已注册设备；请使用原配置或选择新的 --state")
        client = Client(args.hub)
        result = client.call("POST", "/api/device-pair", json={"name": args.name, "code": args.code})
        save_json(state / "connector.json", {**result, "hub": args.hub, "projects": {}})
        print(f"本地设备已绑定账号 {result['owner']}；配对码已失效")
        client.http.close()
        return
    if args.command == "status":
        from peerlink.bridge.registry import load_agents
        config_path = state / "connector.json"
        if not config_path.is_file():
            print(json.dumps({"paired": False, "owner": None, "device": None,
                              "hub": None, "projects": [], "agents": []}, ensure_ascii=False, indent=2))
            return
        config = json.loads(config_path.read_text())
        print(json.dumps({"paired": True, "owner": config["owner"], "device": config["id"],
                          "hub": config["hub"], "projects": list(config.get("projects", {})),
                          "agents": list(load_agents(state))},
                         ensure_ascii=False, indent=2))
        return
    if args.command == "update-check":
        config_path = state / "connector.json"
        try:
            hub = (
                json.loads(config_path.read_text())["hub"] if config_path.is_file()
                else os.environ.get("PEERLINK_HUB", PUBLIC_HUB)
            )
            result = check_releases(hub)
        except (httpx.HTTPError, OSError, KeyError, ValueError):
            result = {
                "checked": False,
                "message": "暂时无法连接 Peerlink 版本服务；本地协作功能不受影响，请稍后重试。",
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    config, client = configured(state)
    if args.command == "catalog":
        print(json.dumps(client.call("GET", "/api/catalog/projects"), ensure_ascii=False, indent=2))
        return
    if args.command == "project-propose":
        print(json.dumps(client.call("POST", "/api/catalog/projects", json={
            "id": args.id, "description": args.description}), ensure_ascii=False, indent=2))
        return
    if args.command == "peers":
        result = client.call("GET", "/api/peers")
    elif args.command == "agents":
        result = client.call("GET", "/api/bridge/agents", params={"owner": args.owner} if args.owner else {})
    elif args.command == "send":
        result = client.call("POST", "/api/bridge/messages", json={
            "receiver": args.receiver, "agent_id": args.agent,
            "content": args.message, "thread_id": args.thread,
            "message_id": args.message_id or secrets.token_hex(12),
        })
    elif args.command == "projects":
        legacy = client.call("GET", "/api/projects", params={"owner": args.owner})
        agents = discover_bridge_agents(client, args.owner)
        result = [*legacy, *({**agent, "runtime": "bridge"} for agent in agents)]
    elif args.command == "ask":
        agents = discover_bridge_agents(client, args.receiver)
        if any(agent["id"] == args.project for agent in agents):
            result = client.call("POST", "/api/bridge/messages", json={
                "receiver": args.receiver, "agent_id": args.project,
                "content": args.question, "message_id": secrets.token_hex(12),
            })
        else:
            result = client.call("POST", "/api/requests", json={
                "receiver": args.receiver, "project": args.project, "question": args.question,
            })
    elif args.command == "requests":
        result = client.call("GET", "/api/requests")
    elif args.command == "get":
        result = client.call("GET", "/api/requests/" + args.id)
    else:
        result = client.call("POST", "/api/requests/" + args.id + "/decision", json={"action": "cancel"})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
