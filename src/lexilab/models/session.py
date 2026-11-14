from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ItemType(StrEnum):
    NEW_INTRO = "new_intro"
    NEW_RECALL = "new_recall"
    REVIEW_RECOGNITION = "review_recognition"
    REVIEW_RECALL = "review_recall"
    REINFORCE = "reinforce"
    VERIFY = "verify"
    READ = "read"
    LISTEN = "listen"
    WRITE = "write"


@dataclass
class PlanItem:
    item_type: ItemType
    word_key: str
    direction: str | None = None
    card_row_id: int | None = None
    payload: dict = field(default_factory=dict)


@dataclass
class SessionPlan:
    kind: str
    items: list[PlanItem] = field(default_factory=list)
    due_count: int = 0
    new_count: int = 0
    estimated_seconds: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.items
