"""Docker Engine API over the unix socket (helper container lifecycle)."""
from __future__ import annotations

import os
from typing import Any

import httpx

from . import config


def docker_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(uds=config.DOCKER_SOCKET),
        base_url="http://docker",
        timeout=httpx.Timeout(30.0, connect=10.0),
    )


def decode_log_stream(payload: bytes) -> str:
    """Decode Docker's multiplexed stdout/stderr stream into readable text."""
    chunks: list[bytes] = []
    offset = 0
    while offset + 8 <= len(payload):
        size = int.from_bytes(payload[offset + 4: offset + 8], "big")
        start = offset + 8
        end = start + size
        if end > len(payload):
            break
        chunks.append(payload[start:end])
        offset = end
    if chunks and offset == len(payload):
        return b"".join(chunks).decode("utf-8", errors="replace")
    return payload.decode("utf-8", errors="replace")


async def helper_inspect() -> dict[str, Any] | None:
    async with docker_client() as client:
        response = await client.get(f"/containers/{config.HELPER_NAME}/json")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
    state = payload.get("State") or {}
    return {
        "name": config.HELPER_NAME,
        "id": str(payload.get("Id") or "")[:12],
        "running": bool(state.get("Running")),
        "exit_code": state.get("ExitCode"),
        "started_at": state.get("StartedAt") or "",
        "finished_at": state.get("FinishedAt") or "",
        "error": state.get("Error") or "",
    }


async def helper_logs(tail: int = 400) -> str:
    async with docker_client() as client:
        response = await client.get(
            f"/containers/{config.HELPER_NAME}/logs",
            params={"stdout": "1", "stderr": "1", "tail": str(tail)},
        )
        if response.status_code != 200:
            return ""
        return decode_log_stream(response.content)


async def host_project_path() -> str:
    """Where PROJECT_DIR lives on the docker host — read from our own mounts,
    so compose does not need to hardcode the checkout path."""
    if config.BIND_FALLBACK:
        return config.BIND_FALLBACK
    hostname = os.environ.get("HOSTNAME") or ""
    async with docker_client() as client:
        response = await client.get(f"/containers/{hostname}/json")
        if response.status_code == 200:
            for mount in response.json().get("Mounts") or []:
                if str(mount.get("Destination") or "") == str(config.PROJECT_DIR):
                    return str(mount.get("Source") or "")
    raise RuntimeError(
        "cannot resolve the host path of PROJECT_DIR; set UPDATER_BIND_PATH"
    )


def finished(info: dict[str, Any]) -> bool:
    finished_at = str(info.get("finished_at") or "")
    return bool(finished_at) and not finished_at.startswith("0001-01-01")
