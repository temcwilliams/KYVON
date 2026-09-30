"""Request validation (Pydantic)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

MAX_TEXT = 10_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ChatRequest(_Strict):
    message: str = Field(max_length=MAX_TEXT)
    conversation_id: int | None = Field(default=None, ge=1)


class ConversationCreate(_Strict):
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(_Strict):
    title: str | None = Field(default=None, max_length=200)
    archived: bool | None = None


class EnvironmentRequest(_Strict):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class LoginRequest(_Strict):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    device_name: str = Field(default="", max_length=100)
    # True for the web client: the token goes in an HttpOnly cookie, not the body.
    cookie: bool = False


class MemoryCreate(_Strict):
    text: str = Field(min_length=1, max_length=2000)
    category: str | None = Field(default=None, max_length=32)
    importance: int | None = None


class MemoryUpdate(_Strict):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    category: str | None = Field(default=None, max_length=32)
    importance: int | None = None
