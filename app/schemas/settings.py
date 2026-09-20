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


class AlertDedupSettingsPayload(BaseModel):
    """Order-fingerprint dedup knobs consumed by ``app.services.orders``."""

    enabled: bool = True
    similarity: float = Field(default=0.8, ge=0.1, le=1.0)
    window_minutes: int = Field(default=60, ge=1, le=1440)
    max_push_per_order: int = Field(default=2, ge=1, le=10)
    new_phone_repush: bool = True
    ad_filter_enabled: bool = True
    ad_keywords: str = Field(default="", max_length=500)
