from pydantic import BaseModel, Field


class AdminLoginPayload(BaseModel):
    token: str = Field(min_length=1, max_length=500)
