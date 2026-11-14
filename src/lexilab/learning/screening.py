from __future__ import annotations

from datetime import timedelta

from rich.console import Console
from rich.text import Text

from lexilab.audio.tts import AudioService
from lexilab.config.settings import Settings
from lexilab.memory.engine import MemoryService
from lexilab.storage.learning_repo import LearningRepository
from lexilab.storage.schema import utcnow
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.ui.io import TerminalIO
from lexilab.vocabulary.service import VocabularyService


class ScreeningService:
    def __init__(
        self,
        settings: Settings,
        repo: LearningRepository,
        vocab_repo: VocabularyRepository,
        vocab: VocabularyService,
        memory: MemoryService,
        audio: AudioService,
        console: Console,
        io: TerminalIO,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.vocab_repo = vocab_repo
        self.vocab = vocab
        self.memory = memory
        self.audio = audio
        self.console = console
        self.io = io

    def run(self, limit: int = 50) -> dict:
        book = self.repo.get_setting("active_book", "cet6") or "cet6"
        exclude = self.repo.learned_keys() | self.repo.screening_known_keys()
        candidates = self.vocab_repo.new_candidates(book, limit, exclude)
        if not candidates:
            self.console.print(Text("没有可筛选的新词。", style="green"))
            return {"seen": 0, "known": 0, "learning": 0}
        known = 0
        learning = 0
        seen = 0
        audio_status = self.audio.status()
        audio_ok = bool(audio_status.get("provider_available")) and bool(audio_status.get("player"))
        for index, word_key in enumerate(candidates, 1):
            entry = self.vocab.display_entry(self.vocab.lookup(word_key))
            if entry is None:
                continue
            self.console.print()
            self.console.print(Text(f"SCREEN   {index}/{len(candidates)}", style="bold"))
            self.console.print(Text(entry.headword, style="bold cyan"))
            if entry.phonetic:
                self.console.print(Text(f"/{entry.phonetic.strip('/')}/", style="dim"))
            self.console.print(
                Text(
                    "[1] 已认识   [2] 不确定   [3] 不认识   "
                    + ("[p] 发音   " if audio_ok else "")
                    + "[q] 退出",
                    style="dim",
                )
            )
            while True:
                key = self.io.read_char()
                if key in {"q", "eof", "esc"}:
                    self.console.print(Text("已退出筛选。", style="yellow"))
                    return {"seen": seen, "known": known, "learning": learning, "quit": True}
                if key == "p":
                    if audio_ok:
                        play = self.audio.speak(entry.headword)
                        if not play.ok:
                            self.console.print(Text(f"音频不可用: {play.message}", style="dim"))
                    continue
                if key not in {"1", "2", "3"}:
                    continue
                seen += 1
                if key == "1":
                    known += 1
                    days = self.settings.learning.screen_verify_days
                    first = days[0] if days else 1
                    self.repo.upsert_screening(entry.word_key, utcnow() + timedelta(days=first))
                    self.repo.add_training_log(
                        entry.word_key,
                        "recognition",
                        correct=None,
                        detail={"step": "screening_known", "note": "requires deferred verification"},
                    )
                else:
                    learning += 1
                    self.memory.ensure_cards(
                        entry.word_key,
                        recall_suspended=self.settings.learning.recall_delay_days > 0,
                    )
                    self.repo.add_training_log(
                        entry.word_key,
                        "recognition",
                        correct=None,
                        detail={"step": "screening_learning", "response": int(key)},
                    )
                break
        self.console.print()
        self.console.print(
            Text(f"筛选完成: 已认识 {known}，进入学习 {learning}，共 {seen}", style="bold")
        )
        self.console.print(Text("“已认识”将在后续到期抽查中被验证，不会直接永久标记为掌握。", style="dim"))
        return {"seen": seen, "known": known, "learning": learning}
