from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, field_validator

from lexilab.paths import default_data_dir, project_root

DEFAULT_CONFIG_TEXT = """\
[general]
data_dir = "data"

[learning]
new_words_per_day = 10
daily_minutes = 30
desired_retention = 0.90
max_reviews_per_session = 80
pause_new_when_due_over = 60
recall_delay_days = 2
interleave_gap = 3
review_seconds = 25
new_word_seconds = 70
reading_target_min = 5
reading_target_max = 10
screen_verify_days = [1, 3, 7, 14, 30, 90]

[ai]
enabled = false
provider = "deepseek"
base_url = "https://api.deepseek.com"
model = ""
api_key_env = "DEEPSEEK_API_KEY"
timeout = 60
retry_count = 2
max_requests_per_day = 30
reading_words_min = 150
reading_words_max = 250

[audio]
enabled = true
provider = "auto"
voice = "slt"
rate = 0.95
player = "auto"

[ui]
language = "zh"
color = true
show_timer = true
textual = true

[effects]
enabled = true
intensity = "normal"
typing_particles = true
shake_on_error = true
pulse_on_correct = true
combo = true
startup_animation = true
reduced_motion = false
max_particles = 240
"""


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class GeneralSettings(_Base):
    data_dir: str = "data"
    timezone: str = "local"


class LearningSettings(_Base):
    new_words_per_day: int = Field(default=10, ge=0, le=500)
    daily_minutes: int = Field(default=30, ge=1, le=600)
    desired_retention: float = Field(default=0.90, ge=0.70, le=0.97)
    max_reviews_per_session: int = Field(default=80, ge=1, le=2000)
    pause_new_when_due_over: int = Field(default=60, ge=1, le=5000)
    recall_delay_days: int = Field(default=2, ge=0, le=60)
    interleave_gap: int = Field(default=3, ge=0, le=20)
    review_seconds: int = Field(default=25, ge=3, le=600)
    new_word_seconds: int = Field(default=70, ge=5, le=1200)
    reading_target_min: int = Field(default=5, ge=1, le=20)
    reading_target_max: int = Field(default=10, ge=1, le=30)
    screen_verify_days: list[int] = Field(default_factory=lambda: [1, 3, 7, 14, 30, 90])

    @field_validator("desired_retention")
    @classmethod
    def _round_retention(cls, value: float) -> float:
        return round(value, 4)


class AISettings(_Base):
    enabled: bool = False
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    model: str = ""
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout: float = Field(default=60, ge=5, le=600)
    retry_count: int = Field(default=2, ge=0, le=5)
    max_requests_per_day: int = Field(default=30, ge=0, le=500)
    reading_words_min: int = Field(default=150, ge=50, le=1000)
    reading_words_max: int = Field(default=250, ge=80, le=2000)


class AudioSettings(_Base):
    enabled: bool = True
    provider: str = "auto"
    voice: str = "slt"
    rate: float = Field(default=0.95, ge=0.5, le=2.0)
    player: str = "auto"


class UISettings(_Base):
    language: str = "zh"
    color: bool = True
    show_timer: bool = True
    textual: bool = True


class EffectsSettings(_Base):
    enabled: bool = True
    intensity: Literal["off", "minimal", "normal", "power"] = "normal"
    typing_particles: bool = True
    shake_on_error: bool = True
    pulse_on_correct: bool = True
    combo: bool = True
    startup_animation: bool = True
    reduced_motion: bool = False
    max_particles: int = Field(default=240, ge=0, le=1000)


class Settings(_Base):
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    learning: LearningSettings = Field(default_factory=LearningSettings)
    ai: AISettings = Field(default_factory=AISettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    ui: UISettings = Field(default_factory=UISettings)
    effects: EffectsSettings = Field(default_factory=EffectsSettings)

    # Runtime-only fields.
    data_dir: Path = Field(default_factory=default_data_dir)
    config_path: Path | None = None

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for name in ("raw", "audio", "backups"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)

    @property
    def vocabulary_db(self) -> Path:
        return self.data_dir / "vocabulary.db"

    @property
    def learning_db(self) -> Path:
        return self.data_dir / "learning.db"

    def api_key(self) -> str | None:
        value = os.environ.get(self.ai.api_key_env, "").strip()
        return value or None


def _candidate_configs() -> list[Path]:
    candidates: list[Path] = []
    env = os.environ.get("LEXILAB_CONFIG")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(project_root() / "configs" / "settings.toml")
    candidates.append(Path.home() / ".config" / "lexilab" / "settings.toml")
    return candidates


def load_settings(config_path: str | Path | None = None) -> Settings:
    path: Path | None = None
    if config_path:
        path = Path(config_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"配置文件不存在: {path}")
    else:
        for candidate in _candidate_configs():
            if candidate.is_file():
                path = candidate
                break

    raw: dict = {}
    if path is not None:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)

    settings = Settings.model_validate(raw)
    settings.config_path = path

    base_dir = project_root() if path is None else path.resolve().parent
    if path is not None and base_dir.name == "configs":
        base_dir = base_dir.parent
    env_data_dir = os.environ.get("LEXILAB_DATA_DIR")
    if env_data_dir:
        data_dir = Path(env_data_dir).expanduser().resolve()
    else:
        configured = Path(settings.general.data_dir).expanduser()
        data_dir = configured if configured.is_absolute() else (base_dir / configured).resolve()
    settings.data_dir = data_dir
    return settings


def write_default_config(path: str | Path, *, force: bool = False) -> Path:
    target = Path(path).expanduser()
    if target.exists() and not force:
        raise FileExistsError(f"配置文件已存在: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return target


def save_settings(settings: Settings, path: str | Path) -> Path:
    target = Path(path).expanduser()
    data = settings.model_dump(
        include={"general", "learning", "ai", "audio", "ui", "effects"},
        exclude_none=True,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as fh:
        tomli_w.dump(data, fh)
    return target


def config_summary(settings: Settings) -> dict[str, object]:
    return {
        "config_path": str(settings.config_path) if settings.config_path else "(defaults)",
        "data_dir": str(settings.data_dir),
        "desired_retention": settings.learning.desired_retention,
        "new_words_per_day": settings.learning.new_words_per_day,
        "ai_provider": settings.ai.provider,
        "ai_model": settings.ai.model or "(not set)",
        "ai_enabled": settings.ai.enabled,
        "tts_provider": settings.audio.provider,
        "tts_voice": settings.audio.voice,
        "effects": f"{settings.effects.intensity}" + (" (on)" if settings.effects.enabled else " (off)"),
        "textual_ui": settings.ui.textual,
    }
