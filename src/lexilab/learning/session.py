from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from lexilab.config.settings import Settings
from lexilab.memory.engine import MemoryService
from lexilab.models.session import ItemType, PlanItem
from lexilab.models.word import WordEntry
from lexilab.relations.service import RelationService
from lexilab.storage.learning_repo import LearningRepository
from lexilab.training.judge import judge_word_answer
from lexilab.ui.base import FeedbackView, ProductionPrompt, SessionUI
from lexilab.vocabulary.service import VocabularyService


@dataclass
class RunItem:
    item: PlanItem
    item_id: int | None = None


@dataclass
class SessionResult:
    session_id: str
    reviewed: int = 0
    new_words: int = 0
    skipped: int = 0
    quit: bool = False
    minutes: int = 0
    details: dict = field(default_factory=dict)


class LearningSession:
    def __init__(
        self,
        settings: Settings,
        repo: LearningRepository,
        memory: MemoryService,
        vocab: VocabularyService,
        ui: SessionUI,
        relations: RelationService | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.memory = memory
        self.vocab = vocab
        self.ui = ui
        self.relations = relations
        self._reviewed = 0
        self._new = 0
        self._skipped = 0
        self._completed = 0

    # ------------------------------------------------------------------- run
    def run(self, session_id: str, items: list[RunItem] | None = None) -> SessionResult:
        started = datetime.now(timezone.utc)
        if items is None:
            items = self._load_pending(session_id)
        queue = list(items)
        total = max(1, len(queue))
        quit_requested = False
        while queue:
            run_item = queue.pop(0)
            position = f"{self._completed + 1} / {max(total, self._completed + 1 + len(queue))}"
            try:
                quit_now = self._dispatch(run_item, position, queue)
            except KeyboardInterrupt:
                quit_requested = True
                break
            if quit_now:
                quit_requested = True
                break
            self._completed += 1

        elapsed = max(0, int((datetime.now(timezone.utc) - started).total_seconds() // 60))
        if not quit_requested:
            stats = {
                "reviewed": self._reviewed,
                "new_words": self._new,
                "skipped": self._skipped,
                "minutes": elapsed,
            }
            self.repo.finish_session(session_id, stats)
        result = SessionResult(
            session_id=session_id,
            reviewed=self._reviewed,
            new_words=self._new,
            skipped=self._skipped,
            quit=quit_requested,
            minutes=elapsed,
        )
        if not quit_requested:
            choice = self.ui.show_summary(
                {
                    **result.__dict__,
                    "pending": len(queue),
                    "message": "已保存，下次运行 lexi study 可继续" if quit_requested else "本次学习完成",
                }
            )
            if choice:
                result.details["summary_choice"] = choice
        return result

    def _load_pending(self, session_id: str) -> list[RunItem]:
        result: list[RunItem] = []
        for row in self.repo.pending_items(session_id):
            payload = json.loads(row["payload_json"] or "{}")
            result.append(
                RunItem(
                    PlanItem(
                        item_type=ItemType(row["item_type"]),
                        word_key=row["word_key"],
                        direction=row["direction"],
                        card_row_id=row["card_row_id"],
                        payload=payload,
                    ),
                    item_id=int(row["id"]),
                )
            )
        return result

    def _dispatch(self, run_item: RunItem, position: str, queue: list[RunItem]) -> bool:
        item = run_item.item
        entry = self._entry(item.word_key)
        if item.item_type == ItemType.NEW_INTRO:
            return self._new_intro(run_item, entry, position, queue)
        if item.item_type == ItemType.NEW_RECALL:
            return self._new_recall(run_item, entry, position, queue)
        if item.item_type == ItemType.REVIEW_RECOGNITION:
            return self._review_recognition(run_item, entry, position, queue)
        if item.item_type == ItemType.REVIEW_RECALL:
            return self._review_recall(run_item, entry, position, queue)
        if item.item_type == ItemType.VERIFY:
            return self._verify(run_item, entry, position, queue)
        if item.item_type == ItemType.REINFORCE:
            return self._reinforce(run_item, entry, position)
        self.ui.notify(f"未知学习项: {item.item_type}", "warning")
        self._mark(run_item, "skipped")
        return False

    # --------------------------------------------------------------- handlers
    def _new_intro(
        self, run_item: RunItem, entry: WordEntry, position: str, queue: list[RunItem]
    ) -> bool:
        direction = getattr(self.ui, "ask_new_word_direction", None)
        if callable(direction):
            result = direction(entry, position)
            if result.quit:
                return True
            rating = int(result.rating or 1)
            if result.hinted and rating == 4:
                # Audio/detail disclosure means the answer was not fully
                # independent; Easy is not justified.
                rating = 2
            self.memory.ensure_cards(
                entry.word_key,
                recall_suspended=self.settings.learning.recall_delay_days > 0,
            )
            self.repo.add_training_log(
                entry.word_key,
                "recognition",
                correct=None if rating == 1 else True,
                hinted=result.hinted,
                duration_ms=result.duration_ms,
                detail={
                    "step": "direction_intro",
                    "response": rating,
                    "revealed": result.revealed,
                },
                session_id=run_item.item.payload.get("session_id"),
            )
            if rating in {2, 4}:
                row = self.repo.get_card(entry.word_key, "recognition") or self.memory.ensure_recognition_card(
                    entry.word_key
                )
                outcome = self.memory.review(
                    row, rating, duration_ms=result.duration_ms
                )
                self._reviewed += 1
                self._new += 1
                self._drop_followup_recall(queue, entry.word_key)
                self._mark(run_item, "done", {"rating": outcome.rating, "step": "direction_intro"})
            else:
                # The card is created but no successful FSRS review is recorded.
                # A later NEW_RECALL performs the independent delayed test.
                self._mark(run_item, "done", {"rating": None, "step": "direction_intro"})
            return False

        # Scripted/legacy UI fallback.
        action = self.ui.ask_new_word(entry, position)
        if action == 0:
            return True
        self.memory.ensure_cards(
            entry.word_key,
            recall_suspended=self.settings.learning.recall_delay_days > 0,
        )
        self.repo.add_training_log(
            entry.word_key,
            "recognition",
            correct=None,
            detail={"step": "initial_self_report", "response": action},
            session_id=run_item.item.payload.get("session_id"),
        )
        if not self.ui.show_word_info(entry):
            return True
        self._mark(run_item, "done", {"self_report": action})
        return False

    def _new_recall(
        self, run_item: RunItem, entry: WordEntry, position: str, queue: list[RunItem]
    ) -> bool:
        result = self.ui.ask_recognition(entry, position, mode="new")
        if result.quit:
            return True
        if result.skipped:
            self._skip(run_item, entry, "recognition")
            return False
        row = self.repo.get_card(entry.word_key, "recognition") or self.memory.ensure_recognition_card(
            entry.word_key
        )
        outcome = self.memory.review(row, int(result.rating or 1), duration_ms=result.duration_ms)
        self._reviewed += 1
        self._new += 1
        if outcome.rating == 1:
            self.repo.add_word_error(entry.word_key, "recognition", "forgot_after_intro", "新词主动回忆失败")
            self._requeue(queue, entry.word_key)
        elif outcome.rating >= 3:
            self.repo.resolve_errors(entry.word_key, "recognition")
        self._mark(run_item, "done", {"rating": outcome.rating})
        return False

    def _review_recognition(
        self, run_item: RunItem, entry: WordEntry, position: str, queue: list[RunItem]
    ) -> bool:
        result = self.ui.ask_recognition(entry, position, mode="review")
        if result.quit:
            return True
        if result.skipped:
            self._skip(run_item, entry, "recognition")
            return False
        row = self.repo.get_card_by_id(run_item.item.card_row_id) or self.repo.get_card(
            entry.word_key, "recognition"
        )
        if row is None:
            self.ui.notify("卡片缺失，已跳过", "warning")
            self._mark(run_item, "failed")
            return False
        outcome = self.memory.review(row, int(result.rating or 1), duration_ms=result.duration_ms)
        self._reviewed += 1
        if outcome.rating == 1:
            self.repo.add_word_error(entry.word_key, "recognition", "forgot", "复习时未能回忆")
            self._requeue(queue, entry.word_key)
        elif outcome.rating >= 3:
            self.repo.resolve_errors(entry.word_key, "recognition")
        self._mark(run_item, "done", {"rating": outcome.rating})
        return False

    def _review_recall(
        self, run_item: RunItem, entry: WordEntry, position: str, queue: list[RunItem]
    ) -> bool:
        prompt = ProductionPrompt(
            meaning=entry.primary_meaning,
            pos=entry.primary_pos,
            cloze=entry.cloze_sentence(),
            hint=entry.primary_meaning[:1] + "…" if entry.primary_meaning else "",
        )
        result = self.ui.ask_production(entry, prompt, position)
        if result.quit:
            return True
        if result.skipped:
            self._skip(run_item, entry, "recall")
            return False
        judge = judge_word_answer(
            result.answer,
            entry.headword,
            known_forms=self.vocab.forms_for(entry.word_key),
        )
        if not judge.correct and self.relations is not None:
            self.relations.record_confusion_from_answer(
                entry.word_key, result.answer, skill="recall"
            )
        suggested = 2 if (judge.correct and result.hinted) else (3 if judge.correct else 1)
        feedback = FeedbackView(
            expected=entry.headword,
            given=result.answer,
            correct=judge.correct,
            message=judge.message,
            diagnosis=judge.message if judge.error_type == "spelling" else "",
            reference_sentence=entry.examples[0].sentence_en if entry.examples else "",
            suggested_rating=suggested,
            hinted=result.hinted,
        )
        rating = self.ui.show_feedback(feedback)
        self.repo.add_training_log(
            entry.word_key,
            "recall",
            correct=judge.correct,
            hinted=result.hinted,
            duration_ms=result.duration_ms,
            error_type=judge.error_type,
            detail={"answer": result.answer, "expected": entry.headword},
        )
        if rating is None:
            self._mark(run_item, "done", {"fsrs_skipped": True, "answer": result.answer})
            return True
        row = self.repo.get_card(entry.word_key, "recall")
        if row is None:
            self.memory.ensure_cards(
                entry.word_key,
                recall_suspended=self.settings.learning.recall_delay_days > 0,
            )
            row = self.repo.get_card(entry.word_key, "recall")
        if row is None:
            self._mark(run_item, "failed")
            return False
        outcome = self.memory.review(row, rating, duration_ms=result.duration_ms)
        self._reviewed += 1
        if outcome.rating == 1:
            self.repo.add_word_error(
                entry.word_key, "recall", judge.error_type or "wrong_answer", judge.message
            )
            self._requeue(queue, entry.word_key)
        elif outcome.rating >= 3 and judge.correct:
            self.repo.resolve_errors(entry.word_key, "recall")
        self._mark(run_item, "done", {"rating": outcome.rating, "answer": result.answer})
        return False

    def _verify(
        self, run_item: RunItem, entry: WordEntry, position: str, queue: list[RunItem]
    ) -> bool:
        result = self.ui.ask_recognition(entry, position, mode="verify")
        if result.quit:
            return True
        if result.skipped:
            self._skip(run_item, entry, "recognition")
            return False
        rating = int(result.rating or 1)
        days = self.settings.learning.screen_verify_days
        if rating >= 3:
            self.repo.mark_screening(entry.word_key, passed=True, next_verify_days=days)
            self.repo.add_training_log(
                entry.word_key,
                "recognition",
                correct=True,
                duration_ms=result.duration_ms,
                detail={"step": "screening_verification"},
            )
            self._mark(run_item, "done", {"rating": rating, "verification": "passed"})
        else:
            self.repo.mark_screening(entry.word_key, passed=False, next_verify_days=days)
            self.memory.ensure_cards(entry.word_key, recall_suspended=True)
            row = self.repo.get_card(entry.word_key, "recognition")
            if row is not None:
                self.memory.review(row, rating, duration_ms=result.duration_ms)
                self._reviewed += 1
            self.repo.add_training_log(
                entry.word_key,
                "recognition",
                correct=False,
                duration_ms=result.duration_ms,
                error_type="verification_failed",
                detail={"step": "screening_verification"},
            )
            self.repo.add_word_error(
                entry.word_key, "recognition", "verification_failed", "快速筛选后被抽查失败"
            )
            self._requeue(queue, entry.word_key)
            self._mark(run_item, "done", {"rating": rating, "verification": "failed"})
        return False

    def _reinforce(self, run_item: RunItem, entry: WordEntry, position: str) -> bool:
        ok = self.ui.ask_reinforcement(entry, position)
        if ok is None:
            return True
        self.repo.add_training_log(
            entry.word_key,
            "recognition",
            correct=ok,
            detail={"step": "short_term_reinforcement", "note": "not a new long-term success"},
        )
        self._mark(run_item, "done", {"reinforced": ok})
        return False

    # ---------------------------------------------------------------- helpers
    def _entry(self, word_key: str) -> WordEntry:
        lookup = self.vocab.lookup(word_key)
        entry = self.vocab.display_entry(lookup)
        if entry is None:
            return WordEntry(word_key=word_key, headword=word_key)
        return entry

    def _mark(self, run_item: RunItem, status: str, payload: dict | None = None) -> None:
        if run_item.item_id is not None:
            self.repo.mark_item(run_item.item_id, status, payload=payload)

    def _drop_followup_recall(self, queue: list[RunItem], word_key: str) -> None:
        """Merge a successful intro with its delayed recall item.

        A first exposure that already produced an independent Easy/Hard review
        must not create a second review log for the same learning event.
        """
        for queued in list(queue):
            if queued.item.word_key == word_key and queued.item.item_type == ItemType.NEW_RECALL:
                queue.remove(queued)
                self._mark(queued, "done", {"merged_into_intro": True})

    def _skip(self, run_item: RunItem, entry: WordEntry, skill: str) -> None:
        self._skipped += 1
        self.repo.add_training_log(entry.word_key, skill, correct=None, detail={"skipped": True})
        self._mark(run_item, "skipped")
        self.ui.notify("已跳过（不产生记忆评分）", "muted")

    @staticmethod
    def _requeue(queue: list[RunItem], word_key: str, gap: int = 2) -> None:
        position = min(gap, len(queue))
        queue.insert(position, RunItem(PlanItem(ItemType.REINFORCE, word_key)))
