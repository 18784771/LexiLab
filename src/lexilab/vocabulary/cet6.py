from __future__ import annotations

import hashlib
import json
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from lexilab.models.word import Definition, Example, Phrase, WordEntry
from lexilab.storage.schema import utcnow_iso
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.vocabulary.normalize import normalize_word

CET6_URL = (
    "https://raw.githubusercontent.com/KyleBing/english-vocabulary/master/"
    "full_line_jsonl/full/%E6%AD%A3%E5%BA%8F/%E5%85%AD%E7%BA%A7.jsonl"
)
CET6_BOOK_CODE = "cet6"
CET6_BOOK_NAME = "大学英语六级词汇（第三方整理，非官方大纲）"
CET6_LICENSE = "BSD-3-Clause (KyleBing/english-vocabulary)"
CET6_SOURCE_URL = "https://github.com/KyleBing/english-vocabulary"


@dataclass
class ImportReport:
    total_lines: int = 0
    unique_words: int = 0
    definitions: int = 0
    examples: int = 0
    phrases: int = 0
    duplicate_senses: int = 0
    skipped: int = 0
    problems: list[str] = field(default_factory=list)
    sha256: str = ""
    path: str = ""

    def as_text(self) -> str:
        lines = [
            f"文件: {self.path}",
            f"SHA-256: {self.sha256}",
            f"原始行数: {self.total_lines}",
            f"唯一词条: {self.unique_words}",
            f"释义: {self.definitions}",
            f"例句: {self.examples}",
            f"短语: {self.phrases}",
            f"合并的同词多义行: {self.duplicate_senses}",
            f"跳过异常行: {self.skipped}",
        ]
        if self.problems:
            lines.append("异常摘要:")
            lines.extend(f"  - {item}" for item in self.problems[:10])
        return "\n".join(lines)


def download_cet6(target: Path, *, progress: Callable[[int, int], None] | None = None) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(CET6_URL, headers={"User-Agent": "LexiLab/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response, tmp.open("wb") as fh:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    tmp.replace(target)
    return target


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique(items: list[str]) -> list[str]:
    return list(OrderedDict((item, None) for item in items if item))


def parse_entry(obj: dict, source: str = "cet6") -> WordEntry | None:
    if not isinstance(obj, dict):
        return None
    word_obj = (obj.get("content") or {}).get("word") or {}
    headword = (word_obj.get("wordHead") or obj.get("headWord") or "").strip()
    if not headword:
        return None
    word_key = normalize_word(headword)
    if not word_key:
        return None
    content = word_obj.get("content") or {}

    definitions: list[Definition] = []
    translation_parts: list[str] = []
    english_parts: list[str] = []
    for trans in content.get("trans") or []:
        pos = (trans.get("pos") or "").strip()
        cn = (trans.get("tranCn") or "").strip()
        en = (trans.get("tranOther") or "").strip()
        if cn or en:
            definitions.append(Definition(pos=pos, meaning_cn=cn, meaning_en=en))
        if cn:
            translation_parts.append(f"{pos}. {cn}" if pos else cn)
        if en:
            english_parts.append(f"{pos}. {en}" if pos else en)

    examples: list[Example] = []
    for sentence in (content.get("sentence") or {}).get("sentences") or []:
        text = (sentence.get("sContent") or "").strip()
        if text:
            examples.append(Example(sentence_en=text, sentence_cn=(sentence.get("sCn") or "").strip(), source="cet6"))

    phrases: list[Phrase] = []
    for phrase in (content.get("phrase") or {}).get("phrases") or []:
        value = (phrase.get("pContent") or "").strip()
        if value:
            phrases.append(Phrase(phrase=value, translation=(phrase.get("pCn") or "").strip()))

    synonyms: list[str] = []
    for syno in (content.get("syno") or {}).get("synos") or []:
        for item in syno.get("hwds") or []:
            value = (item.get("w") or "").strip()
            if value:
                synonyms.append(value)

    derivatives: list[str] = []
    for rel in (content.get("relWord") or {}).get("rels") or []:
        for item in rel.get("words") or []:
            value = (item.get("hwd") or "").strip()
            if value:
                suffix = (item.get("tran") or "").strip()
                derivatives.append(f"{value} {suffix}".strip())

    pos_list = _unique([d.pos for d in definitions if d.pos])
    return WordEntry(
        word_key=word_key,
        headword=headword,
        phonetic_uk=(content.get("ukphone") or content.get("phone") or "").strip(),
        phonetic_us=(content.get("usphone") or "").strip(),
        pos="/".join(pos_list),
        translation="\n".join(_unique(translation_parts)),
        definition_en="\n".join(_unique(english_parts)),
        source=source,
        definitions=definitions,
        examples=examples,
        phrases=phrases,
        synonyms=_unique(synonyms),
        derivatives=_unique(derivatives),
    )


def _merge_into(target: WordEntry, incoming: WordEntry) -> None:
    target.definitions.extend(incoming.definitions)
    target.examples.extend(incoming.examples)
    target.phrases.extend(incoming.phrases)
    target.synonyms = _unique(target.synonyms + incoming.synonyms)
    target.derivatives = _unique(target.derivatives + incoming.derivatives)
    target.translation = "\n".join(_unique(target.translation.split("\n") + incoming.translation.split("\n")))
    target.definition_en = "\n".join(
        _unique(target.definition_en.split("\n") + incoming.definition_en.split("\n"))
    )
    target.pos = "/".join(_unique(target.pos.split("/") + incoming.pos.split("/")))
    if not target.phonetic_uk:
        target.phonetic_uk = incoming.phonetic_uk
    if not target.phonetic_us:
        target.phonetic_us = incoming.phonetic_us


def import_cet6(
    path: str | Path,
    repo: VocabularyRepository,
    *,
    book_code: str = CET6_BOOK_CODE,
    book_name: str = CET6_BOOK_NAME,
    source_url: str = CET6_SOURCE_URL,
) -> ImportReport:
    source_path = Path(path)
    report = ImportReport(path=str(source_path))
    report.sha256 = sha256_file(source_path)
    merged: dict[str, WordEntry] = OrderedDict()
    raws: dict[str, list[str]] = OrderedDict()

    with source_path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            report.total_lines += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                report.skipped += 1
                report.problems.append(f"第 {lineno} 行 JSON 错误: {exc.msg}")
                continue
            entry = parse_entry(obj)
            if entry is None:
                report.skipped += 1
                report.problems.append(f"第 {lineno} 行缺少 headWord")
                continue
            entry.source = book_code
            if not entry.definitions:
                report.skipped += 1
                report.problems.append(f"第 {lineno} 行 {entry.headword} 缺少释义")
                continue
            if entry.word_key in merged:
                _merge_into(merged[entry.word_key], entry)
                report.duplicate_senses += 1
            else:
                merged[entry.word_key] = entry
            raws.setdefault(entry.word_key, []).append(line.strip())

    report.unique_words = len(merged)
    book_id = repo.upsert_book(
        book_code,
        book_name,
        description="KyleBing/english-vocabulary 完整版六级词库，按词条合并多义项。",
        source_url=source_url,
        license_text=CET6_LICENSE,
        source_version=f"sha256:{report.sha256}",
    )
    with repo.db.transaction() as conn:
        for rank, (key, entry) in enumerate(merged.items(), 1):
            raw_lines = raws.get(key, [])
            repo.upsert_word(
                entry,
                book_id=book_id,
                rank=rank,
                source_id=f"{book_code}:{key}",
                raw_payload="\n".join(raw_lines),
                store_raw=False,
                conn=conn,
            )
            conn.execute(
                "UPDATE words SET raw_json=? WHERE word_key=?",
                ("\n".join(raw_lines), key),
            )
            for line_index, raw_line in enumerate(raw_lines, 1):
                conn.execute(
                    """INSERT INTO raw_entries(source, source_id, word_key, payload_json, imported_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(source, source_id) DO UPDATE SET
                         payload_json=excluded.payload_json, imported_at=excluded.imported_at""",
                    (
                        book_code,
                        f"{book_code}:{key}:{line_index}",
                        key,
                        raw_line,
                        utcnow_iso(),
                    ),
                )
            report.definitions += len(entry.definitions)
            report.examples += len(entry.examples)
            report.phrases += len(entry.phrases)
        repo.set_metadata("cet6.source_url", source_url, conn)
        repo.set_metadata("cet6.sha256", report.sha256, conn)
        repo.set_metadata("cet6.license", CET6_LICENSE, conn)
        repo.set_metadata("cet6.imported_at", utcnow_iso(), conn)
        repo.set_metadata("cet6.note", "第三方整理词库，不是官方考试大纲。", conn)
    return report
