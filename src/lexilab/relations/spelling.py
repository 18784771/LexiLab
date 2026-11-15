from __future__ import annotations

from dataclasses import dataclass

from lexilab.relations.model import RelationRecord
from lexilab.vocabulary.normalize import normalize_word


class RapidFuzzUnavailable(RuntimeError):
    """Raised when rapidfuzz is not installed."""


@dataclass
class SpellingAnalyzer:
    """Damerau-Levenshtein spelling neighbours with a bounded candidate pool."""

    max_neighbors: int = 10
    similarity_threshold: float = 0.80

    def __post_init__(self) -> None:
        try:
            from rapidfuzz import process  # noqa: F401
            from rapidfuzz.distance import DamerauLevenshtein  # noqa: F401
        except ImportError as exc:
            raise RapidFuzzUnavailable("未安装 rapidfuzz") from exc

    def neighbours(self, words: list[str], forms_by_word: dict[str, set[str]] | None = None) -> list[RelationRecord]:
        from rapidfuzz import process
        from rapidfuzz.distance import DamerauLevenshtein

        keys = sorted({normalize_word(word) for word in words if normalize_word(word)})
        buckets: dict[int, list[str]] = {}
        for key in keys:
            if len(key) < 4:
                continue
            buckets.setdefault(len(key), []).append(key)
        forms = forms_by_word or {}
        pairs: dict[tuple[str, str], float] = {}
        for key in keys:
            if len(key) < 4:
                continue
            pool: list[str] = []
            for length in range(max(4, len(key) - 2), len(key) + 3):
                pool.extend(buckets.get(length, ()))
            if len(pool) <= 1:
                continue
            threshold = max(self.similarity_threshold, 0.86) if len(key) <= 4 else self.similarity_threshold
            matches = process.extract(
                key,
                pool,
                scorer=DamerauLevenshtein.normalized_similarity,
                limit=max(self.max_neighbors * 3 + 1, 1),
                # RapidFuzz may compute 0.8 as 0.7999999999999999; the
                # explicit epsilon makes the documented inclusive threshold
                # behave predictably for words such as adapt/adopt.
                score_cutoff=max(0.0, threshold - 1e-6),
            )
            kept = 0
            for target, score, _ in matches:
                if target == key or score + 1e-9 < threshold:
                    continue
                if _same_paradigm(key, target, forms):
                    continue
                pair = (key, target) if key < target else (target, key)
                old = pairs.get(pair)
                if old is None or score > old:
                    pairs[pair] = float(score)
                kept += 1
                if kept >= self.max_neighbors:
                    break
        records: list[RelationRecord] = []
        for (left, right), score in sorted(pairs.items()):
            # Symmetric relation stored in both directions so the query path is
            # identical for every relation type.
            records.append(
                RelationRecord(left, right, "orthographic_similar", score=score, source="rapidfuzz")
            )
            records.append(
                RelationRecord(right, left, "orthographic_similar", score=score, source="rapidfuzz")
            )
        return records


def _same_paradigm(left: str, right: str, forms: dict[str, set[str]]) -> bool:
    left_forms = forms.get(left, set())
    right_forms = forms.get(right, set())
    return right in left_forms or left in right_forms


def forms_from_exchange(word: str, exchange: str) -> set[str]:
    """Parse ECDICT's exchange field into the word's inflected forms."""
    forms = {normalize_word(word)}
    for segment in (exchange or "").split("/"):
        _, _, value = segment.partition(":")
        for part in value.split(","):
            key = normalize_word(part)
            if key and key != normalize_word(word):
                forms.add(key)
    forms.discard("")
    return forms
