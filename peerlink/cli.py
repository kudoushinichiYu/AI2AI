import argparse
import getpass
import json
import os
import re
import shutil
from pathlib import Path

from peerlink.client import Client
from peerlink.connector import configured, review, save_json, work


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
    project.add_argument("--runtime", choices=["mock", "codex-docker"], default="mock")
    remove = sub.add_parser("project-remove")
    remove.add_argument("id")
    sub.add_parser("catalog")
    propose = sub.add_parser("project-propose")
    propose.add_argument("id")
    propose.add_argument("description")
    worker = sub.add_parser("work")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--auth-dir")
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
            client.call("PUT", "/api/projects", json=project)
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
    config, client = configured(state)
    if args.command == "status":
        print(json.dumps({"owner": config["owner"], "device": config["id"],
                          "hub": config["hub"], "projects": list(config["projects"])},
                         ensure_ascii=False, indent=2))
        return
    if args.command == "catalog":
        print(json.dumps(client.call("GET", "/api/catalog/projects"), ensure_ascii=False, indent=2))
        return
    if args.command == "project-propose":
        print(json.dumps(client.call("POST", "/api/catalog/projects", json={
            "id": args.id, "description": args.description}), ensure_ascii=False, indent=2))
        return
    if args.command == "peers":
        result = client.call("GET", "/api/peers")
    elif args.command == "projects":
        result = client.call("GET", "/api/projects", params={"owner": args.owner})
    elif args.command == "ask":
        result = client.call("POST", "/api/requests", json={"receiver": args.receiver, "project": args.project, "question": args.question})
    elif args.command == "requests":
        result = client.call("GET", "/api/requests")
    elif args.command == "get":
        result = client.call("GET", "/api/requests/" + args.id)
    else:
        result = client.call("POST", "/api/requests/" + args.id + "/decision", json={"action": "cancel"})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
