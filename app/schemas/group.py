from pydantic import BaseModel, Field


class GroupPayload(BaseModel):
    group_id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=200)
    avatar_url: str = Field(default="", max_length=1000)
