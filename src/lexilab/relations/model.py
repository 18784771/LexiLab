from __future__ import annotations

from dataclasses import dataclass, field


RELATION_TYPES = (
    "synonym",
    "antonym",
    "hypernym",
    "hyponym",
    "derivation",
    "similar",
    "related",
    "orthographic_similar",
)

RELATION_LABELS = {
    "synonym": "同义词",
    "antonym": "反义词",
    "hypernym": "上位词",
    "hyponym": "下位词",
    "derivation": "派生词",
    "similar": "语义相似",
    "related": "语义相关",
    "orthographic_similar": "形近词",
    "user_confusion": "个人易混淆",
}

# Higher means a stronger/cleaner signal for related-word extension.
RELATION_WEIGHTS = {
    "synonym": 1.0,
    "derivation": 0.9,
    "antonym": 0.7,
    "hypernym": 0.6,
    "hyponym": 0.6,
    "similar": 0.5,
    "related": 0.4,
    "orthographic_similar": 0.45,
    "user_confusion": 1.0,
}


@dataclass(frozen=True)
class RelationRecord:
    source_word: str
    target_word: str
    relation_type: str
    source_sense: str = ""
    target_sense: str = ""
    part_of_speech: str = ""
    score: float | None = None
    source: str = "wordnet"


@dataclass
class RelationView:
    word_key: str
    headword: str
    translation: str
    pos: str
    relation_type: str
    score: float | None = None
    source_sense: str = ""
    target_sense: str = ""
    source: str = ""
    reasons: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return RELATION_LABELS.get(self.relation_type, self.relation_type)

    @property
    def meaning(self) -> str:
        text = (self.translation or "").replace("\n", "；").strip()
        if self.pos and text and not text.startswith(self.pos):
            return f"{self.pos}. {text}"
        return text
