from __future__ import annotations

from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr, field_validator


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


class LLMSettingsInput(BaseModel):
    base_url: AnyHttpUrl = Field(max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    # Omitted/null preserves the stored key; an empty string removes it.
    api_key: SecretStr | None = Field(default=None, max_length=4096)

    @field_validator("base_url")
    @classmethod
    def clean_base_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("Use an API base URL without credentials, query parameters, or a fragment")
        return value

    @field_validator("model", mode="before")
    @classmethod
    def clean_model(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class LLMSettingsOutput(BaseModel):
    base_url: str
    model: str
    has_api_key: bool


class ExampleSentencesInput(BaseModel):
    sense_index: int = Field(ge=0, le=1000)


class ExampleSentencesOutput(BaseModel):
    examples: list[str]


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
    body: str = Field(min_length=1, max_length=20000)
    entry_ids: list[int]

    @field_validator("body", mode="before")
    @classmethod
    def clean_body(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("entry_ids")
    @classmethod
    def validate_entries(cls, value: list[int]) -> list[int]:
        if any(entry_id <= 0 for entry_id in value) or len(set(value)) != len(value):
            raise ValueError("Choose distinct word entries")
        return value


class StudyStartInput(BaseModel):
    kind: SessionKind
    direction: StudyDirection = "w2m"
    override_due: bool = False


class PresentationInput(BaseModel):
    presentation_token: str


class AnswerInput(PresentationInput):
    rating: int = Field(ge=1, le=4)
    duration_ms: int | None = Field(default=None, ge=0, le=3600000)
