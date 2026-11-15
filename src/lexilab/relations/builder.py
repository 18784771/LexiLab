from __future__ import annotations

import time
from collections.abc import Callable

from lexilab.config.settings import Settings
from lexilab.relations.spelling import RapidFuzzUnavailable, SpellingAnalyzer, forms_from_exchange
from lexilab.relations.wordnet import WordNetAnalyzer, WordNetUnavailable
from lexilab.storage.schema import utcnow_iso
from lexilab.storage.vocab_repo import VocabularyRepository


class RelationBuilder:
    def __init__(self, settings: Settings, vocab: VocabularyRepository) -> None:
        self.settings = settings
        self.vocab = vocab

    def build(
        self,
        *,
        force: bool = False,
        book_code: str | None = None,
        wordnet: bool = True,
        spelling: bool = True,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> dict:
        started = time.perf_counter()
        cfg = self.settings.relations
        if not cfg.enabled:
            return {"skipped": True, "reason": "relations.enabled=false", "elapsed": 0.0}
        if force:
            self.vocab.clear_relations()
        words = self.vocab.book_word_keys(book_code)
        result: dict = {
            "words": len(words),
            "wordnet": {"built": 0, "relations": 0, "error": ""},
            "spelling": {"built": 0, "relations": 0, "error": ""},
            "elapsed": 0.0,
        }
        if wordnet and cfg.wordnet_enabled:
            result["wordnet"] = self._build_wordnet(words, progress)
        if spelling and cfg.rapidfuzz_enabled:
            result["spelling"] = self._build_spelling(words, progress)
        self.vocab.set_metadata("relations.built_at", utcnow_iso())
        self.vocab.set_metadata(
            "relations.spelling.config",
            f"{cfg.spelling.similarity_threshold}:{cfg.spelling.max_neighbors}",
        )
        # Compact metrics cache keeps future smart-order planning fast even
        # when the full ECDICT has 770k rows.
        self.vocab.refresh_word_metrics()
        result["elapsed"] = round(time.perf_counter() - started, 3)
        result["stats"] = self.vocab.relation_stats()
        return result

    def _build_wordnet(
        self,
        words: list[str],
        progress: Callable[[str, int, int], None] | None,
    ) -> dict:
        built = self.vocab.relation_built_words("wordnet")
        pending = [word for word in words if word not in built]
        info = {"built": 0, "relations": 0, "error": ""}
        if not pending:
            return info
        try:
            analyzer = WordNetAnalyzer()
        except WordNetUnavailable as exc:
            info["error"] = str(exc)
            return info
        batch_records: list = []
        batch_words: list[str] = []
        for index, word in enumerate(pending, 1):
            batch_records.extend(analyzer.relations(word))
            batch_words.append(word)
            if len(batch_words) >= 80:
                info["relations"] += self.vocab.insert_relations(batch_records)
                self.vocab.mark_relation_built(batch_words, "wordnet")
                info["built"] += len(batch_words)
                batch_records.clear()
                batch_words.clear()
            if progress and index % 50 == 0:
                progress("wordnet", index, len(pending))
        if batch_words:
            info["relations"] += self.vocab.insert_relations(batch_records)
            self.vocab.mark_relation_built(batch_words, "wordnet")
            info["built"] += len(batch_words)
        self.vocab.set_metadata("relations.wordnet.version", analyzer.version)
        return info

    def _build_spelling(
        self,
        words: list[str],
        progress: Callable[[str, int, int], None] | None,
    ) -> dict:
        built = self.vocab.relation_built_words("spelling")
        config_key = (
            f"{self.settings.relations.spelling.similarity_threshold}:"
            f"{self.settings.relations.spelling.max_neighbors}"
        )
        if built and self.vocab.get_metadata("relations.spelling.config") != config_key:
            self.vocab.clear_relations_by_source("rapidfuzz")
            built = set()
        pending_words = [word for word in words if word not in built]
        if not pending_words:
            return {"built": 0, "relations": 0, "error": ""}
        info = {"built": 0, "relations": 0, "error": ""}
        try:
            analyzer = SpellingAnalyzer(
                max_neighbors=self.settings.relations.spelling.max_neighbors,
                similarity_threshold=self.settings.relations.spelling.similarity_threshold,
            )
        except RapidFuzzUnavailable as exc:
            info["error"] = str(exc)
            return info
        exchanges = self.vocab.ecdict_exchanges(pending_words)
        forms = {
            word: forms_from_exchange(word, exchanges.get(word, ""))
            for word in pending_words
        }
        if progress:
            progress("spelling", 1, 3)
        records = analyzer.neighbours(pending_words, forms)
        if progress:
            progress("spelling", 2, 3)
        info["relations"] = self.vocab.insert_relations(records)
        self.vocab.mark_relation_built(pending_words, "spelling")
        info["built"] = len(pending_words)
        if progress:
            progress("spelling", 3, 3)
        return info
