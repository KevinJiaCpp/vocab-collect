from __future__ import annotations

import json
from datetime import datetime, timezone

from fsrs import Card as FSRSCard
from fsrs import Optimizer, ReviewLog as FSRSReviewLog, Scheduler
from sqlalchemy import select

from .db import SessionLocal
from .models import Card, ReviewLog, User, WordProgress


def optimize_user(user_id: int) -> None:
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            return
        logs = db.scalars(select(ReviewLog).where(ReviewLog.user_id == user_id)).all()
        if len(logs) < 400:
            user.optimizer_status = "idle"
            user.optimizer_error = "At least 400 reviews are required."
            db.commit()
            return
        fsrs_logs = [FSRSReviewLog.from_json(row.fsrs_log_json) for row in logs]
        parameters = Optimizer(fsrs_logs).compute_optimal_parameters()
        scheduler = Scheduler(parameters=parameters)
        cards = db.scalars(select(Card).where(Card.user_id == user_id)).all()
        for card in cards:
            progress = db.scalar(select(WordProgress).where(
                WordProgress.user_id == user_id,
                WordProgress.normalized_word == card.normalized_word,
            ))
            if progress and progress.status != "active":
                continue
            card_logs = [
                FSRSReviewLog.from_json(row.fsrs_log_json)
                for row in logs
                if row.card_id == card.id
            ]
            if not card_logs:
                continue
            updated = scheduler.reschedule_card(FSRSCard.from_json(card.fsrs_json), card_logs)
            card.fsrs_json = updated.to_json()
            card.state = int(updated.state.value if hasattr(updated.state, "value") else updated.state)
            card.due = updated.due
            card.last_review = updated.last_review
        user.fsrs_parameters = json.dumps(list(parameters))
        user.optimizer_status = "complete"
        user.optimizer_error = None
        user.optimized_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        user = db.get(User, user_id)
        if user:
            user.optimizer_status = "failed"
            user.optimizer_error = str(exc)[:1000]
            db.commit()
    finally:
        db.close()

