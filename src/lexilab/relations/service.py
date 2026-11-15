from __future__ import annotations

from collections import defaultdict

from lexilab.config.settings import Settings
from lexilab.relations.builder import RelationBuilder
from lexilab.relations.model import RELATION_TYPES, RelationView
from lexilab.relations.wordnet import download_wordnet
from lexilab.storage.learning_repo import LearningRepository
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.vocabulary.normalize import normalize_word


class RelationService:
    """Read-side facade for static relations and personal confusion data."""

    def __init__(
        self,
        settings: Settings,
        vocab: VocabularyRepository,
        learning: LearningRepository,
    ) -> None:
        self.settings = settings
        self.vocab = vocab
        self.learning = learning
        self.builder = RelationBuilder(settings, vocab)

    @property
    def enabled(self) -> bool:
        return self.settings.relations.enabled

    def build(self, **kwargs) -> dict:
        return self.builder.build(**kwargs)

    @staticmethod
    def download_wordnet() -> bool:
        return download_wordnet()

    def stats(self) -> dict:
        static = self.vocab.relation_stats()
        return {
            **static,
            "built_at": self.vocab.get_metadata("relations.built_at") or "",
            "wordnet_version": self.vocab.get_metadata("relations.wordnet.version") or "",
            "user_confusions": self.learning.confusion_count(),
            "enabled": self.enabled,
        }

    def groups(self, word: str, limit: int = 30) -> dict[str, list[RelationView]]:
        if not self.enabled:
            return {}
        key = normalize_word(word)
        groups: dict[str, list[RelationView]] = defaultdict(list)
        seen: set[tuple[str, str]] = set()
        for row in self.vocab.relation_views(key, limit=limit):
            dedupe_key = (row["relation_type"], row["target_word"])
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            groups[row["relation_type"]].append(
                RelationView(
                    word_key=row["target_word"],
                    headword=row["headword"],
                    translation=row["translation"],
                    pos=row["display_pos"],
                    relation_type=row["relation_type"],
                    score=row["score"],
                    source_sense=row["source_sense"],
                    target_sense=row["target_sense"],
                    source=row["source"],
                )
            )
        for pair in self.learning.list_confusions(limit=200):
            if key in {pair["source_word"], pair["target_word"]}:
                target = (
                    pair["target_word"] if pair["source_word"] == key else pair["source_word"]
                )
                view = self._view(target, "user_confusion", float(pair["count"]))
                if view:
                    view.reasons.append(f"历史混淆 {pair['count']} 次")
                    groups["user_confusion"].append(view)
        return dict(groups)

    def related(
        self,
        word: str,
        relation_type: str | None = None,
        limit: int = 30,
    ) -> list[RelationView]:
        groups = self.groups(word, limit=limit)
        if relation_type:
            return groups.get(relation_type, [])[:limit]
        result: list[RelationView] = []
        for kind in RELATION_TYPES:
            result.extend(groups.get(kind, []))
        result.extend(groups.get("user_confusion", []))
        return result[:limit]

    def extension_candidates(self, word: str, limit: int = 10) -> list[RelationView]:
        groups = self.groups(word, limit=limit * 2)
        candidates: list[RelationView] = []
        for kind in ("synonym", "derivation", "antonym", "hypernym", "hyponym", "related"):
            candidates.extend(groups.get(kind, []))
        return candidates[:limit]

    def record_confusion_from_answer(self, source: str, answer: str, skill: str = "recall") -> bool:
        if not self.enabled:
            return False
        target = normalize_word(answer)
        if not target or target == normalize_word(source):
            return False
        ec = self.vocab.ecdict_lookup(target)
        if ec and ec.lemma():
            target = normalize_word(ec.lemma())
        if target == normalize_word(source):
            return False
        if not self._target_exists(target):
            return False
        self.learning.record_confusion(source, target, skill=skill)
        return True

    def drill_pairs(self, mode: str, count: int = 10) -> list[tuple[str, str]]:
        """Return (target, contrast) pairs without deciding the UI."""
        if not self.enabled:
            return []
        if mode == "confusion":
            pairs = []
            for row in self.learning.list_confusions(limit=count * 4):
                if self._target_exists(row["source_word"]) and self._target_exists(
                    row["target_word"]
                ):
                    pairs.append((row["source_word"], row["target_word"]))
            return pairs[:count]
        relation_type = "synonym" if mode == "synonym" else "orthographic_similar"
        learned = self.learning.learned_keys()
        rows = self.vocab.relation_pairs(relation_type, limit=max(count * 60, 200))
        pairs: list[tuple[str, str]] = []
        seen: set[str] = set()
        seen_pairs: set[frozenset[str]] = set()
        # Prefer words the learner already has a card for; then fill with any
        # current-book word so the drill is not empty after a fresh install.
        for prefer_learned in (True, False):
            for row in rows:
                source = row["source_word"]
                target = row["target_word"]
                if source in seen:
                    continue
                pair_key = frozenset((source, target))
                if pair_key in seen_pairs:
                    continue
                if prefer_learned and source not in learned:
                    continue
                if not self._target_exists(source) or not self._target_exists(target):
                    continue
                # A derivative such as manufacture/manufacturer is a real
                # morphological relation, not a spelling confusion candidate.
                if relation_type == "orthographic_similar" and self.vocab.has_relation(
                    source, target, ("derivation",)
                ):
                    continue
                seen.add(source)
                seen_pairs.add(pair_key)
                pairs.append((source, target))
                if len(pairs) >= count:
                    return pairs
        return pairs

    def _view(self, word_key: str, relation_type: str, score: float | None) -> RelationView | None:
        meta = self.vocab.word_metadata(word_key)
        if meta:
            return RelationView(
                word_key=word_key,
                headword=meta["headword"] or word_key,
                translation=meta["translation"] or "",
                pos=meta["pos"] or "",
                relation_type=relation_type,
                score=score,
                source="user_history",
            )
        ec = self.vocab.ecdict_lookup(word_key)
        if ec:
            return RelationView(
                word_key=word_key,
                headword=ec.word,
                translation=ec.translation,
                pos=ec.pos,
                relation_type=relation_type,
                score=score,
                source="user_history",
            )
        return None

    def _target_exists(self, word_key: str) -> bool:
        return self.vocab.word_metadata(word_key) is not None or self.vocab.ecdict_lookup(
            word_key
        ) is not None
