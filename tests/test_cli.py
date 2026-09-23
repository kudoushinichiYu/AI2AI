import httpx
import pytest

from peerlink.cli import discover_bridge_agents


class StubClient:
    def __init__(self, status):
        self.status = status

    def call(self, method, path, **kwargs):
        assert (method, path, kwargs) == (
            "GET", "/api/bridge/agents", {"params": {"owner": "yujunjie.50"}},
        )
        if self.status == 200:
            return [{"id": "ai-outbound", "owner": "yujunjie.50"}]
        response = httpx.Response(self.status, request=httpx.Request("GET", "https://hub/api/bridge/agents"))
        response.raise_for_status()


def test_bridge_discovery_works_on_new_hub():
    assert discover_bridge_agents(StubClient(200), "yujunjie.50")[0]["id"] == "ai-outbound"


def test_bridge_discovery_falls_back_only_for_old_hub():
    assert discover_bridge_agents(StubClient(404), "yujunjie.50") == []
    with pytest.raises(httpx.HTTPStatusError):
        discover_bridge_agents(StubClient(403), "yujunjie.50")
