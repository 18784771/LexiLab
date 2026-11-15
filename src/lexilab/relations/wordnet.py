from __future__ import annotations

import re
from dataclasses import dataclass

from lexilab.relations.model import RelationRecord
from lexilab.vocabulary.normalize import normalize_word

_LEMMA_OK = re.compile(r"^[A-Za-z][A-Za-z'-]*$")


class WordNetUnavailable(RuntimeError):
    """Raised when NLTK WordNet is missing or its corpus is not installed."""


def wordnet_data_available() -> bool:
    try:
        from nltk.corpus import wordnet as wn

        return bool(wn.synsets("word"))
    except Exception:
        return False


def download_wordnet() -> bool:
    """Explicit initialization step; never called on normal startup."""
    try:
        import nltk
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise WordNetUnavailable("未安装 nltk；请执行 pip install -r requirements.txt") from exc
    try:
        return bool(nltk.download("wordnet", quiet=True))
    except Exception as exc:
        raise WordNetUnavailable(
            "WordNet 下载失败。若处于受信代理环境，可显式设置 "
            "NLTK_ALLOW_PROXIED_URLOPEN=1 后重试；或手动准备 ~/nltk_data/corpora/wordnet"
        ) from exc


@dataclass
class WordNetAnalyzer:
    """Small, explicit wrapper around the WordNet relations we actually use."""

    max_synsets: int = 12

    def __post_init__(self) -> None:
        try:
            from nltk.corpus import wordnet as wn
        except ImportError as exc:
            raise WordNetUnavailable("未安装 nltk") from exc
        try:
            wn.synsets("word")
        except LookupError as exc:
            raise WordNetUnavailable("WordNet 数据未初始化；运行 lexi relations download") from exc
        self._wn = wn

    @property
    def version(self) -> str:
        try:
            return str(self._wn.get_version())
        except Exception:
            return "unknown"

    @staticmethod
    def _key(name: str) -> str:
        return normalize_word(name.replace("_", " "))

    @classmethod
    def _valid(cls, name: str) -> bool:
        return bool(_LEMMA_OK.fullmatch(name)) and "_" not in name

    def relations(self, word: str) -> list[RelationRecord]:
        key = normalize_word(word)
        if not key or not _LEMMA_OK.fullmatch(key):
            return []
        records: list[RelationRecord] = []
        for synset in self._wn.synsets(key)[: self.max_synsets]:
            sense = synset.name()
            pos = synset.pos()
            for lemma in synset.lemmas():
                if self._key(lemma.name()) != key:
                    continue
                records.extend(self._synonym_records(key, lemma, synset))
                records.extend(self._antonym_records(key, lemma, sense, pos))
                records.extend(self._derivation_records(key, lemma, sense, pos))
            records.extend(self._hierarchy_records(key, synset, sense, pos))
        return _dedupe(records)

    def _synonym_records(self, key: str, lemma, synset) -> list[RelationRecord]:
        records: list[RelationRecord] = []
        for other in synset.lemmas():
            if not self._valid(other.name()):
                continue
            target = self._key(other.name())
            if target == key:
                continue
            record = RelationRecord(
                key,
                target,
                "synonym",
                synset.name(),
                synset.name(),
                synset.pos(),
                1.0,
                "wordnet",
            )
            records.append(record)
            records.append(
                RelationRecord(
                    target,
                    key,
                    "synonym",
                    synset.name(),
                    synset.name(),
                    synset.pos(),
                    1.0,
                    "wordnet",
                )
            )
        return records

    def _antonym_records(self, key: str, lemma, sense: str, pos: str) -> list[RelationRecord]:
        records: list[RelationRecord] = []
        for other in lemma.antonyms():
            if not self._valid(other.name()):
                continue
            target = self._key(other.name())
            if target == key:
                continue
            target_sense = other.synset().name()
            records.append(
                RelationRecord(key, target, "antonym", sense, target_sense, pos, 0.95, "wordnet")
            )
            records.append(
                RelationRecord(target, key, "antonym", target_sense, sense, pos, 0.95, "wordnet")
            )
        return records

    def _derivation_records(self, key: str, lemma, sense: str, pos: str) -> list[RelationRecord]:
        records: list[RelationRecord] = []
        for other in lemma.derivationally_related_forms():
            if not self._valid(other.name()):
                continue
            target = self._key(other.name())
            if target == key:
                continue
            target_sense = other.synset().name()
            records.append(
                RelationRecord(key, target, "derivation", sense, target_sense, pos, 0.9, "wordnet")
            )
            records.append(
                RelationRecord(target, key, "derivation", target_sense, sense, pos, 0.9, "wordnet")
            )
        return records

    def _hierarchy_records(self, key: str, synset, sense: str, pos: str) -> list[RelationRecord]:
        records: list[RelationRecord] = []
        for relation, inverse in (("hypernym", "hyponym"), ("hyponym", "hypernym")):
            if relation == "hypernym":
                targets = synset.hypernyms()
            else:
                targets = synset.hyponyms()
            for target_synset in targets:
                target = self._key(target_synset.lemmas()[0].name()) if target_synset.lemmas() else ""
                if not target or target == key or not _LEMMA_OK.fullmatch(target):
                    continue
                score = 0.75
                records.append(
                    RelationRecord(
                        key,
                        target,
                        relation,
                        sense,
                        target_synset.name(),
                        pos,
                        score,
                        "wordnet",
                    )
                )
                records.append(
                    RelationRecord(
                        target,
                        key,
                        inverse,
                        target_synset.name(),
                        sense,
                        pos,
                        score,
                        "wordnet",
                    )
                )
        for relation, targets in (
            ("similar", synset.similar_tos()),
            ("related", synset.also_sees()),
        ):
            for target_synset in targets:
                if not target_synset.lemmas():
                    continue
                target = self._key(target_synset.lemmas()[0].name())
                if not target or target == key or not _LEMMA_OK.fullmatch(target):
                    continue
                score = self._semantic_score(synset, target_synset, 0.6 if relation == "similar" else 0.5)
                records.append(
                    RelationRecord(
                        key,
                        target,
                        relation,
                        sense,
                        target_synset.name(),
                        pos,
                        score,
                        "wordnet",
                    )
                )
                records.append(
                    RelationRecord(
                        target,
                        key,
                        relation,
                        target_synset.name(),
                        sense,
                        pos,
                        score,
                        "wordnet",
                    )
                )
        return records

    @staticmethod
    def _semantic_score(source, target, fallback: float) -> float:
        try:
            value = source.wup_similarity(target)
        except Exception:
            value = None
        if value is None:
            return fallback
        return round(max(0.0, min(1.0, float(value))), 4)


def _dedupe(records: list[RelationRecord]) -> list[RelationRecord]:
    seen: set[tuple] = set()
    result: list[RelationRecord] = []
    for record in records:
        key = (
            record.source_word,
            record.target_word,
            record.relation_type,
            record.source_sense,
            record.target_sense,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result
