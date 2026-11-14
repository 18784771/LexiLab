from __future__ import annotations

import json

import pytest

from lexilab.ai.base import AIRequest, AIResponse, AIUnavailable, AIResponseFormatError
from lexilab.ai.materials import MaterialService, MaterialValidationError
from lexilab.ai.schemas import WordInfo
from lexilab.ai.service import AIService


class FailingProvider:
    name = "fake"

    def __init__(self, text="not json", error=None):
        self.text = text
        self.error = error
        self.calls = 0

    def available(self):
        return True, "ok"

    def generate(self, request: AIRequest) -> AIResponse:
        self.calls += 1
        if self.error:
            raise self.error
        return AIResponse(text=self.text, model="fake", provider=self.name, latency_ms=1)


def test_mock_reading_generation_validation_and_cache(mock_context):
    materials = mock_context.materials
    result = materials.get_reading(
        topic="robotics", difficulty=1, target_words=["mitigate", "robust"], force_new=True
    )
    assert result.material["kind"] == "reading"
    assert all(result.coverage.values())
    assert len(result.material["questions"]) >= 2
    assert 100 <= len(result.material["body"].split()) <= 350

    counting = FailingProvider(error=AssertionError("cache must not call AI"))
    materials.ai = AIService(mock_context.settings, mock_context.repo, provider=counting)
    cached = materials.get_reading(
        topic="robotics", difficulty=1, target_words=["mitigate", "robust"]
    )
    assert cached.cached is True
    assert counting.calls == 0


def test_mock_reading_grade_records_attempts_and_training(mock_context):
    materials = mock_context.materials
    result = materials.get_reading(
        topic="robotics", difficulty=1, target_words=["mitigate"], force_new=True
    )
    answers = ["The passage explains the main idea.", "It illustrates a concern.", "Evidence is incomplete."]
    grades, meta = materials.grade_reading(result.material["id"], answers)
    assert len(grades) == 3
    assert meta.mock is True
    attempts = mock_context.repo.db.scalar("SELECT COUNT(*) FROM material_attempts", (), 0)
    assert attempts == 3
    logs = mock_context.repo.db.scalar("SELECT COUNT(*) FROM training_logs WHERE skill='context'", (), 0)
    assert logs == 1


def test_mock_writing_grade_records_word_error(mock_context):
    materials = mock_context.materials
    result = materials.get_writing(level=1, target_words=["mitigate"], force_new=True)
    grade, meta = materials.grade_writing(result.material["id"], "This is a simple sentence.")
    assert meta.mock is True
    assert grade.follow_up_required is True
    assert mock_context.repo.db.scalar("SELECT COUNT(*) FROM word_errors", (), 0) >= 1


def test_invalid_json_is_retried_then_fails(mock_context):
    settings = mock_context.settings
    settings.ai.retry_count = 1
    provider = FailingProvider(text="this is not json")
    service = AIService(settings, mock_context.repo, provider=provider)
    with pytest.raises(AIResponseFormatError):
        service.generate_validated(
            purpose="word_enrich",
            prompt_name="word_enrich",
            schema=WordInfo,
            word="test",
        )
    assert provider.calls == 2


def test_provider_error_is_wrapped(mock_context):
    from tests.helpers import make_due_card

    make_due_card(mock_context.repo, "mitigate")
    before = mock_context.repo.db.scalar("SELECT COUNT(*) FROM cards", (), 0)
    provider = FailingProvider(error=AIUnavailable("network down"))
    service = AIService(mock_context.settings, mock_context.repo, provider=provider)
    with pytest.raises(AIUnavailable):
        service.generate_validated(
            purpose="word_enrich",
            prompt_name="word_enrich",
            schema=WordInfo,
            word="test",
        )
    assert mock_context.repo.db.scalar("SELECT COUNT(*) FROM cards", (), 0) == before
    assert mock_context.repo.db.scalar("SELECT COUNT(*) FROM review_logs", (), 0) == 0


def test_reading_coverage_is_enforced(mock_context):
    body = (
        "This passage is long enough to pass the structural validation but it deliberately "
        "contains none of the requested target vocabulary. It keeps repeating generic statements "
        "about research, evidence, and careful reasoning without using the words the learner needs."
    )
    payload = {
        "title": "No targets",
        "topic": "test",
        "difficulty": 1,
        "body": body,
        "target_words_used": [],
        "questions": [
            {"question": "What is the main idea?", "answer": "Generic research.", "rationale": ""},
            {"question": "What is missing?", "answer": "The target words.", "rationale": ""},
        ],
    }
    provider = FailingProvider(text=json.dumps(payload, ensure_ascii=False))
    service = AIService(mock_context.settings, mock_context.repo, provider=provider)
    materials = MaterialService(
        mock_context.settings, mock_context.repo, mock_context.vocab_repo, service
    )
    with pytest.raises(MaterialValidationError):
        materials.get_reading(topic="test", difficulty=1, target_words=["mitigate", "robust"], force_new=True)
    assert provider.calls == 2
    assert mock_context.repo.db.scalar("SELECT COUNT(*) FROM materials", (), 0) == 0


def test_prompt_versions_are_recorded(mock_context):
    materials = mock_context.materials
    result = materials.get_reading(topic="ai", difficulty=1, target_words=["mitigate"], force_new=True)
    assert result.meta.prompt_version
    row = mock_context.repo.db.query_one(
        "SELECT prompt_version, provider, model FROM materials WHERE id=?", (result.material["id"],)
    )
    assert row["prompt_version"] == result.meta.prompt_version
    assert row["provider"] == "mock"


def test_ai_quota_prevents_unbounded_calls(context):
    context.settings.ai.enabled = True
    context.settings.ai.provider = "mock"
    context.settings.ai.model = "mock-v1"
    context.settings.ai.max_requests_per_day = 1
    context.repo.log_ai_request(
        provider="mock",
        model="mock-v1",
        purpose="test",
        prompt_version="v",
        status="ok",
    )
    service = AIService(context.settings, context.repo)
    from lexilab.ai.base import AIQuotaError

    with pytest.raises(AIQuotaError):
        service.generate_validated(
            purpose="word_enrich",
            prompt_name="word_enrich",
            schema=WordInfo,
            word="test",
        )
