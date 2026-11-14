from __future__ import annotations

import re

from lexilab.models.word import Definition, ECDICTEntry, LookupResult, WordEntry
from lexilab.storage.learning_repo import LearningRepository
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.vocabulary.normalize import normalize_word, word_forms

_POS_LINE = re.compile(r"^([a-z]{1,6})\.\s*(.+)$", re.IGNORECASE)


class VocabularyService:
    def __init__(self, vocab: VocabularyRepository, learning: LearningRepository | None = None) -> None:
        self.vocab = vocab
        self.learning = learning

    # ---------------------------------------------------------------- lookup
    def lookup(self, word: str, *, follow_lemma: bool = True) -> LookupResult:
        key = normalize_word(word)
        entry = self.vocab.get_entry(key)
        ec = self.vocab.ecdict_lookup(key)
        personal = self.learning.get_personal(key) if self.learning else None
        if entry or ec or personal:
            found = "cet6" if entry else ("ecdict" if ec else "personal")
            return LookupResult(word_key=key, entry=entry, ecdict=ec, personal=dict(personal) if personal else None, found_in=found)

        if follow_lemma:
            for candidate in self._lemma_candidates(key):
                if candidate == key:
                    continue
                entry = self.vocab.get_entry(candidate)
                ec = self.vocab.ecdict_lookup(candidate)
                personal = self.learning.get_personal(candidate) if self.learning else None
                if entry or ec or personal:
                    found = "cet6-lemma" if entry else ("ecdict-lemma" if ec else "personal-lemma")
                    return LookupResult(
                        word_key=candidate,
                        entry=entry,
                        ecdict=ec,
                        personal=dict(personal) if personal else None,
                        found_in=found,
                    )
        return LookupResult(word_key=key, entry=None, ecdict=None, personal=None, found_in="none")

    def _lemma_candidates(self, key: str) -> list[str]:
        candidates: list[str] = []
        ec = self.vocab.ecdict_lookup(key)
        if ec:
            lemma = ec.lemma()
            if lemma:
                candidates.append(normalize_word(lemma))
        rules: list[str] = []
        if key.endswith("ies") and len(key) > 4:
            rules.append(key[:-3] + "y")
        if key.endswith("ied") and len(key) > 4:
            rules.append(key[:-3] + "y")
        if key.endswith("ing") and len(key) > 4:
            rules.extend([key[:-3], key[:-3] + "e"])
            if len(key) > 5 and key[-4] == key[-5]:
                rules.append(key[:-4])
        if key.endswith("ed") and len(key) > 3:
            rules.extend([key[:-2], key[:-1]])
            if len(key) > 4 and key[-3] == key[-4]:
                rules.append(key[:-3])
        if key.endswith("es") and len(key) > 3:
            rules.extend([key[:-2], key[:-1]])
        if key.endswith("s") and len(key) > 3:
            rules.append(key[:-1])
        if key.endswith("er") and len(key) > 4:
            rules.extend([key[:-2], key[:-1]])
        if key.endswith("est") and len(key) > 5:
            rules.extend([key[:-3], key[:-2]])
        for rule in rules:
            if rule and rule not in candidates:
                candidates.append(rule)
        return candidates

    def display_entry(self, result: LookupResult) -> WordEntry | None:
        if result.entry:
            return result.entry
        if result.ecdict:
            return entry_from_ecdict(result.ecdict)
        if result.personal:
            p = result.personal
            return WordEntry(
                word_key=p["word_key"],
                headword=p["headword"],
                translation=p.get("translation") or "",
                phonetic_uk=p.get("phonetic") or "",
                source="personal",
                definitions=[Definition(meaning_cn=p.get("translation") or "")],
            )
        return None

    def forms_for(self, word: str) -> set[str]:
        key = normalize_word(word)
        known: set[str] = set()
        ec = self.vocab.ecdict_lookup(key)
        if ec:
            known |= ec.forms()
        return word_forms(key, known)

    # ------------------------------------------------------------- personal
    def add_personal(
        self,
        word: str,
        *,
        translation: str = "",
        phonetic: str = "",
        note: str = "",
        source: str = "manual",
    ) -> LookupResult:
        if self.learning is None:
            raise RuntimeError("personal words require a learning repository")
        result = self.lookup(word)
        entry = self.display_entry(result)
        if not translation and entry:
            translation = entry.translation
        if not phonetic and entry:
            phonetic = entry.phonetic
        headword = entry.headword if entry else word.strip()
        key = entry.word_key if entry else normalize_word(word)
        self.learning.add_personal(
            key,
            headword,
            translation=translation,
            phonetic=phonetic,
            note=note,
            source=source,
        )
        return self.lookup(key)

    def remove_personal(self, word: str) -> int:
        if self.learning is None:
            return 0
        return self.learning.remove_personal(normalize_word(word))

    def personal_entries(self) -> list[dict]:
        if self.learning is None:
            return []
        return self.learning.list_personal()

    # ---------------------------------------------------------------- search
    def search(self, term: str, limit: int = 10) -> list[tuple[str, str, str]]:
        results: list[tuple[str, str, str]] = []
        for row in self.vocab.search(term, limit=limit):
            results.append((row["word_key"], row["headword"], row["translation"].split("\n")[0]))
        seen = {r[0] for r in results}
        for row in self.vocab.ecdict_search(term, limit=limit):
            key = normalize_word(row["word"])
            if key in seen:
                continue
            meaning = (row["translation"] or "").replace("\\n", "\n").split("\n")[0]
            results.append((key, row["word"], meaning))
        return results

    def total_words(self, book_code: str | None = None) -> int:
        return self.vocab.count_words(book_code)


def entry_from_ecdict(ec: ECDICTEntry) -> WordEntry:
    definitions: list[Definition] = []
    for line in (ec.translation or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        match = _POS_LINE.match(line)
        if match:
            definitions.append(Definition(pos=match.group(1), meaning_cn=match.group(2).strip()))
        else:
            definitions.append(Definition(pos=ec.pos, meaning_cn=line))
    return WordEntry(
        word_key=normalize_word(ec.word),
        headword=ec.word,
        phonetic_uk=ec.phonetic,
        pos=ec.pos,
        translation=ec.translation,
        definition_en=ec.definition,
        frequency=ec.frq,
        source="ecdict",
        definitions=definitions,
    )
