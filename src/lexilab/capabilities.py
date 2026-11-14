from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from lexilab.config.settings import Settings
from lexilab.storage.learning_repo import LearningRepository
from lexilab.storage.vocab_repo import VocabularyRepository


class CapabilityState(StrEnum):
    READY = "ready"
    DISABLED = "disabled"
    UNCONFIGURED = "unconfigured"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass
class Capability:
    key: str
    label: str
    state: CapabilityState
    reason: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.state == CapabilityState.READY

    @property
    def retryable(self) -> bool:
        return self.state == CapabilityState.ERROR

    @property
    def usable(self) -> bool:
        return self.state in {CapabilityState.READY, CapabilityState.ERROR}


@dataclass
class CapabilityRegistry:
    settings: Settings
    repo: LearningRepository
    vocab: VocabularyRepository
    audio_service: object | None = None

    def collect(self) -> dict[str, Capability]:
        return {
            "vocabulary": self.vocabulary(),
            "fsrs": self.fsrs(),
            "ai": self.ai(),
            "tts": self.tts(),
            "player": self.player(),
            "cached_materials": self.cached_materials(),
        }

    def vocabulary(self) -> Capability:
        try:
            count = self.vocab.count_words()
        except Exception as exc:  # database corruption is a real error
            return Capability("vocabulary", "词库", CapabilityState.ERROR, str(exc))
        if count <= 0:
            return Capability(
                "vocabulary",
                "词库",
                CapabilityState.UNAVAILABLE,
                "词库尚未初始化（运行 lexi init）",
                {"words": 0},
            )
        return Capability("vocabulary", "词库", CapabilityState.READY, f"{count} 条", {"words": count})

    def fsrs(self) -> Capability:
        try:
            from fsrs import Scheduler

            Scheduler(desired_retention=self.settings.learning.desired_retention)
        except Exception as exc:
            return Capability("fsrs", "FSRS", CapabilityState.ERROR, str(exc))
        return Capability(
            "fsrs",
            "FSRS",
            CapabilityState.READY,
            f"desired_retention={self.settings.learning.desired_retention}",
        )

    def ai(self) -> Capability:
        cfg = self.settings.ai
        if not cfg.enabled:
            return Capability("ai", "AI", CapabilityState.DISABLED, "用户未启用 AI")
        if cfg.provider.lower() == "none":
            return Capability("ai", "AI", CapabilityState.DISABLED, "provider = none")
        if cfg.provider.lower() not in {"deepseek", "mock"}:
            return Capability(
                "ai", "AI", CapabilityState.UNAVAILABLE, f"未知 provider: {cfg.provider}"
            )
        if cfg.provider.lower() == "deepseek":
            if importlib.util.find_spec("openai") is None:
                return Capability(
                    "ai",
                    "AI",
                    CapabilityState.UNAVAILABLE,
                    "未安装 AI 扩展依赖 openai（pip install -r requirements-ai.txt）",
                )
            if not cfg.model.strip():
                return Capability(
                    "ai",
                    "AI",
                    CapabilityState.UNCONFIGURED,
                    "配置 [ai].model 为空；请从 DeepSeek 官方文档选择模型名",
                )
            if not self.settings.api_key():
                return Capability(
                    "ai",
                    "AI",
                    CapabilityState.UNCONFIGURED,
                    f"环境变量 {cfg.api_key_env} 未设置",
                )
        error = self._last_ai_error()
        if error:
            return Capability("ai", "AI", CapabilityState.ERROR, error)
        return Capability(
            "ai",
            "AI",
            CapabilityState.READY,
            f"{cfg.provider}/{cfg.model or 'mock'} 已配置（尚不代表远程服务已验证）",
        )

    def _last_ai_error(self) -> str:
        row = self.repo.db.query_one(
            "SELECT status, error, created_at FROM ai_request_logs ORDER BY id DESC LIMIT 1"
        )
        if not row or row["status"] not in {"error", "format_error"}:
            return ""
        try:
            when = datetime.fromisoformat(row["created_at"])
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - when > timedelta(hours=24):
                return ""
        except (TypeError, ValueError):
            pass
        return (row["error"] or row["status"])[:200]

    def tts(self) -> Capability:
        if not self.settings.audio.enabled:
            return Capability("tts", "语音合成", CapabilityState.DISABLED, "音频模块已禁用")
        if self.audio_service is None:
            return Capability("tts", "语音合成", CapabilityState.UNAVAILABLE, "未检测")
        status = self.audio_service.status()
        if not status.get("provider_available"):
            return Capability(
                "tts",
                "语音合成",
                CapabilityState.UNAVAILABLE,
                str(status.get("provider_reason") or "无可用 TTS"),
                status,
            )
        return Capability(
            "tts",
            "语音合成",
            CapabilityState.READY,
            f"{status.get('provider')}",
            status,
        )

    def player(self) -> Capability:
        if not self.settings.audio.enabled:
            return Capability("player", "音频播放", CapabilityState.DISABLED, "音频模块已禁用")
        if self.audio_service is None:
            return Capability("player", "音频播放", CapabilityState.UNAVAILABLE, "未检测")
        status = self.audio_service.status()
        if not status.get("player"):
            return Capability(
                "player",
                "音频播放",
                CapabilityState.UNAVAILABLE,
                str(status.get("player_reason") or "无可用播放器"),
                status,
            )
        return Capability(
            "player",
            "音频播放",
            CapabilityState.READY,
            str(status.get("player")),
            status,
        )

    def cached_materials(self) -> Capability:
        count = int(
            self.repo.db.scalar("SELECT COUNT(*) FROM materials WHERE status != 'deleted'", (), 0) or 0
        )
        if count <= 0:
            return Capability(
                "cached_materials",
                "本地材料",
                CapabilityState.UNAVAILABLE,
                "暂无缓存材料",
                {"count": 0},
            )
        return Capability(
            "cached_materials",
            "本地材料",
            CapabilityState.READY,
            f"{count} 份",
            {"count": count},
        )


def audio_ready(caps: dict[str, Capability]) -> bool:
    return caps["tts"].ready and caps["player"].ready


def ai_usable(caps: dict[str, Capability]) -> bool:
    return caps["ai"].usable


def ai_message(caps: dict[str, Capability], module: str = "AI 训练") -> str:
    cap = caps["ai"]
    if cap.state == CapabilityState.DISABLED:
        return (
            f"{module}模块尚未启用。\n\n"
            "如需使用，请执行：\n"
            "  lexi config ai\n"
            "（AI 是可选增强功能，基础背单词功能不受影响。）"
        )
    if cap.state == CapabilityState.UNCONFIGURED:
        return (
            f"{module}模块尚未配置完整：{cap.reason}\n\n"
            "请执行：\n"
            "  lexi config ai"
        )
    if cap.state == CapabilityState.UNAVAILABLE:
        return (
            f"{module}模块当前不可用：{cap.reason}\n\n"
            "如需使用：\n"
            "  pip install -r requirements-ai.txt\n"
            "  lexi config ai"
        )
    if cap.state == CapabilityState.ERROR:
        return (
            f"上次 AI 请求失败：{cap.reason}\n\n"
            "可以稍后重试，或改用本地训练（拼写 / 语境填空 / 听写）。"
        )
    return ""
