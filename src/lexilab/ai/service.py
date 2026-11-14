from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from lexilab.ai.base import (
    AIError,
    AIProvider,
    AIQuotaError,
    AIRequest,
    AIResponseFormatError,
    AIUnavailable,
)
from lexilab.ai.deepseek import DeepSeekProvider
from lexilab.ai.jsonutil import parse_model
from lexilab.ai.mock import MockProvider
from lexilab.ai.prompts import load_prompt
from lexilab.config.settings import Settings
from lexilab.storage.learning_repo import LearningRepository

T = TypeVar("T", bound=BaseModel)

SYSTEM_PROMPT = (
    "You are an English teaching assistant for a Chinese CET-6 learner. "
    "Reply with valid json only. Do not include Markdown fences, comments, code or commands."
)


@dataclass
class AICallMeta:
    provider: str
    model: str
    prompt_version: str
    latency_ms: int = 0
    mock: bool = False

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}" + (" (模拟)" if self.mock else "")


class AIService:
    def __init__(self, settings: Settings, repo: LearningRepository, *, provider: AIProvider | None = None) -> None:
        self.settings = settings
        self.repo = repo
        self.provider = provider or self._build_provider()

    def _build_provider(self) -> AIProvider:
        name = self.settings.ai.provider.lower()
        if name == "mock":
            return MockProvider()
        if name == "deepseek":
            return DeepSeekProvider(self.settings)
        return _UnavailableProvider(name)

    def available(self) -> tuple[bool, str]:
        if not self.settings.ai.enabled:
            return False, "AI 未启用（配置 [ai].enabled = false）"
        return self.provider.available()

    @property
    def is_mock(self) -> bool:
        return self.provider.name == "mock"

    def _check_quota(self) -> None:
        limit = self.settings.ai.max_requests_per_day
        if limit and self.repo.ai_requests_today() >= limit:
            raise AIQuotaError(f"今日 AI 请求已达到上限 {limit}（可在配置中调整 max_requests_per_day）")

    def generate_validated(
        self,
        *,
        purpose: str,
        prompt_name: str,
        schema: type[T],
        context: dict | None = None,
        max_tokens: int = 1800,
        temperature: float = 0.6,
        retries: int | None = None,
        **variables,
    ) -> tuple[T, AICallMeta]:
        ok, reason = self.available()
        if not ok:
            raise AIUnavailable(reason)
        self._check_quota()
        prompt = load_prompt(prompt_name)
        user_text = prompt.render(**variables)
        attempt_limit = self.settings.ai.retry_count if retries is None else retries
        request = AIRequest(
            purpose=purpose,
            system=SYSTEM_PROMPT,
            user=user_text,
            json_mode=True,
            temperature=temperature,
            max_tokens=max_tokens,
            prompt_version=prompt.version,
            context=context or {},
        )
        last_error: AIError | None = None
        for attempt in range(attempt_limit + 1):
            try:
                response = self.provider.generate(request)
                model = parse_model(response.text, schema)
                self.repo.log_ai_request(
                    provider=response.provider,
                    model=response.model,
                    purpose=purpose,
                    prompt_version=prompt.version,
                    status="ok",
                    latency_ms=response.latency_ms,
                )
                return model, AICallMeta(
                    provider=response.provider,
                    model=response.model,
                    prompt_version=prompt.version,
                    latency_ms=response.latency_ms,
                    mock=self.is_mock,
                )
            except AIResponseFormatError as exc:
                last_error = exc
                self.repo.log_ai_request(
                    provider=self.provider.name,
                    model=self.settings.ai.model,
                    purpose=purpose,
                    prompt_version=prompt.version,
                    status="format_error",
                    error=str(exc),
                )
                request.user = (
                    user_text
                    + "\n\nYour previous response was invalid: "
                    + str(exc)
                    + "\nReturn one valid json object only, with every required field."
                )
            except AIUnavailable as exc:
                self.repo.log_ai_request(
                    provider=self.provider.name,
                    model=self.settings.ai.model,
                    purpose=purpose,
                    prompt_version=prompt.version,
                    status="error",
                    error=str(exc),
                )
                raise
        assert last_error is not None
        raise last_error


class _UnavailableProvider:
    name = "none"

    def __init__(self, configured_name: str) -> None:
        self.configured_name = configured_name

    def available(self) -> tuple[bool, str]:
        return False, f"未配置可用的 AI provider: {self.configured_name}"

    def generate(self, request: AIRequest):  # pragma: no cover - never reached
        raise AIUnavailable(f"未配置可用的 AI provider: {self.configured_name}")
