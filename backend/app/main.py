from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import COOKIE_NAME, clear_login_session, create_login_session, get_current_user, password_hash
from .config import REPO_ROOT, settings
from .db import get_db
from .dictionary_service import dictionary_service, normalize_word, resolve_audio
from .models import (
    Card,
    DictionaryTerm,
    Note,
    ReviewLog,
    StudySettings,
    User,
    WordList,
    WordListEntry,
    WordProgress,
)
from .optimizer_service import optimize_user
from .schemas import (
    AnswerInput,
    AuthInput,
    EntryInput,
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
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }
    if include_entries:
        payload["entries"] = [{"id": entry.id, "word": entry.word, "normalized_word": entry.normalized_word, "position": entry.position, "has_definition": entry.has_definition} for entry in entries]
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
    return {"id": entry.id, "word": entry.word, "normalized_word": entry.normalized_word, "position": entry.position, "has_definition": entry.has_definition}


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


def _parse_text_import(text: str, fallback_name: str, fallback_direction: str) -> tuple[str, str, list[str]]:
    name = fallback_name
    direction = fallback_direction
    words: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# name:"):
            name = stripped.split(":", 1)[1].strip() or name
        elif stripped.startswith("# direction:"):
            direction = stripped.split(":", 1)[1].strip()
        elif not stripped.startswith("#"):
            words.append(stripped)
    return name, direction, words


@app.post("/api/lists/import", status_code=201)
async def import_list(
    file: UploadFile = File(...),
    direction: str = Form("w2m"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if direction not in {"w2m", "bidirectional"}:
        raise HTTPException(422, "Invalid list direction")
    try:
        content = (await file.read()).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "Import file must be UTF-8 text") from exc
    fallback_name = Path(file.filename or "Imported list").stem[:120]
    if (file.filename or "").casefold().endswith(".json"):
        try:
            parsed = json.loads(content)
            if not isinstance(parsed, dict) or parsed.get("version") != 1 or not isinstance(parsed.get("name"), str) or not isinstance(parsed.get("words"), list) or not all(isinstance(word, str) and 0 < len(word) <= 240 for word in parsed["words"]):
                raise ValueError
            name, imported_direction, words = parsed.get("name", fallback_name), parsed.get("direction", direction), parsed["words"]
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(422, "Invalid Vocab Collect JSON file") from exc
    else:
        name, imported_direction, words = _parse_text_import(content, fallback_name, direction)
    if imported_direction not in {"w2m", "bidirectional"}:
        raise HTTPException(422, "Imported list direction is not supported")
    name = " ".join(str(name).strip().split())
    if not 1 <= len(name) <= 120:
        raise HTTPException(422, "Imported list name must be 1–120 characters")
    value = WordList(user_id=user.id, name=name, direction=imported_direction, is_active=True)
    db.add(value)
    try:
        db.flush()
        seen: set[str] = set()
        for raw in words:
            normalized = normalize_word(str(raw))
            if not normalized or len(str(raw)) > 240:
                raise HTTPException(422, "Imported words must be 1–240 characters")
            if normalized in seen:
                raise HTTPException(409, f"Duplicate word in import: {raw}")
            _add_entry(db, user.id, value, str(raw))
            seen.add(normalized)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A list with that name already exists") from exc
    return _list_payload(db, value, True)


@app.get("/api/lists/{list_id}/export")
def export_list(list_id: int, format: str = Query("json", pattern="^(json|txt)$"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = _owned_list(db, user.id, list_id)
    entries = db.scalars(select(WordListEntry).where(WordListEntry.word_list_id == value.id).order_by(WordListEntry.position)).all()
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.name).strip("-") or "word-list"
    if format == "txt":
        body = "\n".join(["# vocab-collect: 1", f"# name: {value.name}", f"# direction: {value.direction}", *[entry.word for entry in entries]]) + "\n"
        return PlainTextResponse(body, headers={"Content-Disposition": f'attachment; filename="{safe_name}.txt"'})
    body = json.dumps({"version": 1, "name": value.name, "direction": value.direction, "words": [entry.word for entry in entries]}, ensure_ascii=False, indent=2)
    return Response(body, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'})


@app.get("/api/words/learned")
def learned_words(q: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    statement = select(WordProgress).where(WordProgress.user_id == user.id)
    if q.strip():
        statement = statement.where(WordProgress.normalized_word.contains(normalize_word(q)))
    values = db.scalars(statement.order_by(WordProgress.updated_at.desc())).all()
    output = []
    for value in values:
        cards = db.scalars(select(Card).where(Card.user_id == user.id, Card.normalized_word == value.normalized_word)).all()
        output.append({"word": value.display_word, "normalized_word": value.normalized_word, "status": value.status, "cards": [{"direction": card.direction, "state": card.state, "due": card.due} for card in cards]})
    return output


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
def notes(q: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    statement = select(Note).where(Note.user_id == user.id)
    if q.strip():
        key = normalize_word(q)
        statement = statement.where((Note.normalized_word.contains(key)) | (Note.body.contains(q.strip())))
    return [{"word": value.display_word, "normalized_word": value.normalized_word, "body": value.body, "updated_at": value.updated_at} for value in db.scalars(statement.order_by(Note.updated_at.desc())).all()]


@app.get("/api/words/{word}/note")
def get_note(word: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    value = db.scalar(select(Note).where(Note.user_id == user.id, Note.normalized_word == normalize_word(word)))
    return {"word": value.display_word if value else word, "body": value.body if value else "", "updated_at": value.updated_at if value else None}


@app.put("/api/words/{word}/note")
def put_note(word: str, payload: NoteInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    normalized = normalize_word(word)
    value = db.scalar(select(Note).where(Note.user_id == user.id, Note.normalized_word == normalized))
    display = payload.display_word or word
    if value is None:
        value = Note(user_id=user.id, normalized_word=normalized, display_word=display, body=payload.body)
        db.add(value)
    else:
        value.body = payload.body
        value.display_word = display
    db.commit()
    return {"word": value.display_word, "normalized_word": normalized, "body": value.body, "updated_at": value.updated_at}


@app.delete("/api/words/{word}/note", status_code=204)
def delete_note(word: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.execute(delete(Note).where(Note.user_id == user.id, Note.normalized_word == normalize_word(word)))
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
    note = db.scalar(select(Note).where(Note.user_id == user.id, Note.normalized_word == normalize_word(word)))
    value["note"] = note.body if note else ""
    return value


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
