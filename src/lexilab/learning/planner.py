from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lexilab.config.settings import Settings
from lexilab.models.session import ItemType, PlanItem, SessionPlan
from lexilab.storage.learning_repo import LearningRepository
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.memory.engine import MemoryService


def _local_day_bounds(day_offset: int = 0) -> tuple[str, str]:
    local_now = datetime.now().astimezone()
    start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(timezone.utc).isoformat(),
        end_local.astimezone(timezone.utc).isoformat(),
    )


class Planner:
    def __init__(
        self,
        settings: Settings,
        repo: LearningRepository,
        vocab: VocabularyRepository,
        memory: MemoryService,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.vocab = vocab
        self.memory = memory

    def today_new_count(self) -> int:
        start, end = _local_day_bounds()
        return int(
            self.repo.db.scalar(
                """SELECT COUNT(DISTINCT word_key) FROM cards
                   WHERE direction='recognition' AND created_at >= ? AND created_at < ?""",
                (start, end),
                0,
            )
        )

    def active_book(self) -> str:
        return self.repo.get_setting("active_book", "cet6") or "cet6"

    def build(
        self,
        kind: str = "study",
        *,
        minutes: int | None = None,
        new_count: int | None = None,
    ) -> SessionPlan:
        self.repo.unsuspend_due_recall_cards(self.settings.learning.recall_delay_days)
        budget_seconds = max(60, (minutes or self.settings.learning.daily_minutes) * 60)
        due = self.repo.due_cards(limit=max(self.settings.learning.max_reviews_per_session, 300))
        due_total = len(due)
        notes: list[str] = []

        review_budget = budget_seconds // max(5, self.settings.learning.review_seconds)
        limit = min(self.settings.learning.max_reviews_per_session, max(0, review_budget))
        selected_due = [] if kind == "learn" else due[:limit]
        if len(selected_due) < len(due):
            notes.append(f"时间预算只覆盖 {len(selected_due)} / {len(due)} 张到期卡")

        verifications: list[dict] = []
        if kind in {"study", "review"}:
            remaining = max(0, limit - len(selected_due))
            verifications = self.repo.due_screenings(limit=min(remaining, 20))

        items: list[PlanItem] = []
        for card in selected_due:
            item_type = (
                ItemType.REVIEW_RECOGNITION
                if card["direction"] == "recognition"
                else ItemType.REVIEW_RECALL
            )
            items.append(
                PlanItem(
                    item_type,
                    card["word_key"],
                    direction=card["direction"],
                    card_row_id=int(card["id"]),
                )
            )
        for row in verifications:
            items.append(PlanItem(ItemType.VERIFY, row["word_key"], payload={"screening_id": row["id"]}))

        # ---------------------------------------------------------------- new
        new_limit = 0
        if kind in {"study", "learn"}:
            if new_count is not None:
                new_limit = max(0, new_count)
            else:
                daily = self.settings.learning.new_words_per_day
                new_limit = max(0, daily - self.today_new_count())
            if kind == "study" and due_total > self.settings.learning.pause_new_when_due_over and new_count is None:
                notes.append(
                    f"到期卡片 {due_total} 张，超过阈值 {self.settings.learning.pause_new_when_due_over}，今日暂停新词"
                )
                new_limit = 0
            spent = len(items) * self.settings.learning.review_seconds
            remaining_seconds = max(0, budget_seconds - spent)
            by_time = remaining_seconds // max(10, self.settings.learning.new_word_seconds)
            new_limit = min(new_limit, int(by_time))
            if new_limit == 0 and new_count is None:
                notes.append("当前时间预算不足以安排新词")

        new_words: list[str] = []
        if new_limit > 0:
            exclude = self.repo.learned_keys() | self.repo.screening_known_keys()
            for personal in self.repo.list_personal():
                key = personal["word_key"]
                if key not in exclude:
                    new_words.append(key)
            for key in self.vocab.new_candidates(self.active_book(), new_limit * 4, exclude):
                if key not in new_words:
                    new_words.append(key)
                if len(new_words) >= new_limit:
                    break
            new_words = new_words[:new_limit]

        if new_words:
            gap = max(0, self.settings.learning.interleave_gap)
            intros = [PlanItem(ItemType.NEW_INTRO, word) for word in new_words]
            recalls = [PlanItem(ItemType.NEW_RECALL, word) for word in new_words]
            sequence: list[PlanItem] = []
            for index, intro in enumerate(intros):
                if index >= gap:
                    sequence.append(recalls[index - gap])
                sequence.append(intro)
            for index in range(max(0, len(intros) - gap), len(recalls)):
                sequence.append(recalls[index])
            items.extend(sequence)

        estimated = 0
        for item in items:
            if item.item_type in {ItemType.NEW_INTRO, ItemType.NEW_RECALL}:
                estimated += self.settings.learning.new_word_seconds
            else:
                estimated += self.settings.learning.review_seconds
        return SessionPlan(
            kind=kind,
            items=items,
            due_count=due_total,
            new_count=len(new_words),
            estimated_seconds=estimated,
            notes=notes,
        )
