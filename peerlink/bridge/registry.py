"""Explicit local Agent bindings; workspace paths never enter Relay metadata."""

import re
from pathlib import Path

from peerlink.connector import read_json, save_json


AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


def registry_path(state):
    return Path(state) / "agents.json"


def load_agents(state):
    path = registry_path(state)
    return read_json(path) if path.is_file() else {}


def validate_workspace(path):
    workspace = Path(path).expanduser().resolve(strict=True)
    if not workspace.is_dir() or workspace in (Path.home(), Path("/")):
        raise ValueError("请选择具体项目目录，不允许根目录或整个 Home")
    return str(workspace)


def add_agent(state, name, workspace, backend="echo", description="",
              visibility="private", allowlist=()):
    if not AGENT_ID_RE.fullmatch(name):
        raise ValueError("Agent 标识只允许字母、数字、下划线和短横线，最长 80 字符")
    if backend not in ("echo", "codex-app-server"):
        raise ValueError("不支持的 Agent Backend")
    if visibility not in ("private", "team", "allowlist"):
        raise ValueError("不支持的可见范围")
    allowed = sorted(set(allowlist))
    if visibility != "allowlist" and allowed:
        raise ValueError("只有 allowlist 模式可以指定成员白名单")
    if len(allowed) > 50:
        raise ValueError("白名单最多 50 人")
    agent = {"id": name, "workspace": validate_workspace(workspace), "backend": backend,
             "description": description, "visibility": visibility, "allowlist": allowed}
    agents = load_agents(state)
    if name in agents and agents[name]["workspace"] != agent["workspace"]:
        raise ValueError("本机已注册同名 Agent；先移除再重新绑定路径")
    agents[name] = agent
    save_json(registry_path(state), agents)
    return agent


def allowed_sender(agent, sender, owner):
    if sender == owner:
        return True
    if agent["visibility"] == "team":
        return True
    if agent["visibility"] == "allowlist":
        return sender in agent["allowlist"]
    return False
