import argparse
import json
import os
import re
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
    project = sub.add_parser("project-add")
    project.add_argument("id")
    project.add_argument("path")
    project.add_argument("--description", default="")
    project.add_argument("--runtime", choices=["mock", "codex-docker"], default="mock")
    remove = sub.add_parser("project-remove")
    remove.add_argument("id")
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
    if args.command == "init-admin":
        from peerlink.hub import Store
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", args.name):
            parser.error("用户名只允许字母、数字、下划线和短横线，最长 80 字符")
        print(Store(args.db).create_admin(args.name))
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
    hub, token = os.environ.get("PEERLINK_HUB", "http://127.0.0.1:8000"), os.environ.get("PEERLINK_TOKEN")
    if not token:
        parser.error("先设置 PEERLINK_TOKEN；远程使用同时设置 HTTPS PEERLINK_HUB")
    client = Client(hub, token)
    if args.command == "connect":
        if (state / "connector.json").exists():
            parser.error("此状态目录已注册设备；请使用原配置或选择新的 --state")
        result = client.call("POST", "/api/devices", json={"name": args.name})
        save_json(state / "connector.json", {**result, "hub": hub, "projects": {}})
        print("本地设备注册完成；仅保存设备 Token，未保存用户 Token")
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
