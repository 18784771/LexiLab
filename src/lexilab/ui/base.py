from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from lexilab.models.word import WordEntry


@dataclass
class RatingResult:
    rating: int | None = None
    answer: str = ""
    hinted: bool = False
    duration_ms: int = 0
    skipped: bool = False
    quit: bool = False


@dataclass
class ProductionPrompt:
    meaning: str
    pos: str = ""
    cloze: str = ""
    example_cn: str = ""
    hint: str = ""


@dataclass
class FeedbackView:
    expected: str
    given: str
    correct: bool | None
    message: str = ""
    diagnosis: str = ""
    reference_sentence: str = ""
    suggested_rating: int | None = None
    extra: dict = field(default_factory=dict)


class SessionUI(Protocol):
    def notify(self, message: str, style: str = "info") -> None:
        ...

    def ask_new_word(self, entry: WordEntry, position: str) -> int:
        """Return 1 know, 2 unsure, 3 unknown, 0 quit."""

    def show_word_info(self, entry: WordEntry) -> bool:
        """Show the compact learning card. Return False to quit."""

    def ask_recognition(self, entry: WordEntry, position: str, *, mode: str = "review") -> RatingResult:
        ...

    def ask_production(
        self, entry: WordEntry, prompt: ProductionPrompt, position: str
    ) -> RatingResult:
        ...

    def show_feedback(self, feedback: FeedbackView) -> int | None:
        """Show grading feedback and return a rating (1-4) or None to quit before rating."""

    def ask_reinforcement(self, entry: WordEntry, position: str) -> bool | None:
        """Short-term re-check without a new FSRS review. None means quit."""

    def show_summary(self, summary: dict) -> None:
        ...
