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
