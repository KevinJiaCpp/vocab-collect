from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ListDirection = Literal["w2m", "bidirectional"]
StudyDirection = Literal["w2m", "m2w"]
WordStatus = Literal["active", "familiar", "useless"]
SessionKind = Literal["learning", "review"]


class AuthInput(BaseModel):
    username: str
    password: str


class SettingsInput(BaseModel):
    learn_batch_size: int = Field(ge=1, le=100)
    review_batch_size: int = Field(ge=1, le=100)
    pool_multiplier: float = Field(default=1.5, ge=1, le=3)
    exclude_multiword_expressions: bool = False


class WordListInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    direction: ListDirection = "w2m"
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("List name is required")
        return value


class WordListPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    direction: ListDirection | None = None
    is_active: bool | None = None


class EntryInput(BaseModel):
    word: str = Field(min_length=1, max_length=240)


class WordStatusInput(BaseModel):
    status: WordStatus


class NoteInput(BaseModel):
    body: str = Field(max_length=20000)
    display_word: str | None = Field(default=None, max_length=240)


class StudyStartInput(BaseModel):
    kind: SessionKind
    direction: StudyDirection = "w2m"
    override_due: bool = False


class PresentationInput(BaseModel):
    presentation_token: str


class AnswerInput(PresentationInput):
    rating: int = Field(ge=1, le=4)
    duration_ms: int | None = Field(default=None, ge=0, le=3600000)
