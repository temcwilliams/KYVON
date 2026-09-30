"""Request validation (Pydantic)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

MAX_TEXT = 10_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ChatRequest(_Strict):
    message: str = Field(max_length=MAX_TEXT)
    environment: str | None = Field(default=None, max_length=MAX_TEXT)


class EnvironmentRequest(_Strict):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
