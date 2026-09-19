from pydantic import BaseModel, Field


class SmtpSettingsPayload(BaseModel):
    host: str = Field(default="", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    username: str = Field(default="", max_length=320)
    password: str = Field(default="", max_length=500)
    from_address: str = Field(default="", max_length=320)
    starttls: bool = True
    ssl: bool = False
    timeout: int = Field(default=15, ge=1, le=120)


class DuplicateMessageSettingsPayload(BaseModel):
    threshold: int = Field(default=2, ge=2, le=100)
    cooldown_minutes: int = Field(default=10, ge=1, le=1440)


class OneBotWebsocketPayload(BaseModel):
    enable: bool = False
    url: str = Field(min_length=1, max_length=1000)
    reconnectInterval: int = Field(default=5000, ge=100, le=3600000)
    heartInterval: int = Field(default=30000, ge=1000, le=3600000)
    verifyCertificate: bool = True
    token: str | None = Field(default=None, max_length=500)
