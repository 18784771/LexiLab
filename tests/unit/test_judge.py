from __future__ import annotations

from lexilab.training.judge import judge_listening, judge_meaning, judge_word_answer


def test_exact_and_case_insensitive():
    assert judge_word_answer("Mitigate", "mitigate").correct is True
    assert judge_word_answer("  mitigate  ", "mitigate").correct is True


def test_inflection_is_accepted_with_note():
    result = judge_word_answer("mitigated", "mitigate")
    assert result.correct is True
    assert "词形" in result.message


def test_spelling_error_is_diagnosed_and_not_correct():
    result = judge_word_answer("mitigete", "mitigate")
    assert result.correct is False
    assert result.error_type == "spelling"
    assert result.near_miss is True
    assert "a" in result.message and "e" in result.message


def test_wrong_word():
    result = judge_word_answer("avoid", "mitigate")
    assert result.correct is False
    assert result.error_type == "wrong_word"


def test_empty_answer():
    result = judge_word_answer("", "mitigate")
    assert result.correct is False
    assert result.error_type == "empty"


def test_chinese_meaning_is_never_auto_failed():
    result = judge_meaning("减轻", "缓解；减轻")
    assert result.correct is True
    uncertain = judge_meaning("降低风险", "缓解；减轻")
    assert uncertain.correct is None
    assert uncertain.needs_user_judgement is True


def test_listening_wer_threshold():
    assert judge_listening("we need to mitigate the risk", "We need to mitigate the risk.").correct is True
    assert judge_listening("we need to mitigate risk", "We need to mitigate the risk.").correct is True
    assert judge_listening("completely different words", "We need to mitigate the risk.").correct is False
