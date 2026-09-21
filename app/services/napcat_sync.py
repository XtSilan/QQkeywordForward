"""Keeps NapCat's OneBot WebSocket client in sync with the configured URL.

Runs as a background loop so a deployment only has to set ``ONEBOT_WS_URL``
instead of wiring the reverse-WS client through the NapCat WebUI by hand.
"""
from __future__ import annotations

import asyncio
import logging

from app.napcat import NapCatClient
from app.settings import Settings


SYNC_INTERVAL_SECONDS = 30
ONEBOT_HTTP_PORT = 3001

logger = logging.getLogger("napcat_sync")


async def _apply_once(settings: Settings, client: NapCatClient) -> None:
    status = await client.login_status()
    if not (isinstance(status, dict) and status.get("isLogin")):
        return
    config = await client.onebot_config()
    network = (config if isinstance(config, dict) else {}).setdefault("network", {})
    clients = network.setdefault("websocketClients", [])
    item = next((value for value in clients if value.get("name") == "websocket-client"), None)
    client_changed = False
    if item is None:
        item = {
            "name": "websocket-client",
            "messagePostFormat": "array",
            "reportSelfMessage": False,
            "debug": False,
            "heartInterval": 30000,
            "reconnectInterval": 5000,
        }
        clients.append(item)
        client_changed = True
    # Push whenever url / enable / token drift from the environment, which is
    # the single source of truth now that the WebUI form is gone. Other fields
    # are left alone so a hand-tuned NapCat config is not clobbered.
    if (
        item.get("url") != settings.onebot_ws_url
        or not item.get("enable")
        or item.get("token", "") != settings.onebot_access_token
    ):
        item["enable"] = True
        item["url"] = settings.onebot_ws_url
        item["token"] = settings.onebot_access_token
        client_changed = True

    # NapCat stores OneBot config per QQ account (onebot11_<uin>.json), so
    # every login switch starts from a file without any network config. Make
    # sure the OneBot HTTP server exists too — the WebUI logout endpoint
    # (/bot_exit) goes through it.
    servers = network.setdefault("httpServers", [])
    server = next((value for value in servers if value.get("name") == "http-server"), None)
    server_changed = False
    if server is None:
        server = {
            "name": "http-server",
            "enable": True,
            "port": ONEBOT_HTTP_PORT,
            "host": "0.0.0.0",
            "enableCors": False,
            "enableWebsocket": True,
            "messagePostFormat": "array",
            "debug": False,
        }
        servers.append(server)
        server_changed = True
    try:
        server_port = int(server.get("port") or 0)
    except (TypeError, ValueError):
        server_port = 0
    if (
        not server.get("enable")
        or server_port != ONEBOT_HTTP_PORT
        or server.get("token", "") != settings.onebot_access_token
    ):
        server["enable"] = True
        server["port"] = ONEBOT_HTTP_PORT
        server["token"] = settings.onebot_access_token
        server_changed = True

    if client_changed or server_changed:
        await client.set_onebot_config(config)


async def run_onebot_sync(settings: Settings) -> None:
    client = NapCatClient(settings)
    while True:
        try:
            await _apply_once(settings, client)
        except Exception as exc:
            logger.warning("onebot sync failed: %s", exc)
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
