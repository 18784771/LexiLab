from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lexilab.config.settings import Settings
from lexilab.learning.ordering import ScoredWord, SmartNewWordOrderer
from lexilab.models.session import ItemType, PlanItem, SessionPlan
from lexilab.relations.service import RelationService
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
        relations: RelationService | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.vocab = vocab
        self.memory = memory
        self.relations = relations or RelationService(settings, vocab, repo)
        self.orderer = SmartNewWordOrderer(settings, vocab, repo, self.relations)

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
        order: str | None = None,
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

        review_items: list[PlanItem] = []
        for card in selected_due:
            item_type = (
                ItemType.REVIEW_RECOGNITION
                if card["direction"] == "recognition"
                else ItemType.REVIEW_RECALL
            )
            review_items.append(
                PlanItem(
                    item_type,
                    card["word_key"],
                    direction=card["direction"],
                    card_row_id=int(card["id"]),
                )
            )

        # ---------------------------------------------------------------- new
        new_limit = 0
        if kind in {"study", "learn"}:
            if new_count is not None:
                new_limit = max(0, new_count)
            else:
                daily = self.settings.learning.new_words_per_day
                new_limit = max(0, daily - self.today_new_count())
            if (
                kind == "study"
                and self.settings.learning.adaptive_new_words
                and due_total > self.settings.learning.pause_new_when_due_over
                and new_count is None
            ):
                notes.append(
                    f"到期卡片 {due_total} 张，超过阈值 {self.settings.learning.pause_new_when_due_over}，今日暂停新词"
                )
                new_limit = 0
            spent = len(review_items) * self.settings.learning.review_seconds
            remaining_seconds = max(0, budget_seconds - spent)
            by_time = remaining_seconds // max(10, self.settings.learning.new_word_seconds)
            new_limit = min(new_limit, int(by_time))
            if new_limit == 0 and new_count is None:
                notes.append("当前时间预算不足以安排新词")

        new_words: list[ScoredWord] = []
        if new_limit > 0:
            exclude = self.repo.learned_keys() | self.repo.screening_known_keys()
            personal = []
            for row in self.repo.list_personal():
                key = row["word_key"]
                if key not in exclude:
                    personal.append(
                        ScoredWord(
                            key,
                            row.get("headword") or key,
                            1.0,
                            ["个人生词（优先加入）"],
                        )
                    )
            new_words.extend(personal[:new_limit])
            remaining_limit = max(0, new_limit - len(new_words))
            if remaining_limit:
                new_words.extend(
                    self.orderer.choose(
                        self.active_book(),
                        remaining_limit,
                        exclude | {item.word_key for item in new_words},
                        order=order,
                    )
                )
            if new_words and (order or self.settings.learning.new_word_order) != "alphabetical":
                first = new_words[0]
                if first.reasons:
                    notes.append(
                        f"排序示例 {first.word_key}: " + "；".join(first.reasons[:2])
                    )

        intros: list[PlanItem] = []
        recalls: list[PlanItem] = []
        if new_words:
            intros = [
                PlanItem(
                    ItemType.NEW_INTRO,
                    item.word_key,
                    payload={"recommendation": item.reasons},
                )
                for item in new_words
            ]
            recalls = [
                PlanItem(
                    ItemType.NEW_RECALL,
                    item.word_key,
                    payload={"recommendation": item.reasons},
                )
                for item in new_words
            ]

        items = self._compose_items(kind, intros, recalls, review_items)
        if kind in {"study", "learn"} and self.settings.learning.mistake_drill:
            reinforce = self._mistake_items({item.word_key for item in items})
            if reinforce:
                items.extend(reinforce)
                notes.append(f"错词强化 {len(reinforce)} 个")

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

    def _compose_items(
        self,
        kind: str,
        intros: list[PlanItem],
        recalls: list[PlanItem],
        reviews: list[PlanItem],
    ) -> list[PlanItem]:
        """Build the automatic daily flow without stage re-confirmation."""
        if kind == "review":
            return list(reviews)
        if kind == "learn":
            if self.settings.learning.delayed_recall:
                gap = max(0, self.settings.learning.interleave_gap)
                sequence = list(intros)
                for index, recall in enumerate(recalls):
                    insert_at = min(len(sequence), gap + index)
                    sequence.insert(insert_at, recall)
                return sequence
            return list(intros) + list(recalls)

        order = self.settings.learning.plan_order
        if not self.settings.learning.delayed_recall:
            new_block = list(intros) + list(recalls)
            return new_block + list(reviews) if order == "new_first" else list(reviews) + new_block
        if order == "old_first":
            return list(reviews) + list(intros) + list(recalls)
        if order == "interleaved":
            sequence: list[PlanItem] = []
            max_len = max(len(intros), len(reviews))
            for index in range(max_len):
                if index < len(intros):
                    sequence.append(intros[index])
                if index < len(reviews):
                    sequence.append(reviews[index])
            sequence.extend(recalls)
            return sequence
        # Default: new intro -> due review -> delayed new recall.
        return list(intros) + list(reviews) + list(recalls)

    def _mistake_items(self, excluded: set[str]) -> list[PlanItem]:
        items: list[PlanItem] = []
        for word in self.repo.weak_words(limit=5):
            if word in excluded:
                continue
            items.append(PlanItem(ItemType.REINFORCE, word, payload={"reason": "错词强化"}))
            if len(items) >= 3:
                break
        return items
