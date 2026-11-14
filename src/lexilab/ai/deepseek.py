from __future__ import annotations

import importlib.util
import time

from lexilab.ai.base import AIError, AIRequest, AIResponse, AIUnavailable
from lexilab.config.settings import Settings


class DeepSeekProvider:
    """OpenAI-compatible DeepSeek client. The model name always comes from config."""

    name = "deepseek"

    def __init__(self, settings: Settings, *, client_factory=None) -> None:
        self.settings = settings
        self._client_factory = client_factory
        self._client = None

    def available(self) -> tuple[bool, str]:
        if not self.settings.ai.enabled:
            return False, "AI 已在配置中禁用"
        if self.settings.ai.provider != "deepseek":
            return False, f"当前 provider 不是 deepseek: {self.settings.ai.provider}"
        if importlib.util.find_spec("openai") is None:
            return False, "未安装 AI 扩展依赖 openai（pip install -r requirements-ai.txt）"
        if not self.settings.api_key():
            return False, f"未设置环境变量 {self.settings.ai.api_key_env}"
        if not self.settings.ai.model.strip():
            return False, "配置 [ai].model 为空（请从 DeepSeek 官方文档选择模型名）"
        return True, "ok"

    def _get_client(self):
        if self._client is None:
            if self._client_factory:
                self._client = self._client_factory()
            else:
                from openai import OpenAI

                self._client = OpenAI(
                    api_key=self.settings.api_key(),
                    base_url=self.settings.ai.base_url,
                    timeout=self.settings.ai.timeout,
                )
        return self._client

    def generate(self, request: AIRequest) -> AIResponse:
        ok, reason = self.available()
        if not ok:
            raise AIUnavailable(reason)
        client = self._get_client()
        attempts = self.settings.ai.retry_count + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            started = time.monotonic()
            try:
                kwargs = {
                    "model": self.settings.ai.model,
                    "messages": [
                        {"role": "system", "content": request.system},
                        {"role": "user", "content": request.user},
                    ],
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens,
                }
                if request.json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                response = client.chat.completions.create(**kwargs)
                latency = int((time.monotonic() - started) * 1000)
                choice = response.choices[0]
                content = (choice.message.content or "").strip()
                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason == "length":
                    raise AIError("响应被截断（finish_reason=length）")
                if not content:
                    raise AIError("响应内容为空")
                usage = {}
                if getattr(response, "usage", None) is not None:
                    try:
                        usage = response.usage.model_dump()
                    except Exception:
                        usage = {}
                return AIResponse(
                    text=content,
                    model=self.settings.ai.model,
                    provider=self.name,
                    usage=usage,
                    finish_reason=finish_reason,
                    latency_ms=latency,
                )
            except Exception as exc:  # SDK exception hierarchy is deliberately not leaked
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(1.0 + attempt)
                    continue
        raise AIUnavailable(f"DeepSeek 请求失败: {type(last_error).__name__}: {last_error}") from last_error
