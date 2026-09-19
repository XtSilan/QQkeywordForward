from pydantic import BaseModel, Field


class DestinationCreate(BaseModel):
    kind: str = Field(pattern="^(qq|email)$")
    address: str = Field(min_length=3, max_length=320)
    display_name: str = Field(default="", max_length=100)


class DestinationUpdate(BaseModel):
    kind: str = Field(pattern="^(qq|email)$")
    address: str = Field(min_length=3, max_length=320)
    display_name: str = Field(default="", max_length=100)
    enabled: bool = True
    group_ids: list[str] = Field(default_factory=list)


class NotificationChannelPayload(BaseModel):
    kind: str = Field(pattern="^(qq|email)$")
    address: str = Field(min_length=3, max_length=320)
    display_name: str = Field(default="", max_length=100)


class NotificationConfigCreate(BaseModel):
    channels: list[NotificationChannelPayload] = Field(min_length=1, max_length=100)
    group_ids: list[str] = Field(min_length=1)


class NotificationSettingsPayload(BaseModel):
    qq_enabled: bool = False
    email_enabled: bool = False
    destination_ids: list[int] = Field(default_factory=list)


class NotificationBulkApply(BaseModel):
    group_ids: list[str] = Field(min_length=1)
    qq_enabled: bool = False
    email_enabled: bool = False
    destination_ids: list[int] = Field(default_factory=list)
