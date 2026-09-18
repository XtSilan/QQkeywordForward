from urllib.parse import urlencode

import httpx

from app.settings import Settings


class DockerControl:
    allowed = {
        "napcat": "napcat_container_name",
        "nonebot": "nonebot_container_name",
        "webui": "webui_container_name",
    }

    def __init__(self, settings: Settings):
        self.settings = settings

    def _container(self, service: str) -> str:
        field = self.allowed.get(service)
        if not field:
            raise ValueError("service is not allowed")
        return getattr(self.settings, field)

    async def restart(self, service: str) -> dict:
        if not self.settings.control_enabled:
            raise RuntimeError("service control is disabled")
        container = self._container(service)
        query = urlencode({"t": "20"})
        transport = httpx.AsyncHTTPTransport(uds=self.settings.docker_socket)
        async with httpx.AsyncClient(transport=transport, timeout=30) as client:
            response = await client.post(
                f"http://docker/v1.45/containers/{container}/restart?{query}"
            )
        if response.status_code not in (204, 304):
            raise RuntimeError(f"docker restart failed: {response.status_code}")
        return {"service": service, "container": container, "restarted": True}

    async def logs(self, service: str, tail: int = 200) -> str:
        if not self.settings.control_enabled:
            raise RuntimeError("service control is disabled")
        container = self._container(service)
        tail = max(1, min(tail, 2000))
        query = urlencode({"stdout": "1", "stderr": "1", "tail": str(tail)})
        transport = httpx.AsyncHTTPTransport(uds=self.settings.docker_socket)
        async with httpx.AsyncClient(transport=transport, timeout=30) as client:
            response = await client.get(
                f"http://docker/v1.45/containers/{container}/logs?{query}"
            )
        if response.status_code != 200:
            raise RuntimeError(f"docker logs failed: {response.status_code}")
        return response.content.decode("utf-8", errors="replace")
