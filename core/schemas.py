from pydantic import BaseModel, Field

from .config import settings


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8_000)
    model: str = settings.default_model
    system: str | None = Field(default=None, max_length=2_000)


class RagRequest(ChatRequest):
    top_k: int = Field(default=3, ge=1, le=5)


class SummarizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    model: str = settings.default_model
    max_sentences: int = Field(default=3, ge=1, le=10)
