from __future__ import annotations

import random
import time

from rich.console import Console
from rich.text import Text

from lexilab.audio.tts import AudioService, TTSUnavailable
from lexilab.config.settings import Settings
from lexilab.storage.learning_repo import LearningRepository
from lexilab.storage.vocab_repo import VocabularyRepository
from lexilab.training.judge import judge_listening, judge_word_answer
from lexilab.ui.io import TerminalIO
from lexilab.vocabulary.service import VocabularyService


class AudioDrillSession:
    """Level-1 offline listening drills. No LLM is involved."""

    def __init__(
        self,
        settings: Settings,
        repo: LearningRepository,
        vocab_repo: VocabularyRepository,
        vocab: VocabularyService,
        audio: AudioService,
        console: Console,
        io: TerminalIO,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.vocab_repo = vocab_repo
        self.vocab = vocab
        self.audio = audio
        self.console = console
        self.io = io

    def _ensure_audio(self) -> None:
        status = self.audio.status()
        if not status.get("provider_available"):
            raise TTSUnavailable(f"语音合成不可用: {status.get('provider_reason')}")
        if not status.get("player"):
            raise TTSUnavailable(f"音频播放不可用: {status.get('player_reason')}")

    def _candidates(self, count: int, *, need_example: bool = False) -> list[str]:
        rows = self.repo.db.query_all(
            """SELECT c.word_key,
                      COALESCE((SELECT COUNT(*) FROM word_errors e
                                WHERE e.word_key=c.word_key AND e.resolved=0), 0) AS n
               FROM cards c GROUP BY c.word_key ORDER BY n DESC, MIN(c.due) LIMIT ?""",
            (count * 5,),
        )
        keys = [row["word_key"] for row in rows]
        if len(keys) < count:
            book = self.repo.get_setting("active_book", "cet6") or "cet6"
            keys.extend(
                self.vocab_repo.new_candidates(
                    book, count * 3, self.repo.learned_keys() | set(keys)
                )
            )
        result: list[str] = []
        for key in keys:
            entry = self.vocab_repo.get_entry(key)
            if entry is None:
                continue
            if need_example and not entry.example_for_cloze():
                continue
            result.append(key)
            if len(result) >= count:
                break
        return result

    def run(self, kind: str, count: int = 8) -> dict:
        self._ensure_audio()
        need_example = kind == "sentence"
        words = self._candidates(count, need_example=need_example)
        if not words:
            self.console.print(Text("没有可训练的词。请先学习一些单词。", style="yellow"))
            return {"answered": 0, "correct": 0}
        if kind == "listening":
            return self._run_listening_words(words)
        if kind == "dictation":
            return self._run_dictation(words)
        return self._run_sentences(words)

    def _run_listening_words(self, words: list[str]) -> dict:
        pool = self._candidates(max(12, len(words) * 3))
        entries = {
            key: self.vocab_repo.get_entry(key)
            for key in dict.fromkeys(words + pool)
            if self.vocab_repo.get_entry(key) is not None
        }
        answered = 0
        correct_total = 0
        rng = random.Random(20260101)
        for index, word in enumerate(words, 1):
            entry = entries.get(word)
            if entry is None:
                continue
            distractors = [
                e for k, e in entries.items() if k != word and e.primary_meaning
            ]
            rng.shuffle(distractors)
            options = [entry] + distractors[:3]
            rng.shuffle(options)
            correct_index = next(i for i, item in enumerate(options) if item.word_key == word)
            self.console.print()
            self.console.print(Text(f"LISTENING   {index}/{len(words)}", style="bold"))
            plays = 0
            started = time.monotonic()
            play = self.audio.speak(entry.headword)
            if play.ok:
                plays += 1
            else:
                self.console.print(Text(f"音频不可用: {play.message}", style="yellow"))
            for i, option in enumerate(options, 1):
                self.console.print(Text(f"  [{i}] {option.primary_meaning.replace(chr(10), '；')[:80]}"))
            self.console.print(Text("[p] 重播   [1-4] 选择   [s] 跳过   [q] 退出", style="dim"))
            while True:
                key = self.io.read_char()
                if key in {"q", "eof", "esc"}:
                    return {"answered": answered, "correct": correct_total, "quit": True}
                if key == "p":
                    play = self.audio.speak(entry.headword)
                    if play.ok:
                        plays += 1
                    continue
                if key == "s":
                    self.repo.add_training_log(
                        word, "listening", correct=None, detail={"mode": "meaning_choice", "skipped": True}
                    )
                    break
                if key in {"1", "2", "3", "4"}:
                    answered += 1
                    correct = int(key) - 1 == correct_index
                    correct_total += int(correct)
                    duration = int((time.monotonic() - started) * 1000)
                    self.console.print(
                        Text(("正确" if correct else "错误"), style="green" if correct else "red")
                    )
                    self.console.print(
                        Text("单词: ", style="dim")
                        + Text(entry.headword, style="bold")
                        + Text(f"  {entry.meaning_with_pos()}", style="dim")
                    )
                    self.repo.add_training_log(
                        word,
                        "listening",
                        correct=correct,
                        hinted=plays > 1,
                        duration_ms=duration,
                        error_type=None if correct else "meaning_choice",
                        detail={"mode": "meaning_choice", "plays": plays, "answer_index": int(key)},
                    )
                    if not correct:
                        self.repo.add_word_error(word, "listening", "meaning_choice", "听音辨义错误")
                    self.io.pause("按 Enter 继续")
                    break
        self.console.print(Text(f"训练完成: {correct_total}/{answered} 正确", style="bold"))
        return {"answered": answered, "correct": correct_total}

    def _run_dictation(self, words: list[str]) -> dict:
        answered = 0
        correct_total = 0
        for index, word in enumerate(words, 1):
            entry = self.vocab_repo.get_entry(word)
            if entry is None:
                continue
            self.console.print()
            self.console.print(Text(f"WORD DICTATION   {index}/{len(words)}", style="bold"))
            self.console.print(Text("[p] 重播   [Enter] 作答   [s] 跳过   [q] 退出", style="dim"))
            plays = 0
            started = time.monotonic()
            play = self.audio.speak(entry.headword)
            if play.ok:
                plays += 1
            else:
                self.console.print(Text(f"音频不可用: {play.message}", style="yellow"))
            while True:
                key = self.io.read_char()
                if key in {"q", "eof", "esc"}:
                    return {"answered": answered, "correct": correct_total, "quit": True}
                if key == "p":
                    if self.audio.speak(entry.headword).ok:
                        plays += 1
                    continue
                if key == "s":
                    self.repo.add_training_log(
                        word, "listening", correct=None, detail={"mode": "word_dictation", "skipped": True}
                    )
                    break
                if key == "enter":
                    answer = self.io.read_line("Your answer: ")
                    if answer is None:
                        return {"answered": answered, "correct": correct_total, "quit": True}
                    if not answer.strip():
                        continue
                    judge = judge_word_answer(
                        answer,
                        entry.headword,
                        known_forms=self.vocab.forms_for(entry.word_key),
                    )
                    answered += 1
                    correct_total += int(bool(judge.correct))
                    self.console.print(
                        Text("正确" if judge.correct else "错误", style="green" if judge.correct else "red")
                    )
                    self.console.print(Text("答案: ", style="dim") + Text(entry.headword, style="bold"))
                    if judge.message:
                        self.console.print(Text(judge.message, style="yellow"))
                    self.repo.add_training_log(
                        word,
                        "listening",
                        correct=judge.correct,
                        hinted=plays > 1,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        error_type=judge.error_type,
                        detail={"mode": "word_dictation", "plays": plays, "answer": answer},
                    )
                    if not judge.correct:
                        self.repo.add_word_error(
                            word, "listening", judge.error_type or "dictation", "单词听写错误"
                        )
                    self.io.pause("按 Enter 继续")
                    break
        self.console.print(Text(f"训练完成: {correct_total}/{answered} 正确", style="bold"))
        return {"answered": answered, "correct": correct_total}

    def _run_sentences(self, words: list[str]) -> dict:
        answered = 0
        correct_total = 0
        for index, word in enumerate(words, 1):
            entry = self.vocab_repo.get_entry(word)
            if entry is None:
                continue
            example = entry.example_for_cloze()
            if example is None:
                continue
            expected = example.sentence_en
            self.console.print()
            self.console.print(Text(f"SENTENCE DICTATION   {index}/{len(words)}", style="bold"))
            self.console.print(Text("[p] 重播   [h] 提示   [Enter] 作答   [s] 跳过   [q] 退出", style="dim"))
            plays = 0
            hinted = False
            started = time.monotonic()
            play = self.audio.speak(expected)
            if play.ok:
                plays += 1
            else:
                self.console.print(Text(f"音频不可用: {play.message}", style="yellow"))
            while True:
                key = self.io.read_char()
                if key in {"q", "eof", "esc"}:
                    return {"answered": answered, "correct": correct_total, "quit": True}
                if key == "p":
                    if self.audio.speak(expected).ok:
                        plays += 1
                    continue
                if key == "h":
                    hinted = True
                    self.console.print(Text("提示: " + example.sentence_cn, style="yellow"))
                    continue
                if key == "s":
                    self.repo.add_training_log(
                        word, "listening", correct=None, detail={"mode": "sentence_dictation", "skipped": True}
                    )
                    break
                if key == "enter":
                    answer = self.io.read_line("Your answer: ")
                    if answer is None:
                        return {"answered": answered, "correct": correct_total, "quit": True}
                    if not answer.strip():
                        continue
                    judge = judge_listening(answer, expected, threshold=0.25)
                    answered += 1
                    correct_total += int(bool(judge.correct))
                    self.console.print(
                        Text("正确" if judge.correct else "错误", style="green" if judge.correct else "red")
                    )
                    self.console.print(Text("原文: ", style="dim") + Text(expected, style="bold"))
                    if example.sentence_cn:
                        self.console.print(Text(example.sentence_cn, style="dim"))
                    self.repo.add_training_log(
                        word,
                        "listening",
                        correct=judge.correct,
                        hinted=hinted or plays > 1,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        error_type=judge.error_type,
                        detail={"mode": "sentence_dictation", "plays": plays, "answer": answer},
                    )
                    if not judge.correct:
                        self.repo.add_word_error(word, "listening", "sentence_dictation", "句子听写错误")
                    self.io.pause("按 Enter 继续")
                    break
        self.console.print(Text(f"训练完成: {correct_total}/{answered} 正确", style="bold"))
        return {"answered": answered, "correct": correct_total}
