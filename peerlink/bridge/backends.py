"""Local Agent Backend contract and the no-model Echo verification backend."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class BackendAnswer:
    text: str
    thread_id: str | None = None


class AgentBackend(ABC):
    @abstractmethod
    async def answer(self, question: str, workspace: str,
                     backend_thread_id: str | None = None) -> BackendAnswer:
        """Answer using only this Agent's explicitly bound local workspace."""


class EchoBackend(AgentBackend):
    async def answer(self, question: str, workspace: str,
                     backend_thread_id: str | None = None) -> BackendAnswer:
        return BackendAnswer("echo: " + question, backend_thread_id)


def create_backend(name: str) -> AgentBackend:
    if name == "echo":
        return EchoBackend()
    if name == "codex-app-server":
        from peerlink.bridge.codex import CodexAppServerBackend
        return CodexAppServerBackend()
    raise ValueError("不支持的 Agent Backend")
