from __future__ import annotations

import difflib
import re
import unicodedata

_EDGE = re.compile(r"^[^\w'-]+|[^\w'-]+$", re.UNICODE)
_SPACES = re.compile(r"\s+")
_TOKEN = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_SENTENCE_PUNCT = re.compile(r"[^\w\s'\-.,!?;:()\"]", re.UNICODE)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("\u3000", " ")
    return _SPACES.sub(" ", text).strip()


def normalize_word(text: str) -> str:
    """Stable key used across the two databases (lowercase, NFKC, trimmed)."""
    value = normalize_text(text).lower()
    value = _EDGE.sub("", value)
    return value


def normalize_answer(text: str) -> str:
    value = normalize_text(text).lower()
    value = _SENTENCE_PUNCT.sub("", value)
    value = re.sub(r"\s+([,.!?;:])", r"\1", value)
    return value.strip(" .,!?;:")


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN.finditer(normalize_text(text))]


def _inflections(word: str) -> set[str]:
    forms: set[str] = set()
    w = word.lower()
    if not w:
        return forms
    forms.update({w + "s", w + "es", w + "ed", w + "ing", w + "er", w + "est", w + "ly"})
    if w.endswith("e"):
        forms.update({w + "d", w[:-1] + "ing", w[:-1] + "er", w[:-1] + "est"})
    if w.endswith("y") and len(w) > 2:
        forms.update({w[:-1] + "ies", w[:-1] + "ied", w[:-1] + "ier", w[:-1] + "iest"})
    if w.endswith("ie"):
        forms.add(w[:-2] + "ying")
    if len(w) >= 3 and w[-1] not in "aeiouwxy" and w[-2] in "aeiou" and w[-3] not in "aeiou":
        forms.update({w + w[-1] + "ed", w + w[-1] + "ing", w + w[-1] + "er", w + w[-1] + "est"})
    if w.endswith("s"):
        forms.add(w[:-1])
    forms.discard(w)
    return forms


def word_forms(word: str, known_forms: set[str] | None = None) -> set[str]:
    base = normalize_word(word)
    forms = {base} if base else set()
    forms |= _inflections(base)
    if known_forms:
        forms |= {normalize_word(f) for f in known_forms if f}
    return {f for f in forms if f}


def matches_form(token: str, target: str, known_forms: set[str] | None = None) -> bool:
    token_norm = normalize_word(token)
    if not token_norm:
        return False
    return token_norm in word_forms(target, known_forms)


def cover_targets(body: str, targets: list[str], forms_by_target: dict[str, set[str]] | None = None) -> dict[str, bool]:
    tokens = {normalize_word(t) for t in tokenize(body)}
    result: dict[str, bool] = {}
    for target in targets:
        forms = word_forms(target, (forms_by_target or {}).get(target))
        result[target] = bool(tokens & forms)
    return result


def similarity(expected: str, actual: str) -> float:
    return difflib.SequenceMatcher(None, normalize_answer(expected), normalize_answer(actual)).ratio()


def describe_misspelling(expected: str, actual: str) -> str:
    """Return a short Chinese character-level diagnosis of the first difference."""
    exp = normalize_answer(expected)
    act = normalize_answer(actual)
    matcher = difflib.SequenceMatcher(None, exp, act)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace" and i2 - i1 == 1 and j2 - j1 == 1:
            return f"第 {i1 + 1} 个字母 {exp[i1]} 被误写为 {act[j1]}"
        if tag == "replace":
            return f"第 {i1 + 1} 个字母起，应为 “{exp[i1:i2]}”，写成了 “{act[j1:j2]}”"
        if tag == "delete":
            return f"第 {i1 + 1} 个字母起少了 “{exp[i1:i2]}”"
        if tag == "insert":
            return f"第 {i1 + 1} 个字母前多写了 “{act[j1:j2]}”"
    return "拼写与参考答案不同"


def contains_word(sentence: str, target: str, known_forms: set[str] | None = None) -> bool:
    tokens = tokenize(sentence)
    forms = word_forms(target, known_forms)
    return any(normalize_word(t) in forms for t in tokens)


def blank_out(sentence: str, target: str, blank: str = "______") -> str:
    """Replace the first occurrence of the target or one of its forms with a blank."""
    forms = sorted(word_forms(target), key=len, reverse=True)
    if not forms:
        return ""
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(form) for form in forms) + r")\b",
        re.IGNORECASE,
    )
    result, count = pattern.subn(blank, sentence, count=1)
    return result if count else ""
