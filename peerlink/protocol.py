"""Wire contract shared by the Peerlink Relay and local Bridge."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


MESSAGE_ID_PATTERN = r"^[0-9a-f]{24}$"
AGENT_ID_PATTERN = r"^[a-zA-Z0-9_-]{1,80}$"


class AgentMessage(BaseModel):
    version: Literal["1"] = "1"
    type: Literal["agent.message"] = "agent.message"
    message_id: str = Field(pattern=MESSAGE_ID_PATTERN)
    thread_id: str = Field(pattern=MESSAGE_ID_PATTERN)
    sender: str = Field(min_length=1, max_length=80)
    receiver: str = Field(min_length=1, max_length=80)
    agent_id: str = Field(pattern=AGENT_ID_PATTERN)
    content: str = Field(min_length=1, max_length=10000)


class AgentResponse(BaseModel):
    version: Literal["1"] = "1"
    type: Literal["agent.response"] = "agent.response"
    message_id: str = Field(pattern=MESSAGE_ID_PATTERN)
    status: Literal["draft_ready", "failed"]
    # Draft text stays on the owner's machine until explicit review and send.
    error_code: Optional[str] = Field(default=None, max_length=80)


class DeviceHeartbeat(BaseModel):
    version: Literal["1"] = "1"
    type: Literal["device.heartbeat"] = "device.heartbeat"


def message_from_row(row):
    """Build a path-free envelope from the temporary request row."""
    return AgentMessage(
        message_id=row["id"],
        thread_id=row["thread_id"] or row["id"],
        sender=row["sender"],
        receiver=row["receiver"],
        agent_id=row["project"],
        content=row["question"],
    ).model_dump()
