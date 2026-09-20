from urllib.parse import urlparse

import httpx


class Client:
    def __init__(self, hub, token):
        parsed = urlparse(hub)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Hub URL 不得包含凭证、查询参数或片段")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        ):
            raise ValueError("远程 Hub 必须使用 HTTPS；仅允许本机 HTTP")
        self.http = httpx.Client(base_url=hub.rstrip("/"), timeout=20,
                                 headers={"Authorization": "Bearer " + token})

    def call(self, method, path, **kwargs):
        response = self.http.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()
