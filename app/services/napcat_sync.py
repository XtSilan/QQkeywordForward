"""Keeps NapCat's OneBot WebSocket client in sync with the configured URL.

Runs as a background loop so a deployment only has to set ``ONEBOT_WS_URL``
instead of wiring the reverse-WS client through the NapCat WebUI by hand.
"""
from __future__ import annotations

import asyncio

from app.napcat import NapCatClient
from app.settings import Settings


SYNC_INTERVAL_SECONDS = 30


async def _apply_once(settings: Settings, client: NapCatClient) -> None:
    status = await client.login_status()
    if not (isinstance(status, dict) and status.get("isLogin")):
        return
    config = await client.onebot_config()
    network = (config if isinstance(config, dict) else {}).setdefault("network", {})
    clients = network.setdefault("websocketClients", [])
    item = next((value for value in clients if value.get("name") == "websocket-client"), None)
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
    # Only push when missing or mismatched; avoids fighting a user who manually
    # customised other fields in the NapCat WebUI.
    if item.get("url") != settings.onebot_ws_url or not item.get("enable"):
        item["enable"] = True
        item["url"] = settings.onebot_ws_url
        if settings.onebot_access_token:
            item["token"] = settings.onebot_access_token
        await client.set_onebot_config(config)


async def run_onebot_sync(settings: Settings) -> None:
    client = NapCatClient(settings)
    while True:
        try:
            await _apply_once(settings, client)
        except Exception:
            pass
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
