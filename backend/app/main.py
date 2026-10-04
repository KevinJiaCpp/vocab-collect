from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import COOKIE_NAME, clear_login_session, create_login_session, get_current_user, password_hash
from .config import REPO_ROOT, settings
from .db import get_db
from .dictionary_service import dictionary_service, normalize_word, resolve_audio
from .llm_service import example_sense_key, generate_examples
from .models import (
    Card,
    DictionaryTerm,
    ExampleSentenceCache,
    LLMSettings,
    ListNote,
    ReviewLog,
    StudySettings,
    User,
    WordList,
    WordListEntry,
    WordProgress,
    note_entries,
    utcnow,
)
from .note_service import list_notes, note_payload, note_word_entries, owned_note
from .optimizer_service import optimize_user
from .schemas import (
    AnswerInput,
    AuthInput,
    EntryInput,
    ExampleSentencesInput,
    ExampleSentencesOutput,
    LLMSettingsInput,
    LLMSettingsOutput,
    NoteInput,
    PresentationInput,
    SettingsInput,
    StudyStartInput,
    WordListInput,
    WordListPatch,
    WordStatusInput,
)
from .study import (
    abandon_session,
    answer_prompt,
    create_study_session,
    next_prompt,
    reveal_prompt,
    session_summary,
    skip_word,
    study_overview,
)


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


app = FastAPI(title="Vocab Collect API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.origin_set),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        allowed_origins = settings.origin_set | {str(request.base_url).rstrip("/")}
        if origin and origin.rstrip("/") not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "Request origin is not allowed"})
    return await call_next(request)


def _user_payload(user: User) -> dict[str, Any]:
    return {"id": user.id, "username": user.username, "created_at": user.created_at}


@app.post("/api/auth/register", status_code=201)
def register(payload: AuthInput, response: Response, db: Session = Depends(get_db)):
    username = payload.username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(422, "Username must be 3–32 letters, numbers, dots, underscores, or hyphens")
    if not 10 <= len(payload.password) <= 128:
        raise HTTPException(422, "Password must be 10–128 characters")
    user = User(username=username, username_key=username.casefold(), password_hash=password_hash.hash(payload.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "That username is already registered") from exc
    db.add(StudySettings(user_id=user.id))
    db.commit()
    db.refresh(user)
    create_login_session(db, user, response)
    return _user_payload(user)


@app.post("/api/auth/login")
def login(payload: AuthInput, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username_key == payload.username.strip().casefold()))
    if user is None or not password_hash.verify(payload.password, user.password_hash):
        raise HTTPException(401, "Username or password is incorrect")
    create_login_session(db, user, response)
    return _user_payload(user)


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    clear_login_session(db, response, request.cookies.get(COOKIE_NAME))
    response.status_code = 204
    return response


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)):
    return _user_payload(user)


def _get_settings(db: Session, user_id: int) -> StudySettings:
    value = db.get(StudySettings, user_id)
    if value is None:
        value = StudySettings(user_id=user_id)
        db.add(value)
        db.commit()
        db.refresh(value)
    return value


@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = _get_settings(db, user.id)
    return {
        "learn_batch_size": value.learn_batch_size,
        "review_batch_size": value.review_batch_size,
        "pool_multiplier": value.pool_multiplier,
        "exclude_multiword_expressions": value.exclude_multiword_expressions,
    }


@app.put("/api/settings")
def update_settings(payload: SettingsInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = _get_settings(db, user.id)
    value.learn_batch_size = payload.learn_batch_size
    value.review_batch_size = payload.review_batch_size
    value.pool_multiplier = payload.pool_multiplier
    value.exclude_multiword_expressions = payload.exclude_multiword_expressions
    db.commit()
    return payload.model_dump()


def _llm_settings_payload(value: LLMSettings | None) -> LLMSettingsOutput:
    if value is None:
        return LLMSettingsOutput(base_url="https://api.openai.com/v1", model="", has_api_key=False)
    return LLMSettingsOutput(base_url=value.base_url, model=value.model, has_api_key=bool(value.api_key))


@app.get("/api/settings/llm", response_model=LLMSettingsOutput)
def get_llm_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _llm_settings_payload(db.get(LLMSettings, user.id))


@app.put("/api/settings/llm", response_model=LLMSettingsOutput)
def update_llm_settings(payload: LLMSettingsInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = db.get(LLMSettings, user.id)
    if value is None:
        value = LLMSettings(user_id=user.id)
        db.add(value)
    value.base_url = str(payload.base_url).rstrip("/")
    value.model = payload.model
    if payload.api_key is not None:
        value.api_key = payload.api_key.get_secret_value().strip() or None
    db.commit()
    return _llm_settings_payload(value)


def _owned_list(db: Session, user_id: int, list_id: int) -> WordList:
    value = db.scalar(select(WordList).where(WordList.id == list_id, WordList.user_id == user_id))
    if value is None:
        raise HTTPException(404, "Word list not found")
    return value


def _list_payload(db: Session, value: WordList, include_entries: bool = False) -> dict[str, Any]:
    entries = db.scalars(select(WordListEntry).where(WordListEntry.word_list_id == value.id).order_by(WordListEntry.position)).all()
    payload: dict[str, Any] = {
        "id": value.id,
        "name": value.name,
        "direction": value.direction,
        "is_active": value.is_active,
        "word_count": len(entries),
        "unavailable_count": sum(not entry.has_definition for entry in entries),
        "note_count": db.scalar(select(func.count()).select_from(ListNote).where(ListNote.word_list_id == value.id)),
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }
    if include_entries:
        note_counts = dict(db.execute(select(note_entries.c.entry_id, func.count()).join(
            ListNote, ListNote.id == note_entries.c.note_id,
        ).where(ListNote.word_list_id == value.id).group_by(note_entries.c.entry_id)).all())
        payload["entries"] = [{"id": entry.id, "word": entry.word, "normalized_word": entry.normalized_word, "position": entry.position, "has_definition": entry.has_definition, "note_count": note_counts.get(entry.id, 0)} for entry in entries]
    return payload


@app.get("/api/lists")
def lists(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    values = db.scalars(select(WordList).where(WordList.user_id == user.id).order_by(WordList.created_at)).all()
    return [_list_payload(db, value) for value in values]


@app.post("/api/lists", status_code=201)
def create_list(payload: WordListInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = WordList(user_id=user.id, **payload.model_dump())
    db.add(value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A list with that name already exists") from exc
    db.refresh(value)
    return _list_payload(db, value, True)


@app.get("/api/lists/{list_id}")
def get_list(list_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _list_payload(db, _owned_list(db, user.id, list_id), True)


@app.patch("/api/lists/{list_id}")
def update_list(list_id: int, payload: WordListPatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = _owned_list(db, user.id, list_id)
    for key, update in payload.model_dump(exclude_unset=True).items():
        if key == "name" and update is not None:
            update = " ".join(update.strip().split())
        setattr(value, key, update)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A list with that name already exists") from exc
    return _list_payload(db, value, True)


@app.delete("/api/lists/{list_id}", status_code=204)
def delete_list(list_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(_owned_list(db, user.id, list_id))
    db.commit()
    return Response(status_code=204)


def _add_entry(db: Session, user_id: int, value: WordList, word: str) -> WordListEntry:
    display = " ".join(word.strip().split())
    normalized = normalize_word(display)
    if not normalized:
        raise HTTPException(422, "Word is required")
    if db.scalar(select(WordListEntry.id).where(WordListEntry.word_list_id == value.id, WordListEntry.normalized_word == normalized)):
        raise HTTPException(409, "That word is already in this list")
    position = db.scalar(select(func.coalesce(func.max(WordListEntry.position), -1)).where(WordListEntry.word_list_id == value.id)) + 1
    entry = WordListEntry(word_list_id=value.id, word=display, normalized_word=normalized, position=position, has_definition=dictionary_service.has_definition(db, display))
    db.add(entry)
    if not db.scalar(select(WordProgress.id).where(WordProgress.user_id == user_id, WordProgress.normalized_word == normalized)):
        db.add(WordProgress(user_id=user_id, normalized_word=normalized, display_word=display))
    db.flush()
    return entry


@app.post("/api/lists/{list_id}/entries", status_code=201)
def add_entry(list_id: int, payload: EntryInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = _owned_list(db, user.id, list_id)
    entry = _add_entry(db, user.id, value, payload.word)
    db.commit()
    return {"id": entry.id, "word": entry.word, "normalized_word": entry.normalized_word, "position": entry.position, "has_definition": entry.has_definition, "note_count": 0}


@app.delete("/api/lists/{list_id}/entries/{entry_id}", status_code=204)
def remove_entry(list_id: int, entry_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = _owned_list(db, user.id, list_id)
    entry = db.scalar(select(WordListEntry).where(WordListEntry.id == entry_id, WordListEntry.word_list_id == value.id))
    if entry is None:
        raise HTTPException(404, "List entry not found")
    db.delete(entry)
    db.flush()
    remaining = db.scalars(select(WordListEntry).where(WordListEntry.word_list_id == value.id).order_by(WordListEntry.position)).all()
    for index, item in enumerate(remaining):
        item.position = index
    db.commit()
    return Response(status_code=204)


@app.post("/api/lists/{list_id}/shuffle")
def shuffle_list(list_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = _owned_list(db, user.id, list_id)
    entries = list(db.scalars(select(WordListEntry).where(WordListEntry.word_list_id == value.id).order_by(WordListEntry.position)).all())
    random.SystemRandom().shuffle(entries)
    for index, entry in enumerate(entries):
        entry.position = index
    db.commit()
    return _list_payload(db, value, True)


def _parse_list_import(content: str) -> tuple[str, str, list[str], list[dict[str, Any]]]:
    try:
        value = json.loads(content)
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] not in {1, 2}:
            raise ValueError("Use a version 1 or version 2 Vocab Collect JSON file")
        name = value.get("name")
        direction = value.get("direction", "w2m")
        words = value.get("words")
        notes = value.get("notes", [])
        if not isinstance(name, str) or not 1 <= len(" ".join(name.split())) <= 120:
            raise ValueError("Imported list name must be 1–120 characters")
        if direction not in {"w2m", "bidirectional"}:
            raise ValueError("Imported list direction is not supported")
        if not isinstance(words, list) or not all(isinstance(word, str) and 1 <= len(word) <= 240 and normalize_word(word) for word in words):
            raise ValueError("Imported words must be 1–240 characters")
        normalized = {normalize_word(word) for word in words}
        if len(normalized) != len(words):
            raise ValueError("Imported words must be unique, ignoring case and spacing")
        if not isinstance(notes, list) or (value["version"] == 1 and notes):
            raise ValueError("Notes require a version 2 JSON file")
        for note in notes:
            if not isinstance(note, dict) or not isinstance(note.get("body"), str) or not 1 <= len(note["body"].strip()) <= 20000:
                raise ValueError("Imported note text must be 1–20000 characters")
            links = note.get("words")
            if not isinstance(links, list) or not all(isinstance(word, str) and normalize_word(word) in normalized for word in links):
                raise ValueError("Every note word must belong to the imported word list")
            if len({normalize_word(word) for word in links}) != len(links):
                raise ValueError("A note cannot link the same word twice")
        return " ".join(name.split()), direction, words, notes
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc) or "Invalid Vocab Collect JSON file") from exc


@app.post("/api/lists/import", status_code=201)
async def import_list(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not (file.filename or "").casefold().endswith(".json"):
        raise HTTPException(422, "Import a Vocab Collect JSON file")
    try:
        content = (await file.read()).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "Import file must be UTF-8 JSON") from exc
    name, imported_direction, words, imported_notes = _parse_list_import(content)
    value = WordList(user_id=user.id, name=name, direction=imported_direction, is_active=True)
    db.add(value)
    try:
        db.flush()
        entries = {normalize_word(raw): _add_entry(db, user.id, value, raw) for raw in words}
        for imported_note in imported_notes:
            db.add(ListNote(word_list_id=value.id, body=imported_note["body"].strip(), entries=[entries[normalize_word(word)] for word in imported_note["words"]]))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A list with that name already exists") from exc
    except HTTPException:
        db.rollback()
        raise
    return _list_payload(db, value, True)


@app.get("/api/lists/{list_id}/export")
def export_list(list_id: int, format: str = Query("json", pattern="^json$"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = _owned_list(db, user.id, list_id)
    entries = db.scalars(select(WordListEntry).where(WordListEntry.word_list_id == value.id).order_by(WordListEntry.position)).all()
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.name).strip("-") or "word-list"
    exported_notes = [{"body": note["body"], "words": [entry["word"] for entry in note["words"]]} for note in sorted(list_notes(db, user.id, list_id=list_id), key=lambda note: note["id"])]
    body = json.dumps({"version": 2, "name": value.name, "direction": value.direction, "words": [entry.word for entry in entries], "notes": exported_notes}, ensure_ascii=False, indent=2)
    return Response(body, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'})


@app.get("/api/words/learned")
def learned_words(q: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    statement = select(Card, WordProgress).outerjoin(
        WordProgress,
        (WordProgress.user_id == Card.user_id) & (WordProgress.normalized_word == Card.normalized_word),
    ).where(Card.user_id == user.id)
    if q.strip():
        statement = statement.where(Card.normalized_word.contains(normalize_word(q)))
    output: dict[str, dict[str, Any]] = {}
    for card, progress in db.execute(statement.order_by(WordProgress.updated_at.desc(), Card.created_at.desc())):
        item = output.setdefault(card.normalized_word, {
            "word": progress.display_word if progress else card.normalized_word,
            "normalized_word": card.normalized_word,
            "status": progress.status if progress else "active",
            "cards": [],
        })
        item["cards"].append({"direction": card.direction, "state": card.state, "due": card.due})
    return list(output.values())


@app.put("/api/words/{word}/status")
def set_word_status(word: str, payload: WordStatusInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    normalized = normalize_word(word)
    progress = db.scalar(select(WordProgress).where(WordProgress.user_id == user.id, WordProgress.normalized_word == normalized))
    if progress is None:
        progress = WordProgress(user_id=user.id, normalized_word=normalized, display_word=word, status=payload.status)
        db.add(progress)
    else:
        progress.status = payload.status
    db.commit()
    return {"word": progress.display_word, "normalized_word": normalized, "status": progress.status}


@app.get("/api/notes")
def notes(q: str = "", list_id: int | None = None, word: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return list_notes(db, user.id, q=q, list_id=list_id, word=word)


@app.post("/api/lists/{list_id}/notes", status_code=201)
def create_note(list_id: int, payload: NoteInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = _owned_list(db, user.id, list_id)
    note = ListNote(word_list=value, body=payload.body, entries=note_word_entries(db, list_id, payload.entry_ids))
    db.add(note)
    db.commit()
    return note_payload(note)


@app.get("/api/words/{word}/lists")
def word_lists(word: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    normalized = normalize_word(word)
    entries = db.scalars(select(WordListEntry).join(WordList, WordList.id == WordListEntry.word_list_id).where(WordList.user_id == user.id, WordListEntry.normalized_word == normalized)).all()
    entry_ids = {entry.word_list_id: entry.id for entry in entries}
    values = db.scalars(select(WordList).where(WordList.user_id == user.id).order_by(WordList.created_at)).all()
    return [{"id": value.id, "name": value.name, "contains": value.id in entry_ids, "entry_id": entry_ids.get(value.id)} for value in values]


@app.put("/api/notes/{note_id}")
def put_note(note_id: int, payload: NoteInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = owned_note(db, user.id, note_id)
    value.entries = note_word_entries(db, value.word_list_id, payload.entry_ids)
    value.body = payload.body
    value.updated_at = utcnow()
    db.commit()
    return note_payload(value)


@app.delete("/api/notes/{note_id}", status_code=204)
def delete_note(note_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(owned_note(db, user.id, note_id))
    db.commit()
    return Response(status_code=204)


@app.get("/api/dictionary/search")
def dictionary_search(q: str, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.scalar(select(func.count()).select_from(DictionaryTerm)):
        raise HTTPException(503, {"code": "lexicon_unavailable", "message": "Dictionary data is missing. Run scripts/bootstrap_data.py."})
    settings = _get_settings(db, user.id)
    return dictionary_service.search(db, q, page, page_size, settings.exclude_multiword_expressions)


@app.get("/api/dictionary/{word}/audio")
async def dictionary_audio(word: str, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    try:
        return await resolve_audio(db, word)
    except LookupError as exc:
        offline = "offline" in str(exc)
        raise HTTPException(503 if offline else 404, {"code": "audio_unavailable" if offline else "audio_not_found", "message": str(exc)}) from exc


@app.get("/api/dictionary/{word}")
def dictionary_entry(word: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not dictionary_service.available():
        raise HTTPException(503, {"code": "lexicon_unavailable", "message": "Dictionary data is missing. Run scripts/bootstrap_data.py."})
    value = dictionary_service.lookup(word)
    if value is None:
        raise HTTPException(404, "No dictionary entry was found")
    value["notes"] = list_notes(db, user.id, word=word)
    cached = {row.sense_key: json.loads(row.payload_json) for row in db.scalars(select(ExampleSentenceCache).where(
        ExampleSentenceCache.user_id == user.id, ExampleSentenceCache.word == value["word"],
    ))}
    value["senses"] = [{**sense, "generated_examples": cached.get(example_sense_key(sense), [])} for sense in value["senses"]]
    return value


@app.post("/api/dictionary/{word}/examples", response_model=ExampleSentencesOutput)
async def dictionary_examples(word: str, payload: ExampleSentencesInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    config = db.get(LLMSettings, user.id)
    if config is None or not config.model:
        raise HTTPException(409, "Configure a language model in Settings → LLM to generate examples.")
    entry = dictionary_service.lookup(word)
    if entry is None:
        raise HTTPException(404, "No dictionary entry was found")
    if payload.sense_index >= len(entry["senses"]):
        raise HTTPException(404, "This word sense is unavailable. Reload the word and try again.")
    examples = await generate_examples(config, entry["word"], entry["senses"][payload.sense_index])
    sense_key = example_sense_key(entry["senses"][payload.sense_index])
    # Replace atomically; failed generation leaves the previous examples intact.
    db.execute(delete(ExampleSentenceCache).where(
        ExampleSentenceCache.user_id == user.id, ExampleSentenceCache.word == entry["word"], ExampleSentenceCache.sense_key == sense_key,
    ))
    db.add(ExampleSentenceCache(user_id=user.id, word=entry["word"], sense_key=sense_key, payload_json=json.dumps(examples, ensure_ascii=False)))
    db.commit()
    return ExampleSentencesOutput(examples=examples)


@app.delete("/api/dictionary/{word}/examples/{sense_index}", status_code=204)
def clear_dictionary_examples(word: str, sense_index: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    entry = dictionary_service.lookup(word)
    if entry is None:
        raise HTTPException(404, "No dictionary entry was found")
    if not 0 <= sense_index < len(entry["senses"]):
        raise HTTPException(404, "This word sense is unavailable. Reload the word and try again.")
    db.execute(delete(ExampleSentenceCache).where(
        ExampleSentenceCache.user_id == user.id, ExampleSentenceCache.word == entry["word"],
        ExampleSentenceCache.sense_key == example_sense_key(entry["senses"][sense_index]),
    ))
    db.commit()
    return Response(status_code=204)


@app.get("/api/study/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return study_overview(db, user)


@app.post("/api/study/sessions", status_code=201)
def start_session(payload: StudyStartInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return session_summary(create_study_session(db, user, payload.kind, payload.direction, payload.override_due))


@app.get("/api/study/sessions/{session_id}/next")
def get_next(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return next_prompt(db, user, session_id)


@app.post("/api/study/sessions/{session_id}/reveal")
def reveal(session_id: int, payload: PresentationInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return reveal_prompt(db, user, session_id, payload.presentation_token)


@app.post("/api/study/sessions/{session_id}/answer")
def answer(session_id: int, payload: AnswerInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return answer_prompt(db, user, session_id, payload.presentation_token, payload.rating, payload.duration_ms)


@app.post("/api/study/sessions/{session_id}/abandon")
def abandon(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return abandon_session(db, user, session_id)


@app.post("/api/study/sessions/{session_id}/skip")
def skip(session_id: int, payload: dict[str, str], db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return skip_word(db, user, session_id, payload.get("presentation_token", ""), payload.get("status", ""))


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    overview_value = study_overview(db, user)
    active_lists = db.scalar(select(func.count()).select_from(WordList).where(WordList.user_id == user.id, WordList.is_active.is_(True))) or 0
    status_counts = dict(db.execute(select(WordProgress.status, func.count()).where(WordProgress.user_id == user.id).group_by(WordProgress.status)).all())
    def period(days: int) -> dict[str, int]:
        rows = db.execute(select(func.count(), func.sum(case((ReviewLog.rating > 1, 1), else_=0))).where(
            ReviewLog.user_id == user.id, ReviewLog.reviewed_at >= now - timedelta(days=days)
        )).one()
        return {"reviews": int(rows[0] or 0), "remembered": int(rows[1] or 0)}
    learned = db.scalar(select(func.count(func.distinct(Card.normalized_word))).join(
        WordProgress,
        (WordProgress.user_id == Card.user_id) & (WordProgress.normalized_word == Card.normalized_word),
    ).where(Card.user_id == user.id, Card.state == 2, WordProgress.status == "active")) or 0
    return {
        "due": overview_value["due"],
        "active_lists": active_lists,
        "learned": learned,
        "familiar": status_counts.get("familiar", 0),
        "useless": status_counts.get("useless", 0),
        "activity_7d": period(7),
        "activity_30d": period(30),
    }


@app.get("/api/optimizer")
def optimizer_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    count = db.scalar(select(func.count()).select_from(ReviewLog).where(ReviewLog.user_id == user.id)) or 0
    return {"review_count": count, "required": 400, "eligible": count >= 400, "status": user.optimizer_status, "error": user.optimizer_error, "optimized_at": user.optimized_at}


@app.post("/api/optimizer", status_code=202)
def run_optimizer(background_tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    count = db.scalar(select(func.count()).select_from(ReviewLog).where(ReviewLog.user_id == user.id)) or 0
    if count < 400:
        raise HTTPException(409, f"{400 - count} more reviews are required")
    if user.optimizer_status == "running":
        raise HTTPException(409, "Optimization is already running")
    user.optimizer_status = "running"
    user.optimizer_error = None
    db.commit()
    background_tasks.add_task(optimize_user, user.id)
    return {"status": "running"}


@app.get("/api/licenses")
def licenses(_user: User = Depends(get_current_user)):
    path = REPO_ROOT / "THIRD_PARTY_NOTICES.md"
    sections = [path.read_text(encoding="utf-8")]
    for name in ("CMUDICT.txt", "WNDB.txt", "OEWN.txt"):
        license_file = REPO_ROOT / "licenses" / name
        if license_file.exists():
            sections.append(f"\n\n--- {name} ---\n\n{license_file.read_text(encoding='utf-8')}")
    return {"text": "\n".join(sections)}


DIST_DIR = REPO_ROOT / "frontend" / "dist"
if DIST_DIR.exists():
    assets = DIST_DIR / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "API route not found")
    candidate = DIST_DIR / full_path
    if full_path and candidate.is_file() and DIST_DIR in candidate.resolve().parents:
        return FileResponse(candidate)
    index = DIST_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(status_code=503, content={"detail": "Frontend has not been built. Run the setup script."})
