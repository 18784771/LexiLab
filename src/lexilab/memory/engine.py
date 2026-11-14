from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from fsrs import Card, Rating, Scheduler

from lexilab.storage.learning_repo import LearningRepository

DIRECTIONS = ("recognition", "recall")


@dataclass
class ReviewOutcome:
    word_key: str
    direction: str
    rating: int
    card: dict
    scheduled_days: float
    elapsed_days: float
    state_before: int
    state_after: int


class MemoryService:
    """Thin wrapper around Py-FSRS. It never invents its own scheduling math."""

    def __init__(self, repo: LearningRepository, desired_retention: float = 0.90) -> None:
        self.repo = repo
        self.desired_retention = desired_retention
        parameters = self._load_parameters()
        if parameters:
            self.scheduler = Scheduler(parameters=parameters, desired_retention=desired_retention)
        else:
            self.scheduler = Scheduler(desired_retention=desired_retention)
            self.persist_parameters()

    def _load_parameters(self) -> list[float] | None:
        raw = self.repo.get_setting("fsrs.parameters")
        if not raw:
            return None
        try:
            values = json.loads(raw)
            if isinstance(values, list) and len(values) >= 17:
                return [float(v) for v in values]
        except (ValueError, TypeError):
            return None
        return None

    def persist_parameters(self) -> None:
        default = list(Scheduler().parameters)
        self.repo.set_setting("fsrs.parameters", json.dumps(default))
        self.repo.set_setting("fsrs.desired_retention", str(self.desired_retention))

    # ------------------------------------------------------------------ cards
    def ensure_cards(self, word_key: str, *, recall_suspended: bool = True) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for direction in DIRECTIONS:
            existing = self.repo.get_card(word_key, direction)
            if existing:
                result[direction] = dict(existing)
                continue
            card = Card()
            created = self.repo.create_card(
                word_key,
                direction,
                card.to_dict(),
                suspended=(direction == "recall" and recall_suspended),
            )
            result[direction] = created
        return result

    def ensure_recognition_card(self, word_key: str) -> dict:
        existing = self.repo.get_card(word_key, "recognition")
        if existing:
            return dict(existing)
        return self.repo.create_card(word_key, "recognition", Card().to_dict())

    @staticmethod
    def _row_to_card(row) -> Card:
        data = {
            "card_id": row["card_id"],
            "state": row["state"],
            "step": row["step"],
            "stability": row["stability"],
            "difficulty": row["difficulty"],
            "due": row["due"],
            "last_review": row["last_review"],
        }
        return Card.from_dict(data)

    @staticmethod
    def _elapsed_days(row, now: datetime) -> float:
        if not row["last_review"]:
            return 0.0
        try:
            last = datetime.fromisoformat(row["last_review"])
        except ValueError:
            return 0.0
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return max(0.0, (now - last).total_seconds() / 86400.0)

    def review(
        self,
        card_row,
        rating: int | Rating,
        *,
        duration_ms: int | None = None,
        now: datetime | None = None,
    ) -> ReviewOutcome:
        if not 1 <= int(rating) <= 4:
            raise ValueError("rating must be 1..4")
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        card = self._row_to_card(card_row)
        state_before = int(card.state)
        elapsed = self._elapsed_days(card_row, now)
        updated, log = self.scheduler.review_card(
            card,
            Rating(int(rating)),
            review_datetime=now,
            review_duration=duration_ms,
        )
        card_dict = updated.to_dict()
        log_dict = log.to_dict()
        due_at = updated.due
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        scheduled_days = max(0.0, (due_at - now).total_seconds() / 86400.0)
        self.repo.save_review(
            int(card_row["id"]),
            card_dict,
            log_dict,
            rating=int(rating),
            duration_ms=duration_ms,
            elapsed_days=elapsed,
            scheduled_days=scheduled_days,
            state_before=state_before,
            now=now,
        )
        return ReviewOutcome(
            word_key=card_row["word_key"],
            direction=card_row["direction"],
            rating=int(rating),
            card=card_dict,
            scheduled_days=scheduled_days,
            elapsed_days=elapsed,
            state_before=state_before,
            state_after=int(card_dict.get("state", 1)),
        )

    def retrievability(self, card_row, now: datetime | None = None) -> float | None:
        try:
            card = self._row_to_card(card_row)
            value = self.scheduler.get_card_retrievability(card, now or datetime.now(timezone.utc))
            return float(value)
        except Exception:
            return None

    def due_in_days(self, card_row) -> float | None:
        try:
            due = datetime.fromisoformat(card_row["due"])
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            return (due - datetime.now(timezone.utc)).total_seconds() / 86400.0
        except (ValueError, TypeError):
            return None
