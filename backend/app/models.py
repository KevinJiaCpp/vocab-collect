from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32))
    username_key: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    fsrs_parameters: Mapped[str | None] = mapped_column(Text, nullable=True)
    optimizer_status: Mapped[str] = mapped_column(String(16), default="idle")
    optimizer_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    optimized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginSession(Base):
    __tablename__ = "login_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudySettings(Base):
    __tablename__ = "study_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    learn_batch_size: Mapped[int] = mapped_column(Integer, default=10)
    review_batch_size: Mapped[int] = mapped_column(Integer, default=20)
    pool_multiplier: Mapped[float] = mapped_column(Float, default=1.5)
    exclude_multiword_expressions: Mapped[bool] = mapped_column(Boolean, default=False)


class LLMSettings(Base):
    __tablename__ = "llm_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    base_url: Mapped[str] = mapped_column(String(2048))
    model: Mapped[str] = mapped_column(String(200))
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExampleSentenceCache(Base):
    __tablename__ = "example_sentence_cache"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    word: Mapped[str] = mapped_column(String(240), primary_key=True)
    sense_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)


class WordList(Base):
    __tablename__ = "word_lists"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_word_lists_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    direction: Mapped[str] = mapped_column(String(16), default="w2m")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    entries: Mapped[list[WordListEntry]] = relationship(
        back_populates="word_list", cascade="all, delete-orphan", order_by="WordListEntry.position"
    )
    notes: Mapped[list[ListNote]] = relationship(back_populates="word_list", cascade="all, delete-orphan")


class WordListEntry(Base):
    __tablename__ = "word_list_entries"
    __table_args__ = (
        UniqueConstraint("word_list_id", "normalized_word", name="uq_entries_list_word"),
        Index("idx_entries_list_position", "word_list_id", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    word_list_id: Mapped[int] = mapped_column(ForeignKey("word_lists.id", ondelete="CASCADE"))
    word: Mapped[str] = mapped_column(String(240))
    normalized_word: Mapped[str] = mapped_column(String(240), index=True)
    position: Mapped[int] = mapped_column(Integer)
    has_definition: Mapped[bool] = mapped_column(Boolean, default=True)

    word_list: Mapped[WordList] = relationship(back_populates="entries")
    notes: Mapped[list[ListNote]] = relationship(secondary="note_entries", back_populates="entries", passive_deletes=True)


class WordProgress(Base):
    __tablename__ = "word_progress"
    __table_args__ = (UniqueConstraint("user_id", "normalized_word", name="uq_progress_user_word"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    normalized_word: Mapped[str] = mapped_column(String(240), index=True)
    display_word: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_word", "direction", name="uq_cards_user_word_direction"),
        Index("idx_cards_user_due", "user_id", "due"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    normalized_word: Mapped[str] = mapped_column(String(240), index=True)
    direction: Mapped[str] = mapped_column(String(4))
    fsrs_json: Mapped[str] = mapped_column(Text)
    state: Mapped[int] = mapped_column(Integer, default=1, index=True)
    due: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_review: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    study_session_id: Mapped[int | None] = mapped_column(ForeignKey("study_sessions.id", ondelete="SET NULL"), nullable=True)
    presentation_token: Mapped[str] = mapped_column(String(64), unique=True)
    rating: Mapped[int] = mapped_column(Integer)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_kind: Mapped[str] = mapped_column(String(12))
    before_json: Mapped[str] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text)
    fsrs_log_json: Mapped[str] = mapped_column(Text)


note_entries = Table(
    "note_entries",
    Base.metadata,
    Column("note_id", ForeignKey("list_notes.id", ondelete="CASCADE"), primary_key=True),
    Column("entry_id", ForeignKey("word_list_entries.id", ondelete="CASCADE"), primary_key=True),
    Index("idx_note_entries_entry", "entry_id"),
)


class ListNote(Base):
    __tablename__ = "list_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    word_list_id: Mapped[int] = mapped_column(ForeignKey("word_lists.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    word_list: Mapped[WordList] = relationship(back_populates="notes")
    entries: Mapped[list[WordListEntry]] = relationship(
        secondary=note_entries, back_populates="notes", order_by="WordListEntry.position", passive_deletes=True
    )


class StudySession(Base):
    __tablename__ = "study_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    direction: Mapped[str] = mapped_column(String(4))
    target_count: Mapped[int] = mapped_column(Integer)
    pool_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    current_item_id: Mapped[int | None] = mapped_column(ForeignKey("study_queue_items.id", ondelete="SET NULL"), nullable=True)
    presentation_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revealed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StudyQueueItem(Base):
    __tablename__ = "study_queue_items"
    __table_args__ = (Index("idx_queue_session_status_order", "study_session_id", "status", "order_value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    study_session_id: Mapped[int] = mapped_column(ForeignKey("study_sessions.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    order_value: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    was_initial_review: Mapped[bool] = mapped_column(Boolean, default=False)


class DictionaryTerm(Base):
    __tablename__ = "dictionary_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(String(240))
    normalized_term: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    search_term: Mapped[str] = mapped_column(String(240), index=True)


class AudioCache(Base):
    __tablename__ = "audio_cache"

    normalized_word: Mapped[str] = mapped_column(String(240), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
