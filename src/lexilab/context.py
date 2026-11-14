from __future__ import annotations

from rich.console import Console

from lexilab.ai.materials import MaterialService
from lexilab.ai.service import AIService
from lexilab.analytics.stats import AnalyticsService
from lexilab.audio.tts import AudioService
from lexilab.capabilities import Capability, CapabilityRegistry
from lexilab.config.settings import Settings
from lexilab.learning.planner import Planner
from lexilab.learning.session import LearningSession
from lexilab.memory.engine import MemoryService
from lexilab.storage.connection import Database
from lexilab.storage.learning_repo import LearningRepository
from lexilab.storage.schema import ensure_learning_schema, ensure_vocabulary_schema
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.ui.io import TerminalIO
from lexilab.ui.terminal import TerminalUI
from lexilab.vocabulary.service import VocabularyService


class AppContext:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_dirs()
        self.console = Console(
            highlight=False,
            color_system="auto" if settings.ui.color else None,
        )
        self.io = TerminalIO()
        self.vocab_db = Database(settings.vocabulary_db)
        self.learning_db = Database(settings.learning_db)
        ensure_vocabulary_schema(self.vocab_db)
        ensure_learning_schema(self.learning_db)
        self.vocab_repo = VocabularyRepository(self.vocab_db)
        self.repo = LearningRepository(self.learning_db)
        self.memory = MemoryService(self.repo, settings.learning.desired_retention)
        self.vocab = VocabularyService(self.vocab_repo, self.repo)
        self.ai = AIService(settings, self.repo)
        self.materials = MaterialService(settings, self.repo, self.vocab_repo, self.ai)
        self.analytics = AnalyticsService(self.repo, self.vocab_repo)
        self.planner = Planner(settings, self.repo, self.vocab_repo, self.memory)
        self._audio: AudioService | None = None
        self._ui: TerminalUI | None = None
        self._capabilities: dict[str, Capability] | None = None

    @property
    def audio(self) -> AudioService:
        if self._audio is None:
            self._audio = AudioService(self.settings)
        return self._audio

    @property
    def capabilities(self) -> dict[str, Capability]:
        if self._capabilities is None:
            audio = self.audio if self.settings.audio.enabled else None
            self._capabilities = CapabilityRegistry(
                self.settings, self.repo, self.vocab_repo, audio
            ).collect()
        return self._capabilities

    @property
    def ui(self) -> TerminalUI:
        if self._ui is None:
            self._ui = TerminalUI(
                self.settings,
                console=self.console,
                io=self.io,
                audio=self.audio,
                audio_available=(
                    self.capabilities["tts"].ready and self.capabilities["player"].ready
                ),
            )
        return self._ui

    def learning_session(self) -> LearningSession:
        return LearningSession(self.settings, self.repo, self.memory, self.vocab, self.ui)

    def has_vocabulary(self) -> bool:
        return self.vocab_repo.count_words() > 0

    def has_learning_data(self) -> bool:
        return self.repo.count_cards() > 0 or bool(self.repo.list_personal())

    def active_book(self) -> str:
        return self.repo.get_setting("active_book", "cet6") or "cet6"
