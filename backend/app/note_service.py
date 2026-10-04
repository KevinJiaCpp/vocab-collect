from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from .dictionary_service import normalize_word
from .models import ListNote, WordList, WordListEntry


def note_payload(note: ListNote) -> dict[str, Any]:
    return {
        "id": note.id,
        "word_list_id": note.word_list_id,
        "list_name": note.word_list.name,
        "body": note.body,
        "words": [{"id": entry.id, "word": entry.word, "normalized_word": entry.normalized_word} for entry in note.entries],
        "updated_at": note.updated_at,
    }


def list_notes(db: Session, user_id: int, *, q: str = "", list_id: int | None = None,
               word: str | None = None, active_only: bool = False) -> list[dict[str, Any]]:
    statement = select(ListNote).join(WordList).where(WordList.user_id == user_id).options(
        joinedload(ListNote.word_list), selectinload(ListNote.entries),
    )
    if list_id is not None:
        statement = statement.where(ListNote.word_list_id == list_id)
    if word is not None:
        statement = statement.where(ListNote.entries.any(WordListEntry.normalized_word == normalize_word(word)))
    if active_only:
        statement = statement.where(WordList.is_active.is_(True))
    if q.strip():
        statement = statement.where(or_(
            ListNote.body.contains(q.strip()), WordList.name.contains(q.strip()),
            ListNote.entries.any(WordListEntry.normalized_word.contains(normalize_word(q))),
        ))
    return [note_payload(note) for note in db.scalars(statement.order_by(ListNote.updated_at.desc(), ListNote.id.desc()))]


def owned_note(db: Session, user_id: int, note_id: int) -> ListNote:
    note = db.scalar(select(ListNote).join(WordList).where(ListNote.id == note_id, WordList.user_id == user_id))
    if note is None:
        raise HTTPException(404, "Note not found")
    return note


def note_word_entries(db: Session, list_id: int, entry_ids: list[int]) -> list[WordListEntry]:
    entries = list(db.scalars(select(WordListEntry).where(
        WordListEntry.word_list_id == list_id, WordListEntry.id.in_(entry_ids),
    ).order_by(WordListEntry.position)))
    if len(entries) != len(entry_ids):
        raise HTTPException(422, "Every attached word must belong to this word list")
    return entries
