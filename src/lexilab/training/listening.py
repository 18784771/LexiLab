from __future__ import annotations

import time

from rich.console import Console
from rich.text import Text

from lexilab.ai.base import AIError
from lexilab.ai.materials import MaterialService
from lexilab.audio.tts import AudioService, TTSUnavailable
from lexilab.storage.learning_repo import LearningRepository
from lexilab.training.judge import judge_listening
from lexilab.ui.io import TerminalIO
from lexilab.vocabulary.normalize import contains_word
from lexilab.vocabulary.service import VocabularyService


class ListeningSession:
    def __init__(
        self,
        materials: MaterialService,
        repo: LearningRepository,
        vocab: VocabularyService,
        audio: AudioService,
        console: Console,
        io: TerminalIO,
    ) -> None:
        self.materials = materials
        self.repo = repo
        self.vocab = vocab
        self.audio = audio
        self.console = console
        self.io = io
        self._audio_warned = False

    def run(
        self,
        *,
        topic: str | None = None,
        difficulty: int = 2,
        target_words: list[str] | None = None,
        count: int = 5,
        force_new: bool = False,
    ) -> dict:
        ok, reason = self.materials.ai.available()
        if not ok:
            raise AIError(f"听力材料生成需要 AI：{reason}")
        status = self.audio.status()
        if not status["provider_available"]:
            raise TTSUnavailable(
                f"没有可用的语音合成: {status['provider_reason']}。"
                "可安装 ffmpeg（含 libflite）或 espeak-ng，详见 README。"
            )
        if not self.audio.player:
            raise TTSUnavailable(f"没有可用的音频播放器: {status['player_reason']}")
        result = self.materials.get_listening(
            topic=topic,
            difficulty=difficulty,
            target_words=target_words,
            count=count,
            force_new=force_new,
        )
        material = result.material
        self.console.print(
            Text(
                f"LISTENING SESSION  |  {material['topic']}  |  {result.meta.label}",
                style="bold",
            )
        )
        if result.cached:
            self.console.print(Text("（使用本地缓存材料）", style="dim"))
        self.console.print(Text("目标词: " + ", ".join(material["target_words"]), style="dim"))

        sentences = material["questions"]
        correct_count = 0
        answered = 0
        for index, item in enumerate(sentences, 1):
            expected = item["answer"]
            translation = item.get("translation", "")
            plays = 0
            replays = 0
            hinted = False
            started = time.monotonic()
            self.console.print()
            self.console.print(Text(f"Sentence {index}/{len(sentences)}", style="bold"))
            self.console.print(Text("[p] 播放   [r] 重播   [h] 提示   [s] 跳过   [q] 退出", style="dim"))
            answer = None
            while True:
                key = self.io.read_char()
                if key in {"q", "eof", "esc"}:
                    return {"material_id": material["id"], "answered": answered, "quit": True}
                if key in {"p", "r"}:
                    play = self.audio.speak(expected)
                    if play.ok:
                        plays += 1
                        if key == "r":
                            replays += 1
                    else:
                        self._warn_audio(play.message)
                    continue
                if key == "h":
                    hinted = True
                    if translation:
                        self.console.print(Text("提示: " + translation, style="yellow"))
                    else:
                        self.console.print(Text("提示: 注意句子中的目标词", style="yellow"))
                    continue
                if key == "s":
                    answer = ""
                    break
                if key == "enter":
                    value = self.io.read_line("Your answer: ")
                    if value is None:
                        return {"material_id": material["id"], "answered": answered, "quit": True}
                    answer = value.strip()
                    break
            duration_ms = int((time.monotonic() - started) * 1000)
            judge = judge_listening(answer, expected) if answer else None
            correct = bool(judge and judge.correct)
            answered += 1
            if correct:
                correct_count += 1
            self.console.print()
            self.console.print(Text("原文: ", style="dim") + Text(expected, style="bold"))
            if translation:
                self.console.print(Text("翻译: " + translation, style="dim"))
            if judge:
                self.console.print(
                    Text("正确" if correct else "需要复习", style="green" if correct else "red")
                )
                if judge.message:
                    self.console.print(Text(judge.message, style="dim"))
            self.repo.record_material_attempt(
                material["id"],
                index - 1,
                answer,
                {
                    "expected": expected,
                    "correct": correct,
                    "plays": plays,
                    "replays": replays,
                    "hinted": hinted,
                },
                correct,
                hinted=hinted,
            )
            involved = [
                target
                for target in material["target_words"]
                if contains_word(expected, target, self.vocab.forms_for(target))
            ]
            targets = involved or material["target_words"][:1]
            for target in targets:
                self.repo.add_training_log(
                    target,
                    "listening",
                    correct=correct,
                    hinted=hinted,
                    duration_ms=duration_ms,
                    error_type=None if correct else (judge.error_type if judge else "empty"),
                    detail={
                        "material_id": material["id"],
                        "sentence": index,
                        "plays": plays,
                        "replays": replays,
                        "answer": answer,
                        "expected": expected,
                    },
                    material_id=material["id"],
                )
                if not correct:
                    self.repo.add_word_error(target, "listening", "dictation_error", "听写错误")
            self.io.pause("按 Enter 继续")
        self.repo.mark_material_used(material["id"])
        self.console.print(
            Text(f"本次听写: {correct_count}/{answered} 正确", style="bold")
            + Text(f"   批改来源: {result.meta.label}", style="dim")
        )
        return {
            "material_id": material["id"],
            "answered": answered,
            "correct": correct_count,
            "mock": result.meta.mock,
        }

    def _warn_audio(self, message: str) -> None:
        if not self._audio_warned:
            self.console.print(Text(f"音频播放失败: {message}", style="yellow"))
            self._audio_warned = True
        else:
            self.console.print(Text("音频播放失败", style="dim"))
