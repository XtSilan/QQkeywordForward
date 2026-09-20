from pydantic import BaseModel, Field


class KeywordCreate(BaseModel):
    display_text: str = Field(min_length=1, max_length=200)
    group_ids: list[str] = Field(default_factory=list)
    enabled: bool = False
    cooldown_seconds: int = Field(default=60, ge=0, le=86400)


class KeywordConfigCreate(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=100)
    group_ids: list[str] = Field(min_length=1)
    destination_ids: list[int] = Field(default_factory=list)
    enabled: bool = True
    cooldown_seconds: int = Field(default=60, ge=0, le=86400)


class KeywordNotificationUpdate(BaseModel):
    destination_ids: list[int] = Field(default_factory=list)


class KeywordUpdate(BaseModel):
    display_text: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)


class KeywordBulkApply(BaseModel):
    keyword_id: int
    group_ids: list[str] = Field(min_length=1)
    enabled: bool = False
    cooldown_seconds: int = Field(default=60, ge=0, le=86400)
    replace_existing: bool = False


class KeywordBulkUpdate(BaseModel):
    keyword_ids: list[int] = Field(min_length=1)
    enabled: bool


class KeywordReorder(BaseModel):
    keyword_ids: list[int] = Field(default_factory=list)
    alphabetical: bool = False
