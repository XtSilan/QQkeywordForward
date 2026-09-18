import hashlib
import json
from typing import Any

import httpx

from app.settings import Settings


class NapCatClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._session_credential = ""

    def _headers(self, credential: str = "") -> dict[str, str]:
        credential = credential or self._session_credential or self.settings.napcat_webui_credential
        if not credential:
            return {}
        return {"Authorization": f"Bearer {credential}"}

    async def authenticate(self) -> str:
        if self._session_credential:
            return self._session_credential
        if self.settings.napcat_webui_credential:
            return self.settings.napcat_webui_credential
        if not self.settings.napcat_webui_token:
            return ""
        digest = hashlib.sha256(
            f"{self.settings.napcat_webui_token}.napcat".encode("utf-8")
        ).hexdigest()
        url = self.settings.napcat_webui_url.rstrip("/") + "/api/auth/login"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, json={"hash": digest})
        response.raise_for_status()
        payload = response.json()
        credential = payload.get("data", {}).get("Credential", "")
        if not credential:
            raise RuntimeError(payload.get("message", "NapCat authentication failed"))
        self._session_credential = credential
        return credential

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = self.settings.napcat_webui_url.rstrip("/") + path
        credential = await self.authenticate()
        headers = {**self._headers(credential), **kwargs.pop("headers", {})}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
        if response.status_code == 401 and self._session_credential:
            self._session_credential = ""
            credential = await self.authenticate()
            headers = {**self._headers(credential), **kwargs.pop("headers", {})}
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("code") not in (None, 0):
            raise RuntimeError(payload.get("message", "NapCat API request failed"))
        return payload.get("data", payload) if isinstance(payload, dict) else payload

    async def login_status(self) -> Any:
        return await self.request("POST", "/api/QQLogin/CheckLoginStatus")

    async def qrcode(self) -> Any:
        return await self.request("POST", "/api/QQLogin/GetQQLoginQrcode")

    async def refresh_qrcode(self) -> Any:
        return await self.request("POST", "/api/QQLogin/RefreshQRcode")

    async def login_info(self) -> Any:
        return await self.request("POST", "/api/QQLogin/GetQQLoginInfo")

    async def quick_login_list(self) -> Any:
        return await self.request("GET", "/api/QQLogin/GetQuickLoginList")

    async def quick_login(self, payload: dict[str, Any]) -> Any:
        return await self.request("POST", "/api/QQLogin/SetQuickLogin", json=payload)

    async def password_login(self, payload: dict[str, Any]) -> Any:
        return await self.request("POST", "/api/QQLogin/PasswordLogin", json=payload)

    async def restart(self) -> Any:
        return await self.request("POST", "/api/QQLogin/RestartNapCat")

    async def restart_process(self) -> Any:
        return await self.request("POST", "/api/Process/Restart")

    async def log_list(self) -> Any:
        return await self.request("GET", "/api/Log/GetLogList")

    async def log_file(self, filename: str) -> Any:
        if ".." in filename or "/" in filename or "\\" in filename:
            raise ValueError("invalid log filename")
        return await self.request(
            "GET", "/api/Log/GetLog", params={"id": filename}
        )

    async def onebot_config(self) -> Any:
        return await self.request("POST", "/api/OB11Config/GetConfig")

    async def set_onebot_config(self, config: dict[str, Any]) -> Any:
        return await self.request(
            "POST", "/api/OB11Config/SetConfig",
            json={"config": json.dumps(config, ensure_ascii=False)},
        )
