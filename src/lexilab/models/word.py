from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Definition:
    pos: str = ""
    meaning_cn: str = ""
    meaning_en: str = ""


@dataclass
class Example:
    sentence_en: str = ""
    sentence_cn: str = ""
    source: str = ""


@dataclass
class Phrase:
    phrase: str = ""
    translation: str = ""


@dataclass
class WordEntry:
    word_key: str
    headword: str
    phonetic_uk: str = ""
    phonetic_us: str = ""
    pos: str = ""
    translation: str = ""
    definition_en: str = ""
    frequency: int | None = None
    source: str = "cet6"
    definitions: list[Definition] = field(default_factory=list)
    examples: list[Example] = field(default_factory=list)
    phrases: list[Phrase] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    derivatives: list[str] = field(default_factory=list)

    @property
    def phonetic(self) -> str:
        return self.phonetic_uk or self.phonetic_us

    @property
    def primary_pos(self) -> str:
        if self.definitions:
            return self.definitions[0].pos or self.pos
        return self.pos or ""

    @property
    def primary_meaning(self) -> str:
        if self.definitions:
            return self.definitions[0].meaning_cn or self.translation
        return self.translation or self.definition_en

    @property
    def short_meaning(self) -> str:
        meaning = self.primary_meaning.replace("\n", "；").strip()
        return meaning[:120]

    def meaning_with_pos(self) -> str:
        pos = self.primary_pos
        meaning = self.short_meaning
        return f"{pos}. {meaning}" if pos else meaning

    def example_for_cloze(self) -> Example | None:
        """Pick a short example containing the headword (or a close form)."""
        head = self.headword.lower()
        candidates = [
            ex for ex in self.examples if head in ex.sentence_en.lower() and 8 <= len(ex.sentence_en) <= 220
        ]
        return candidates[0] if candidates else (self.examples[0] if self.examples else None)

    def cloze_sentence(self) -> str:
        example = self.example_for_cloze()
        if not example:
            return ""
        from lexilab.vocabulary.normalize import blank_out

        return blank_out(example.sentence_en, self.headword)


@dataclass
class ECDICTEntry:
    word: str
    phonetic: str = ""
    definition: str = ""
    translation: str = ""
    pos: str = ""
    collins: int | None = None
    oxford: int | None = None
    tag: str = ""
    bnc: int | None = None
    frq: int | None = None
    exchange: str = ""
    detail: str = ""
    audio: str = ""

    def lemma(self) -> str | None:
        for part in self.exchange.split("/"):
            if part.startswith("0:"):
                return part[2:].strip() or None
        return None

    def forms(self) -> set[str]:
        forms: set[str] = set()
        for part in self.exchange.split("/"):
            if ":" in part:
                value = part.split(":", 1)[1].strip()
                if value:
                    forms.add(value.lower())
        lemma = self.lemma()
        if lemma:
            forms.add(lemma.lower())
        return forms


@dataclass
class LookupResult:
    word_key: str
    entry: WordEntry | None
    ecdict: ECDICTEntry | None
    personal: dict | None = None
    found_in: str = "none"

    @property
    def found(self) -> bool:
        return self.entry is not None or self.ecdict is not None or self.personal is not None
