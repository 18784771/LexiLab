from __future__ import annotations

import math
from dataclasses import dataclass, field

from lexilab.config.settings import Settings
from lexilab.relations.model import RELATION_WEIGHTS
from lexilab.relations.service import RelationService
from lexilab.storage.learning_repo import LearningRepository
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.vocabulary.normalize import normalize_word

_TYPE_LABELS = {
    "synonym": "同义",
    "antonym": "反义",
    "hypernym": "上位",
    "hyponym": "下位",
    "derivation": "派生",
    "similar": "语义相似",
    "related": "语义相关",
    "orthographic_similar": "形近",
    "user_confusion": "混淆",
}


@dataclass
class ScoredWord:
    word_key: str
    headword: str
    score: float
    reasons: list[str] = field(default_factory=list)


class SmartNewWordOrderer:
    """Deterministic, explainable ordering for new-word introduction.

    FSRS owns review timing. This class only decides which *unseen* words enter
    the session and in which order, using frequency, learned-word relations,
    interference control and personal confusion history.
    """

    def __init__(
        self,
        settings: Settings,
        vocab: VocabularyRepository,
        repo: LearningRepository,
        relations: RelationService,
    ) -> None:
        self.settings = settings
        self.vocab = vocab
        self.repo = repo
        self.relations = relations

    def choose(
        self,
        book_code: str | None,
        limit: int,
        exclude: set[str],
        *,
        order: str | None = None,
    ) -> list[ScoredWord]:
        if limit <= 0:
            return []
        mode = order or self.settings.learning.new_word_order
        rows = self.vocab.new_word_rows(book_code)
        candidates = [row for row in rows if row["word_key"] not in exclude]
        if not candidates:
            return []
        if mode == "alphabetical":
            candidates.sort(key=lambda row: row["word_key"])
            return [
                ScoredWord(
                    row["word_key"],
                    row.get("headword") or row["word_key"],
                    1.0,
                    ["显式请求字母排序（仅用于浏览/检索）"],
                )
                for row in candidates[:limit]
            ]

        learned = self.repo.learned_keys()
        relation_rows = (
            self.vocab.relations_for_sources(learned)
            if learned and self.settings.relations.enabled
            else []
        )
        related_by_target: dict[str, list[tuple[str, str, float]]] = {}
        for row in relation_rows:
            target = row["target_word"]
            if target in exclude:
                continue
            related_by_target.setdefault(target, []).append(
                (row["source_word"], row["relation_type"], float(row["score"] or 0.0))
            )
        confusion = self._confusion_map() if self.settings.relations.enabled else {}
        selected: list[ScoredWord] = []
        pool_size = max(len(rows), 1)
        for row in candidates:
            row["_base"] = self._base_score(row, pool_size)
            row["_related"] = self._related_score(row["word_key"], related_by_target)
            row["_confusion"] = confusion.get(row["word_key"], 0)
        # Bound the interference search: only the strongest candidates can
        # realistically enter this session, and full 3991 x 10 fuzzy scoring
        # would waste time on words that cannot be selected.
        ranked = sorted(
            candidates,
            key=lambda row: (
                row["_base"]["score"] + row["_related"]["score"] * 0.5,
                -int(row.get("rank") or 0),
            ),
            reverse=True,
        )
        remaining = ranked[: max(limit * 8, 60)]
        semantic_neighbors: dict[str, set[str]] = {}
        if self.settings.relations.enabled and remaining:
            for relation in self.vocab.relations_for_sources(
                {row["word_key"] for row in remaining}
            ):
                if relation["relation_type"] not in {
                    "synonym",
                    "derivation",
                    "hypernym",
                    "hyponym",
                }:
                    continue
                semantic_neighbors.setdefault(relation["source_word"], set()).add(
                    relation["target_word"]
                )
        while remaining and len(selected) < limit:
            best = None
            for row in remaining:
                penalty, interference_reasons = self._interference(
                    row["word_key"], selected, semantic_neighbors
                )
                if mode == "frequency":
                    score = row["_base"]["score"] * 1.0
                elif mode == "related":
                    score = row["_related"]["score"] * 1.4 + row["_base"]["score"] * 0.5
                else:
                    weight = self.settings.relations.learning
                    score = (
                        row["_base"]["score"] * weight.frequency_weight
                        + row["_related"]["score"] * weight.relatedness_weight
                        + min(1.0, row["_confusion"] / 3.0) * 0.15 * weight.confusion_priority
                        - penalty * weight.interference_penalty
                    )
                # Equal scores keep the source ranking (stable), not a new
                # alphabetical re-sort. Alphabetical is only an explicit mode.
                if best is None or score > best[0]:
                    best = (score, row, interference_reasons)
            if best is None:
                break
            score, row, reasons = best
            explanation = list(row["_base"]["reasons"])
            explanation.extend(row["_related"]["reasons"])
            if row["_confusion"]:
                explanation.append(f"个人历史混淆 {row['_confusion']} 次")
            explanation.extend(reasons)
            selected.append(
                ScoredWord(
                    row["word_key"],
                    row.get("headword") or row["word_key"],
                    round(score, 4),
                    explanation,
                )
            )
            remaining = [candidate for candidate in remaining if candidate is not row]
        return self._spread_similar(selected)

    def _spread_similar(self, items: list[ScoredWord]) -> list[ScoredWord]:
        """Insert a non-similar filler between adjacent similar new words.

        The selection loop already lowers the score of similar candidates, but
        when a batch has more similar words than fillers, the final tail can
        still collide. This small scheduling pass uses the same spelling
        relation only for arrangement; it never changes scores or items.
        """
        if len(items) < 3 or not self.settings.relations.enabled:
            return items
        threshold = self.settings.relations.spelling.similarity_threshold
        sequence = list(items)
        for index in range(len(sequence) - 1):
            if _spelling_similarity(sequence[index].word_key, sequence[index + 1].word_key) < threshold:
                continue
            for candidate_index, candidate in enumerate(sequence):
                if candidate_index in {index, index + 1}:
                    continue
                if (
                    _spelling_similarity(candidate.word_key, sequence[index].word_key) < threshold
                    and _spelling_similarity(candidate.word_key, sequence[index + 1].word_key)
                    < threshold
                ):
                    item = sequence.pop(candidate_index)
                    insert_at = index + 1 if candidate_index > index else index
                    sequence.insert(insert_at, item)
                    break
        return sequence


    def _base_score(self, row: dict, pool_size: int) -> dict:
        frq = row.get("frq")
        bnc = row.get("bnc")
        rank = None
        source = ""
        if frq and int(frq) > 0:
            rank = int(frq)
            source = "ECDICT frq"
        elif bnc and int(bnc) > 0:
            rank = int(bnc)
            source = "ECDICT bnc"
        elif row.get("frequency") and int(row["frequency"]) > 0:
            rank = int(row["frequency"])
            source = "词库 frequency"
        if rank is None:
            source_rank = int(row.get("rank") or 0)
            if source_rank > 0:
                score = 0.05 + 0.20 * (1.0 - min(1.0, (source_rank - 1) / max(pool_size, 1)))
                reasons = ["暂无 ECDICT 词频，降级使用词书顺序"]
            else:
                score = 0.20
                reasons = ["暂无可用词频，使用中性排序分"]
        else:
            # Lower rank = more frequent. The log scale keeps a few extremely
            # common words from dominating the whole session.
            score = 1.0 - min(1.0, math.log10(max(1, rank)) / math.log10(50000))
            score = max(0.05, min(1.0, score))
            reasons = [f"{source} 排名 {rank}"]
        collins = int(row.get("collins") or 0)
        oxford = int(row.get("oxford") or 0)
        if collins:
            score += min(collins, 5) * 0.012
            reasons.append(f"Collins {collins} 星")
        if oxford:
            score += 0.03
            reasons.append("Oxford 核心词")
        return {"score": score, "reasons": reasons}

    def _related_score(self, word_key: str, related: dict) -> dict:
        rows = related.get(word_key, [])
        if not rows:
            return {"score": 0.0, "reasons": []}
        total = 0.0
        reasons: list[str] = []
        seen: set[tuple[str, str]] = set()
        for source, relation, _ in rows:
            key = (source, relation)
            if key in seen:
                continue
            seen.add(key)
            total += RELATION_WEIGHTS.get(relation, 0.3)
            label = _TYPE_LABELS.get(relation, relation)
            reasons.append(f"已学习相关词 {source}（{label}）")
        return {"score": min(1.0, total / 3.0), "reasons": reasons[:3]}

    def _confusion_map(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.repo.list_confusions(limit=500):
            for key in (row["source_word"], row["target_word"]):
                counts[key] = counts.get(key, 0) + int(row["count"])
        return counts

    def _interference(
        self,
        word: str,
        selected: list[ScoredWord],
        semantic_neighbors: dict[str, set[str]] | None = None,
    ) -> tuple[float, list[str]]:
        if not selected or not self.settings.relations.enabled:
            return 0.0, []
        threshold = self.settings.relations.spelling.similarity_threshold
        max_similarity = 0.0
        closest = ""
        for other in selected:
            similarity = _spelling_similarity(word, other.word_key)
            if similarity > max_similarity:
                max_similarity = similarity
                closest = other.word_key
        reasons: list[str] = []
        penalty = 0.0
        if max_similarity >= threshold - 1e-9:
            penalty += 0.35 + min(
                0.5, 0.5 * (max_similarity - threshold) / max(0.01, 1.0 - threshold)
            )
            reasons.append(f"与已选词汇 {closest} 形近，本轮降低优先级")
        neighbors = semantic_neighbors or {}
        for other in selected:
            if other.word_key in neighbors.get(word, set()) or word in neighbors.get(
                other.word_key, set()
            ):
                penalty += 0.12
                reasons.append(f"与已选词汇 {other.word_key} 语义关联，避免同批集中")
                break
        # Same POS floods are mildly less diverse; this is deliberately weak.
        return penalty, reasons


def _spelling_similarity(left: str, right: str) -> float:
    try:
        from rapidfuzz.distance import DamerauLevenshtein

        return float(DamerauLevenshtein.normalized_similarity(left, right))
    except ImportError:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, normalize_word(left), normalize_word(right)).ratio()
