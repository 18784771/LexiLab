from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fsrs import Card

from lexilab.models.session import ItemType, PlanItem
from lexilab.models.word import Definition, Example, Phrase, WordEntry
from lexilab.storage.learning_repo import LearningRepository
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.ui.base import FeedbackView, RatingResult

MINI_WORDS = [
    ("abandon", "v.", "放弃；抛弃", "They had to abandon the experiment."),
    ("abandonment", "n.", "放弃；抛弃", "The abandonment of the plan surprised us."),
    ("ability", "n.", "能力", "She has the ability to solve it."),
    ("abstract", "adj.", "抽象的", "The idea is too abstract for a child."),
    ("accelerate", "v.", "加速", "The new method can accelerate training."),
    ("accurate", "adj.", "准确的", "We need accurate measurements."),
    ("achieve", "v.", "达到；实现", "They achieved a good result."),
    ("acquire", "v.", "获得；习得", "Children acquire language quickly."),
    ("adapt", "v.", "适应；改编", "The system can adapt to change."),
    ("adequate", "adj.", "足够的", "The evidence is adequate."),
    ("mitigate", "v.", "减轻；缓解", "We need to mitigate the risk."),
    ("constraint", "n.", "限制；约束", "Time is a serious constraint."),
    ("subtle", "adj.", "微妙的", "There is a subtle difference."),
    ("robust", "adj.", "稳健的；健壮的", "The design is robust."),
    ("perturbation", "n.", "扰动", "Sensor noise is a perturbation."),
]


def seed_vocab(repo: VocabularyRepository) -> None:
    book_id = repo.upsert_book("cet6", "测试六级词库", source_url="local://test")
    for rank, (word, pos, meaning, sentence) in enumerate(MINI_WORDS, 1):
        entry = WordEntry(
            word_key=word,
            headword=word,
            phonetic_uk="ˈtest",
            pos=pos,
            translation=f"{pos} {meaning}",
            source="cet6",
            definitions=[Definition(pos=pos, meaning_cn=meaning, meaning_en=f"test meaning of {word}")],
            examples=[Example(sentence_en=sentence, sentence_cn="测试例句", source="cet6")],
            phrases=[Phrase(phrase=f"{word} test", translation="测试短语")],
            synonyms=[f"{word}-syn"],
            derivatives=[f"{word}-derived"],
        )
        repo.upsert_word(
            entry,
            book_id=book_id,
            rank=rank,
            source_id=f"cet6:{word}",
            raw_payload='{"headWord":"%s"}' % word,
        )


def make_due_card(
    repo: LearningRepository,
    word_key: str,
    direction: str = "recognition",
    *,
    days: float = -1,
) -> dict:
    card = Card().to_dict()
    card["due"] = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    return repo.create_card(word_key, direction, card)


def new_recall_plan(word: str = "mitigate") -> list[PlanItem]:
    return [
        PlanItem(ItemType.NEW_INTRO, word),
        PlanItem(ItemType.NEW_RECALL, word),
    ]


class ScriptedUI:
    def __init__(
        self,
        *,
        new_actions: list[int] | None = None,
        recognition: list[RatingResult] | None = None,
        production: list[RatingResult] | None = None,
        feedback: list[int | None] | None = None,
        reinforcement: list[bool | None] | None = None,
        info_continue: bool = True,
    ) -> None:
        self.new_actions = list(new_actions or [])
        self.recognition = list(recognition or [])
        self.production = list(production or [])
        self.feedback = list(feedback or [])
        self.reinforcement = list(reinforcement or [])
        self.info_continue = info_continue
        self.messages: list[str] = []
        self.summary: dict | None = None
        self.seen_details = 0

    def notify(self, message: str, style: str = "info") -> None:
        self.messages.append(message)

    def ask_new_word(self, entry, position: str) -> int:
        return self.new_actions.pop(0) if self.new_actions else 0

    def show_word_info(self, entry) -> bool:
        return self.info_continue

    def ask_recognition(self, entry, position: str, *, mode: str = "review") -> RatingResult:
        return self.recognition.pop(0) if self.recognition else RatingResult(quit=True)

    def ask_production(self, entry, prompt, position: str) -> RatingResult:
        return self.production.pop(0) if self.production else RatingResult(quit=True)

    def show_feedback(self, feedback: FeedbackView) -> int | None:
        return self.feedback.pop(0) if self.feedback else 3

    def ask_reinforcement(self, entry, position: str) -> bool | None:
        return self.reinforcement.pop(0) if self.reinforcement else True

    def show_summary(self, summary: dict) -> None:
        self.summary = summary
