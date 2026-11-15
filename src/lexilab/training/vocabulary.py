from __future__ import annotations

import time

from rich.console import Console
from rich.text import Text

from lexilab.ai.materials import MaterialService
from lexilab.audio.tts import AudioService
from lexilab.storage.learning_repo import LearningRepository
from lexilab.training.judge import judge_word_answer
from lexilab.ui.io import TerminalIO
from lexilab.vocabulary.service import VocabularyService


class DrillSession:
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

    def select_words(self, count: int) -> list[str]:
        rows = self.repo.db.query_all(
            """SELECT c.word_key,
                      COALESCE((SELECT COUNT(*) FROM word_errors e
                                WHERE e.word_key=c.word_key AND e.resolved=0), 0) AS n
               FROM cards c GROUP BY c.word_key
               ORDER BY n DESC, MIN(c.due) ASC LIMIT ?""",
            (count * 3,),
        )
        words = [row["word_key"] for row in rows]
        if len(words) < count:
            words.extend(self.materials.select_target_words(count, exclude=set(words)))
        return words[:count]

    def run(
        self,
        kind: str,
        count: int = 10,
        words: list[str] | None = None,
        contrasts: dict[str, str] | None = None,
    ) -> dict:
        contrasts = contrasts or {}
        if kind == "context":
            targets = (words or self.materials.select_target_words(min(count, 8)))[:count]
            items = self.materials.get_cloze(targets)
        else:
            chosen = (words or self.select_words(count))[:count]
            items = [{"answer": word} for word in chosen]
        if not items:
            self.console.print(Text("没有可训练的词。请先学习一些单词。", style="yellow"))
            return {"answered": 0, "correct": 0}

        correct_total = 0
        answered = 0
        audio_ok = bool(self.audio.status().get("provider_available")) and bool(
            self.audio.status().get("player")
        )
        for index, item in enumerate(items, 1):
            word = item.get("answer") or item.get("word")
            entry = self.vocab.display_entry(self.vocab.lookup(word))
            if entry is None:
                continue
            self.console.print()
            title = {
                "spelling": "SPELLING",
                "recall": "RECALL DRILL",
                "context": "CONTEXT",
                "synonym": "SYNONYM CONTRAST",
                "similar_spelling": "SPELLING CONTRAST",
                "confusion": "CONFUSION DRILL",
            }.get(kind, "DRILL")
            self.console.print(Text(f"{title}   {index}/{len(items)}", style="bold"))
            contrast = contrasts.get(word)
            contrast_entry = (
                self.vocab.display_entry(self.vocab.lookup(contrast)) if contrast else None
            )
            if kind == "context":
                self.console.print(Text(item["sentence"], style="bold"))
                if item.get("translation"):
                    self.console.print(Text(item["translation"], style="dim"))
            else:
                self.console.print(Text(entry.meaning_with_pos(), style="bold"))
                if contrast:
                    prefix = {
                        "synonym": "近义词辨析",
                        "similar_spelling": "形近词辨析",
                        "confusion": "历史混淆",
                    }.get(kind, "对比词")
                    line = f"{prefix}：与 {contrast}"
                    if contrast_entry:
                        line += f"（{contrast_entry.short_meaning}）"
                    self.console.print(Text(line, style="yellow"))
                if kind in {"spelling", "similar_spelling", "confusion"} and audio_ok:
                    self.console.print(Text("[p] 播放发音", style="dim"))
            self.console.print(Text("[Enter] 作答   [s] 跳过   [q] 退出", style="dim"))
            hinted = False
            started = time.monotonic()
            while True:
                key = self.io.read_char()
                if key in {"q", "eof", "esc"}:
                    self.console.print(Text("已退出训练。", style="yellow"))
                    return {"answered": answered, "correct": correct_total, "quit": True}
                if key == "p" and kind == "spelling" and audio_ok:
                    hinted = True
                    play = self.audio.speak(entry.headword)
                    if not play.ok:
                        self.console.print(Text(f"音频不可用: {play.message}", style="dim"))
                    continue
                if key == "s":
                    self.repo.add_training_log(word, kind, correct=None, detail={"skipped": True})
                    self.console.print(Text("已跳过", style="dim"))
                    break
                if key == "enter":
                    answer = self.io.read_line("Your answer: ")
                    if answer is None:
                        return {"answered": answered, "correct": correct_total, "quit": True}
                    answer = answer.strip()
                    if not answer:
                        continue
                    duration_ms = int((time.monotonic() - started) * 1000)
                    judge = judge_word_answer(
                        answer, entry.headword, known_forms=self.vocab.forms_for(entry.word_key)
                    )
                    answered += 1
                    if judge.correct:
                        correct_total += 1
                        self.console.print(Text("正确", style="green"))
                    else:
                        self.console.print(Text("错误", style="red"))
                    self.console.print(Text("参考答案: ", style="dim") + Text(entry.headword, style="bold"))
                    if judge.message:
                        self.console.print(Text(judge.message, style="yellow"))
                    if contrast and not judge.correct and contrast_entry:
                        self.console.print(
                            Text(
                                f"对比：{contrast} = {contrast_entry.short_meaning}",
                                style="dim",
                            )
                        )
                    self.repo.add_training_log(
                        word,
                        kind,
                        correct=judge.correct,
                        hinted=hinted,
                        duration_ms=duration_ms,
                        error_type=judge.error_type,
                        detail={
                            "answer": answer,
                            "expected": entry.headword,
                            "contrast": contrast or "",
                        },
                    )
                    if not judge.correct:
                        self.repo.add_word_error(
                            word, kind, judge.error_type or "wrong_answer", judge.message
                        )
                        found = self.vocab.lookup(answer)
                        if found.found_in != "none" and found.word_key != entry.word_key:
                            self.repo.record_confusion(entry.word_key, found.word_key, skill=kind)
                    elif kind in {"spelling", "recall"}:
                        self.repo.resolve_errors(word, kind)
                    self.io.pause("按 Enter 继续")
                    break
        self.console.print(
            Text(f"训练完成: {correct_total}/{answered} 正确", style="bold"),
        )
        return {"answered": answered, "correct": correct_total}
