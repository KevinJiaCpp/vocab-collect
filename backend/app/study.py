from __future__ import annotations

import json
import math
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from fsrs import Card as FSRSCard
from fsrs import Rating, Scheduler, State
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .dictionary_service import dictionary_service
from .models import (
    Card,
    ReviewLog,
    StudyQueueItem,
    StudySession,
    StudySettings,
    User,
    WordList,
    WordListEntry,
    WordProgress,
    utcnow,
)


LEARNING_STEPS = (
    timedelta(minutes=1),
    timedelta(minutes=10),
    timedelta(hours=1),
    timedelta(days=1),
)


def _scheduler(user: User) -> Scheduler:
    kwargs: dict[str, Any] = {
        "learning_steps": LEARNING_STEPS,
        "relearning_steps": LEARNING_STEPS,
    }
    if user.fsrs_parameters:
        kwargs["parameters"] = tuple(json.loads(user.fsrs_parameters))
    return Scheduler(**kwargs)


def _state_value(card: FSRSCard) -> int:
    state = card.state
    return int(state.value if hasattr(state, "value") else state)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _get_or_create_settings(db: Session, user_id: int) -> StudySettings:
    value = db.get(StudySettings, user_id)
    if value is None:
        value = StudySettings(user_id=user_id)
        db.add(value)
        db.flush()
    return value


def active_words(db: Session, user_id: int, direction: str) -> list[tuple[str, str]]:
    lists = db.scalars(
        select(WordList).where(WordList.user_id == user_id, WordList.is_active.is_(True)).order_by(WordList.id)
    ).all()
    buckets: list[list[WordListEntry]] = []
    for word_list in lists:
        if direction == "m2w" and word_list.direction != "bidirectional":
            continue
        entries = db.scalars(
            select(WordListEntry)
            .where(WordListEntry.word_list_id == word_list.id, WordListEntry.has_definition.is_(True))
            .order_by(WordListEntry.position)
        ).all()
        buckets.append(list(entries))
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    cursor = 0
    while any(cursor < len(bucket) for bucket in buckets):
        for bucket in buckets:
            if cursor < len(bucket):
                entry = bucket[cursor]
                if entry.normalized_word not in seen:
                    result.append((entry.normalized_word, entry.word))
                    seen.add(entry.normalized_word)
        cursor += 1
    return result


def _get_or_create_progress(db: Session, user_id: int, normalized: str, display: str) -> WordProgress:
    progress = db.scalar(
        select(WordProgress).where(
            WordProgress.user_id == user_id,
            WordProgress.normalized_word == normalized,
        )
    )
    if progress is None:
        progress = WordProgress(user_id=user_id, normalized_word=normalized, display_word=display)
        db.add(progress)
        db.flush()
    return progress


def _get_or_create_card(db: Session, user_id: int, normalized: str, direction: str) -> Card:
    card = db.scalar(
        select(Card).where(
            Card.user_id == user_id,
            Card.normalized_word == normalized,
            Card.direction == direction,
        )
    )
    if card is None:
        fsrs_card = FSRSCard(card_id=secrets.randbits(53))
        card = Card(
            user_id=user_id,
            normalized_word=normalized,
            direction=direction,
            fsrs_json=fsrs_card.to_json(),
            state=_state_value(fsrs_card),
            due=fsrs_card.due,
            last_review=fsrs_card.last_review,
        )
        db.add(card)
        db.flush()
    return card


def study_overview(db: Session, user: User) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    words_w2m = active_words(db, user.id, "w2m")
    words_m2w = active_words(db, user.id, "m2w")
    active_w2m = {word for word, _ in words_w2m}
    active_m2w = {word for word, _ in words_m2w}
    excluded = set(db.scalars(select(WordProgress.normalized_word).where(
        WordProgress.user_id == user.id, WordProgress.status != "active"
    )).all())
    cards = db.scalars(select(Card).where(Card.user_id == user.id)).all()
    due = {"w2m": 0, "m2w": 0}
    studied = {"w2m": set(), "m2w": set()}
    forward_review = {card.normalized_word for card in cards if card.direction == "w2m" and card.state == int(State.Review.value)}
    for card in cards:
        if card.state != int(State.Learning.value):
            studied[card.direction].add(card.normalized_word)
        allowed = active_w2m if card.direction == "w2m" else active_m2w
        if card.normalized_word in allowed and card.normalized_word not in excluded and _aware(card.due) <= now and card.state != int(State.Learning.value):
            if card.direction == "w2m" or card.normalized_word in forward_review:
                due[card.direction] += 1
    new_w2m = len(active_w2m - studied["w2m"] - excluded)
    new_m2w = len({word for word in active_m2w if word in forward_review} - studied["m2w"] - excluded)
    active_sessions = db.scalars(select(StudySession).where(
        StudySession.user_id == user.id, StudySession.status == "active"
    ).order_by(StudySession.created_at.desc())).all()
    settings = _get_or_create_settings(db, user.id)
    db.commit()
    return {
        "due": due,
        "new": {"w2m": new_w2m, "m2w": new_m2w},
        "settings": {
            "learn_batch_size": settings.learn_batch_size,
            "review_batch_size": settings.review_batch_size,
            "pool_multiplier": settings.pool_multiplier,
            "exclude_multiword_expressions": settings.exclude_multiword_expressions,
        },
        "active_sessions": [session_summary(session) for session in active_sessions],
    }


def create_study_session(db: Session, user: User, kind: str, direction: str, override_due: bool) -> StudySession:
    if kind not in {"learning", "review"} or direction not in {"w2m", "m2w"}:
        raise HTTPException(422, "Invalid session kind or direction")
    existing = db.scalar(select(StudySession).where(
        StudySession.user_id == user.id,
        StudySession.status == "active",
        StudySession.kind == kind,
        StudySession.direction == direction,
    ).order_by(StudySession.created_at.desc()))
    if existing:
        return existing
    overview = study_overview(db, user)
    if kind == "learning" and sum(overview["due"].values()) and not override_due:
        raise HTTPException(409, {"code": "reviews_due", "message": "Review is due before learning."})
    settings = _get_or_create_settings(db, user.id)
    target = settings.learn_batch_size if kind == "learning" else settings.review_batch_size
    limit = math.ceil(target * settings.pool_multiplier) if kind == "learning" else target
    candidates = active_words(db, user.id, direction)
    cards: list[Card] = []
    now = datetime.now(timezone.utc)
    for normalized, display in candidates:
        if len(cards) >= limit:
            break
        progress = _get_or_create_progress(db, user.id, normalized, display)
        if progress.status != "active":
            continue
        if direction == "m2w":
            forward = db.scalar(select(Card).where(
                Card.user_id == user.id,
                Card.normalized_word == normalized,
                Card.direction == "w2m",
            ))
            if forward is None or forward.state != int(State.Review.value):
                continue
        if kind == "learning":
            card = _get_or_create_card(db, user.id, normalized, direction)
        else:
            card = db.scalar(select(Card).where(
                Card.user_id == user.id,
                Card.normalized_word == normalized,
                Card.direction == direction,
            ))
            if card is None:
                continue
        if kind == "learning" and card.state != int(State.Learning.value):
            continue
        if kind == "review" and (card.state == int(State.Learning.value) or _aware(card.due) > now):
            continue
        cards.append(card)
    pool_size = len(cards)
    selected = cards
    session = StudySession(
        user_id=user.id,
        kind=kind,
        direction=direction,
        target_count=target,
        pool_size=pool_size,
    )
    db.add(session)
    db.flush()
    for index, card in enumerate(selected):
        db.add(StudyQueueItem(
            study_session_id=session.id,
            card_id=card.id,
            order_value=float(index),
            was_initial_review=kind == "review",
        ))
    if not selected:
        session.status = "completed"
        session.completed_at = utcnow()
    db.commit()
    db.refresh(session)
    return session


def session_summary(session: StudySession) -> dict[str, Any]:
    return {
        "id": session.id,
        "kind": session.kind,
        "direction": session.direction,
        "target_count": min(session.target_count, session.pool_size),
        "pool_size": session.pool_size,
        "completed_count": session.completed_count,
        "status": session.status,
        "created_at": session.created_at,
        "completed_at": session.completed_at,
    }


def _entry_payload(db: Session, card: Card, include_answer: bool) -> dict[str, Any]:
    progress = db.scalar(select(WordProgress).where(
        WordProgress.user_id == card.user_id,
        WordProgress.normalized_word == card.normalized_word,
    ))
    display = progress.display_word if progress else card.normalized_word
    entry = dictionary_service.lookup(display)
    senses = entry["senses"] if entry else []
    if card.direction == "w2m":
        prompt: dict[str, Any] = {"word": display}
        answer = entry or {"word": display, "senses": [], "pronunciations": [], "morphology": None}
    else:
        prompt = {"senses": senses}
        answer = entry or {"word": display, "senses": senses, "pronunciations": [], "morphology": None}
    payload: dict[str, Any] = {"card_id": card.id, "direction": card.direction, "prompt": prompt}
    if include_answer:
        payload["answer"] = answer
    return payload


def next_prompt(db: Session, user: User, session_id: int) -> dict[str, Any]:
    session = db.get(StudySession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Study session not found")
    if session.status != "active":
        return {"session": session_summary(session), "item": None}
    if session.current_item_id:
        item = db.get(StudyQueueItem, session.current_item_id)
    else:
        item = db.scalar(select(StudyQueueItem).where(
            StudyQueueItem.study_session_id == session.id,
            StudyQueueItem.status == "queued",
        ).order_by(StudyQueueItem.order_value, StudyQueueItem.id))
        if item:
            item.status = "current"
            session.current_item_id = item.id
            session.presentation_token = secrets.token_urlsafe(24)
            session.revealed = False
            db.commit()
    if item is None:
        session.status = "completed"
        session.completed_at = utcnow()
        db.commit()
        return {"session": session_summary(session), "item": None}
    card = db.get(Card, item.card_id)
    assert card is not None
    return {
        "session": session_summary(session),
        "presentation_token": session.presentation_token,
        "revealed": session.revealed,
        "item": _entry_payload(db, card, session.revealed),
    }


def reveal_prompt(db: Session, user: User, session_id: int, token: str) -> dict[str, Any]:
    session = db.get(StudySession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Study session not found")
    if session.presentation_token != token or not session.current_item_id:
        raise HTTPException(409, "This card presentation is stale")
    session.revealed = True
    item = db.get(StudyQueueItem, session.current_item_id)
    card = db.get(Card, item.card_id) if item else None
    if card is None:
        raise HTTPException(409, "Current card is unavailable")
    db.commit()
    return {
        "session": session_summary(session),
        "presentation_token": token,
        "revealed": True,
        "item": _entry_payload(db, card, True),
    }


def _requeue(db: Session, session: StudySession, item: StudyQueueItem, rating: int) -> None:
    orders = list(db.scalars(select(StudyQueueItem.order_value).where(
        StudyQueueItem.study_session_id == session.id,
        StudyQueueItem.status == "queued",
    ).order_by(StudyQueueItem.order_value)).all())
    if rating == int(Rating.Again.value):
        if len(orders) >= 2:
            new_order = (orders[0] + orders[1]) / 2
        elif orders:
            new_order = orders[0] + 0.5
        else:
            new_order = item.order_value + 1
    elif rating == int(Rating.Hard.value):
        if orders:
            midpoint = len(orders) // 2
            new_order = orders[midpoint] - 0.25
        else:
            new_order = item.order_value + 1
    else:
        new_order = (max(orders) + 1) if orders else item.order_value + 1
    item.order_value = new_order
    item.status = "queued"


def answer_prompt(
    db: Session,
    user: User,
    session_id: int,
    token: str,
    rating_value: int,
    duration_ms: int | None,
) -> dict[str, Any]:
    previous = db.scalar(select(ReviewLog).where(ReviewLog.presentation_token == token))
    if previous:
        session = db.get(StudySession, session_id)
        if session is None or session.user_id != user.id:
            raise HTTPException(404, "Study session not found")
        return {"session": session_summary(session), "duplicate": True}
    session = db.get(StudySession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Study session not found")
    if session.presentation_token != token or not session.current_item_id or not session.revealed:
        raise HTTPException(409, "Reveal the current card before grading it")
    if rating_value not in {1, 2, 3, 4}:
        raise HTTPException(422, "Rating must be between 1 and 4")
    item = db.get(StudyQueueItem, session.current_item_id)
    card = db.get(Card, item.card_id) if item else None
    if item is None or card is None:
        raise HTTPException(409, "Current card is unavailable")
    fsrs_card = FSRSCard.from_json(card.fsrs_json)
    before_json = fsrs_card.to_json()
    reviewed_at = datetime.now(timezone.utc)
    next_card, log = _scheduler(user).review_card(
        fsrs_card,
        Rating(rating_value),
        review_datetime=reviewed_at,
        review_duration=duration_ms,
    )
    card.fsrs_json = next_card.to_json()
    card.state = _state_value(next_card)
    card.due = next_card.due
    card.last_review = next_card.last_review
    db.add(ReviewLog(
        user_id=user.id,
        card_id=card.id,
        study_session_id=session.id,
        presentation_token=token,
        rating=rating_value,
        reviewed_at=reviewed_at,
        duration_ms=duration_ms,
        session_kind=session.kind,
        before_json=before_json,
        after_json=next_card.to_json(),
        fsrs_log_json=log.to_json(),
    ))
    item.attempts += 1
    graduated = card.state == int(State.Review.value)
    if session.kind == "learning":
        if graduated:
            item.status = "done"
            session.completed_count += 1
        else:
            _requeue(db, session, item, rating_value)
    else:
        if card.state == int(State.Relearning.value):
            _requeue(db, session, item, rating_value)
        else:
            item.status = "done"
            session.completed_count += 1
    session.current_item_id = None
    session.presentation_token = None
    session.revealed = False
    remaining = db.scalar(select(func.count()).select_from(StudyQueueItem).where(
        StudyQueueItem.study_session_id == session.id,
        StudyQueueItem.status.in_(["queued", "current"]),
    )) or 0
    if (session.kind == "learning" and session.completed_count >= session.target_count) or remaining == 0:
        session.status = "completed"
        session.completed_at = utcnow()
        if remaining:
            for queued in db.scalars(select(StudyQueueItem).where(
                StudyQueueItem.study_session_id == session.id,
                StudyQueueItem.status.in_(["queued", "current"]),
            )):
                queued.status = "deferred"
    db.commit()
    return {"session": session_summary(session), "duplicate": False}


def abandon_session(db: Session, user: User, session_id: int) -> dict[str, Any]:
    session = db.get(StudySession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Study session not found")
    if session.status == "active":
        session.status = "abandoned"
        session.completed_at = utcnow()
        for item in db.scalars(select(StudyQueueItem).where(
            StudyQueueItem.study_session_id == session.id,
            StudyQueueItem.status.in_(["queued", "current"]),
        )):
            item.status = "deferred"
        db.commit()
    return session_summary(session)


def skip_word(db: Session, user: User, session_id: int, token: str, status: str) -> dict[str, Any]:
    session = db.get(StudySession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Study session not found")
    if session.presentation_token != token or not session.current_item_id:
        raise HTTPException(409, "This card presentation is stale")
    if status not in {"familiar", "useless"}:
        raise HTTPException(422, "Invalid exclusion status")
    item = db.get(StudyQueueItem, session.current_item_id)
    card = db.get(Card, item.card_id) if item else None
    if item is None or card is None:
        raise HTTPException(409, "Current card is unavailable")
    progress = db.scalar(select(WordProgress).where(
        WordProgress.user_id == user.id,
        WordProgress.normalized_word == card.normalized_word,
    ))
    if progress is None:
        raise HTTPException(409, "Word progress is unavailable")
    progress.status = status
    for queued in db.scalars(select(StudyQueueItem).join(Card, Card.id == StudyQueueItem.card_id).where(
        StudyQueueItem.study_session_id == session.id,
        Card.normalized_word == card.normalized_word,
        StudyQueueItem.status.in_(["queued", "current"]),
    )):
        queued.status = "deferred"
    session.current_item_id = None
    session.presentation_token = None
    session.revealed = False
    remaining = db.scalar(select(func.count()).select_from(StudyQueueItem).where(
        StudyQueueItem.study_session_id == session.id,
        StudyQueueItem.status == "queued",
    )) or 0
    if remaining == 0:
        session.status = "completed"
        session.completed_at = utcnow()
    db.commit()
    return session_summary(session)
