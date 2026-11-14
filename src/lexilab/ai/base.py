from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class AIError(RuntimeError):
    pass


class AIUnavailable(AIError):
    pass


class AIResponseFormatError(AIError):
    pass


class AIQuotaError(AIError):
    pass


@dataclass
class AIRequest:
    purpose: str
    system: str
    user: str
    json_mode: bool = True
    temperature: float = 0.6
    max_tokens: int = 1800
    prompt_version: str = ""
    context: dict = field(default_factory=dict)


@dataclass
class AIResponse:
    text: str
    model: str
    provider: str
    usage: dict = field(default_factory=dict)
    finish_reason: str | None = None
    latency_ms: int = 0


class AIProvider(Protocol):
    name: str

    def available(self) -> tuple[bool, str]:
        ...

    def generate(self, request: AIRequest) -> AIResponse:
        ...
