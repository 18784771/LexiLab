from __future__ import annotations

from dataclasses import dataclass, field

from lexilab.vocabulary.normalize import (
    describe_misspelling,
    matches_form,
    normalize_answer,
    similarity,
    word_forms,
)


@dataclass
class JudgeResult:
    correct: bool | None
    expected: str
    normalized_answer: str = ""
    error_type: str | None = None
    message: str = ""
    near_miss: bool = False
    needs_user_judgement: bool = False
    accepted_variants: list[str] = field(default_factory=list)

    @property
    def suggested_rating(self) -> int | None:
        if self.correct is None:
            return None
        return 3 if self.correct else 1


def judge_word_answer(
    answer: str,
    expected: str,
    *,
    accepted: list[str] | None = None,
    known_forms: set[str] | None = None,
    allow_inflections: bool = True,
) -> JudgeResult:
    expected_norm = normalize_answer(expected)
    answer_norm = normalize_answer(answer)
    variants = [normalize_answer(v) for v in (accepted or []) if v]
    if not answer_norm:
        return JudgeResult(False, expected, "", "empty", "未作答", accepted_variants=variants)
    if answer_norm == expected_norm:
        return JudgeResult(True, expected, answer_norm, accepted_variants=variants)
    if answer_norm in variants:
        return JudgeResult(True, expected, answer_norm, message="匹配可接受答案", accepted_variants=variants)
    if allow_inflections:
        forms = word_forms(expected, known_forms)
        if answer_norm in forms:
            return JudgeResult(
                True,
                expected,
                answer_norm,
                message="词形与目标词不同，但属于同一词族",
                accepted_variants=variants,
            )
        if matches_form(answer_norm, expected, known_forms):
            return JudgeResult(True, expected, answer_norm, message="词形匹配", accepted_variants=variants)
    ratio = similarity(expected_norm, answer_norm)
    if ratio >= 0.72:
        return JudgeResult(
            False,
            expected,
            answer_norm,
            "spelling",
            describe_misspelling(expected, answer),
            near_miss=True,
            accepted_variants=variants,
        )
    return JudgeResult(
        False,
        expected,
        answer_norm,
        "wrong_word",
        "与参考答案不同",
        accepted_variants=variants,
    )


def judge_meaning(answer: str, meaning: str, alternatives: list[str] | None = None) -> JudgeResult:
    """Heuristic Chinese meaning check, used only as an auxiliary hint.

    The UI never auto-fails a Chinese answer based on this function; it offers the
    reference and lets the learner decide. This keeps synonym/paraphrase handling honest.
    """
    answer_norm = normalize_answer(answer)
    if not answer_norm:
        return JudgeResult(False, meaning, "", "empty", "未作答")
    candidates = [meaning, *(alternatives or [])]
    for candidate in candidates:
        if answer_norm and answer_norm in normalize_answer(candidate):
            return JudgeResult(True, meaning, answer_norm)
    overlap = _chinese_overlap(answer, " ".join(candidates))
    if overlap >= 0.5:
        return JudgeResult(None, meaning, answer_norm, needs_user_judgement=True, message="部分匹配，请自行判断")
    return JudgeResult(None, meaning, answer_norm, needs_user_judgement=True, message="与参考释义不同，请自行判断")


def _chinese_overlap(answer: str, reference: str) -> float:
    chars = [ch for ch in answer if "\u4e00" <= ch <= "\u9fff"]
    if not chars:
        return 0.0
    hits = sum(1 for ch in chars if ch in reference)
    return hits / len(chars)


def judge_listening(answer: str, expected: str, threshold: float = 0.20) -> JudgeResult:
    expected_norm = normalize_answer(expected)
    answer_norm = normalize_answer(answer)
    if not answer_norm:
        return JudgeResult(False, expected, "", "empty", "未作答")
    if answer_norm == expected_norm:
        return JudgeResult(True, expected, answer_norm)
    distance = _edit_distance(expected_norm.split(), answer_norm.split())
    total = max(1, len(expected_norm.split()))
    rate = distance / total
    if rate <= threshold:
        return JudgeResult(True, expected, answer_norm, message=f"词错误率 {rate:.0%}，判定为正确")
    return JudgeResult(
        False,
        expected,
        answer_norm,
        "listening",
        f"词错误率 {rate:.0%}",
        near_miss=rate <= 0.4,
    )


def _edit_distance(a: list[str], b: list[str]) -> int:
    previous = list(range(len(b) + 1))
    for i, item_a in enumerate(a, 1):
        current = [i]
        for j, item_b in enumerate(b, 1):
            cost = 0 if item_a == item_b else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]
