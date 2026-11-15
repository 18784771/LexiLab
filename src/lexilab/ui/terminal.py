from __future__ import annotations

import time

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text

from lexilab.audio.tts import AudioService
from lexilab.config.settings import Settings
from lexilab.models.word import WordEntry
from lexilab.ui.base import FeedbackView, ProductionPrompt, RatingResult
from lexilab.ui.io import TerminalIO

RATING_HINT = "[1] 忘记  [2] 困难  [3] 正常  [4] 简单"
VERIFY_HINT = "[1] 没想起来  [2] 困难  [3] 想起来了  [4] 很轻松"


class TerminalUI:
    def __init__(
        self,
        settings: Settings,
        *,
        console: Console | None = None,
        io: TerminalIO | None = None,
        audio: AudioService | None = None,
        audio_available: bool | None = None,
    ) -> None:
        self.settings = settings
        self.console = console or Console(
            highlight=False,
            color_system="auto" if settings.ui.color else None,
        )
        self.io = io or TerminalIO()
        self.audio = audio
        if audio_available is None:
            if audio is None:
                audio_available = False
            else:
                status = audio.status()
                audio_available = bool(status.get("provider_available")) and bool(status.get("player"))
        self.audio_available = audio_available
        self._audio_failed = False

    def _audio_hint(self) -> str:
        return "[p] 发音   " if self.audio_available else ""

    # ----------------------------------------------------------------- basics
    @property
    def compact(self) -> bool:
        return self.console.width < 60

    def _clear(self) -> None:
        if self.io.interactive and self.console.is_terminal:
            self.console.clear()

    def notify(self, message: str, style: str = "info") -> None:
        palette = {
            "info": "cyan",
            "success": "green",
            "warning": "yellow",
            "error": "bold red",
            "muted": "dim",
        }
        self.console.print(Text(message, style=palette.get(style, "cyan")))

    def _header(self, label: str, position: str = "") -> None:
        text = f"{label}   {position}".strip()
        if self.compact:
            self.console.print(Text(text, style="bold"))
        else:
            self.console.rule(Text(text, style="bold"))

    def _show_word(self, word: str) -> None:
        self.console.print(Align.center(Text(word, style="bold cyan")))

    def _hint(self, text: str) -> None:
        self.console.print(Text(text, style="dim"))

    def _render_back(self, entry: WordEntry, mode: str) -> None:
        self.console.print()
        word_line = Text(entry.headword, style="bold cyan")
        if entry.phonetic:
            word_line.append(f"  /{entry.phonetic.strip('/')}/", style="dim")
        self.console.print(Align.center(word_line))
        self.console.print(Align.center(Text(entry.meaning_with_pos())))
        if entry.phrases:
            phrase = entry.phrases[0]
            line = Text(phrase.phrase, style="italic")
            if phrase.translation:
                line.append(f"  {phrase.translation}", style="dim")
            self.console.print(Align.center(line))
        if entry.examples:
            example = entry.examples[0]
            self.console.print()
            self.console.print(Align.center(Text(example.sentence_en, style="italic")))
            if example.sentence_cn:
                self.console.print(Align.center(Text(example.sentence_cn, style="dim")))
        self.console.print()
        extra = "   [e] 详细词义" if mode != "verify" else ""
        audio = "   [p] 发音" if self.audio_available else ""
        self._hint((VERIFY_HINT if mode == "verify" else RATING_HINT) + extra + audio)

    def _render_front(self, entry: WordEntry, mode: str) -> None:
        self._show_word(entry.headword)
        prompt = {
            "new": "请回忆这个单词的含义",
            "verify": "你还能回忆起这个单词吗？",
        }.get(mode, "请回忆这个单词的含义")
        self.console.print(Align.center(Text(prompt)))
        self.console.print()
        self._hint(f"[Enter] 显示答案   {self._audio_hint()}[s] 跳过   [q] 退出")

    def _play(self, text: str) -> None:
        if self.audio is None or not self.audio_available:
            self.notify("语音功能未启用", "muted")
            return
        result = self.audio.speak(text)
        if not result.ok:
            if not self._audio_failed:
                self.notify(f"音频不可用: {result.message}", "warning")
                self._audio_failed = True
            else:
                self.notify("音频不可用", "muted")

    def _show_details(self, entry: WordEntry) -> bool:
        self._clear()
        self._header("WORD DETAILS")
        blocks: list = [Text(entry.headword, style="bold cyan")]
        if entry.phonetic:
            blocks.append(Text(f"/{entry.phonetic.strip('/')}/", style="dim"))
        for item in entry.definitions[:8]:
            line = Text()
            if item.pos:
                line.append(f"{item.pos}. ", style="bold")
            line.append(item.meaning_cn)
            blocks.append(line)
        if entry.definition_en:
            blocks.append(Text(entry.definition_en[:600], style="dim"))
        if entry.phrases:
            blocks.append(Text("短语", style="bold"))
            blocks.extend(
                Text(f"  {p.phrase}  {p.translation}", style="") for p in entry.phrases[:6]
            )
        if entry.synonyms:
            blocks.append(Text("同近义词: " + ", ".join(entry.synonyms[:10]), style="dim"))
        if entry.derivatives:
            blocks.append(Text("同根词: " + "; ".join(entry.derivatives[:6]), style="dim"))
        if entry.examples:
            blocks.append(Text("例句", style="bold"))
            for ex in entry.examples[:3]:
                blocks.append(Text("  " + ex.sentence_en, style="italic"))
                if ex.sentence_cn:
                    blocks.append(Text("  " + ex.sentence_cn, style="dim"))
        self.console.print(Panel(Group(*blocks), border_style="cyan", expand=not self.compact))
        self._hint("[Enter] 返回   [q] 退出")
        while True:
            key = self.io.read_char()
            if key in {"enter", "esc"}:
                return True
            if key in {"q", "eof"}:
                return False

    # --------------------------------------------------------------- new word
    def ask_new_word(self, entry: WordEntry, position: str) -> int:
        self._clear()
        self._header("NEW", position)
        self._show_word(entry.headword)
        self.console.print(Align.center(Text("你认识这个单词吗？")))
        self.console.print()
        self._hint(f"[1] 认识   [2] 不确定   [3] 不认识   {self._audio_hint()}[q] 退出")
        while True:
            key = self.io.read_char()
            if key in {"1", "2", "3"}:
                return int(key)
            if key in {"q", "eof"}:
                return 0
            if key == "p":
                self._play(entry.headword)
            elif key == "e":
                if not self._show_details(entry):
                    return 0
                self._clear()
                self._header("NEW", position)
                self._show_word(entry.headword)
                self.console.print(Align.center(Text("你认识这个单词吗？")))
                self._hint(f"[1] 认识   [2] 不确定   [3] 不认识   {self._audio_hint()}[q] 退出")

    def _mode_label(self, mode: str) -> str:
        if mode == "verify":
            return "VERIFY"
        if mode == "new":
            return "NEW RECALL"
        if mode == "intro":
            return "NEW"
        return "REVIEW"

    def ask_new_word_direction(self, entry: WordEntry, position: str) -> RatingResult:
        return self.ask_recognition(entry, position, mode="intro")

    def _render_word_info(self, entry: WordEntry) -> None:
        blocks: list = []
        line = Text(entry.headword, style="bold cyan")
        if entry.phonetic:
            line.append(f"  /{entry.phonetic.strip('/')}/", style="dim")
        blocks.append(Align.center(line))
        blocks.append(Align.center(Text(entry.meaning_with_pos())))
        if entry.phrases:
            phrase = entry.phrases[0]
            blocks.append(Align.center(Text(f"{phrase.phrase}  {phrase.translation}", style="italic")))
        if entry.examples:
            example = entry.examples[0]
            blocks.append(Align.center(Text(example.sentence_en, style="italic")))
            if example.sentence_cn:
                blocks.append(Align.center(Text(example.sentence_cn, style="dim")))
        if self.compact:
            self.console.print(Group(*blocks))
        else:
            self.console.print(Panel(Group(*blocks), border_style="cyan"))

    def show_word_info(self, entry: WordEntry) -> bool:
        self._clear()
        self._header("NEW WORD")
        self._render_word_info(entry)
        self._hint(f"[Enter] 继续   [e] 详细词义   {self._audio_hint()}[q] 退出")
        while True:
            key = self.io.read_char()
            if key in {"enter", "esc"}:
                return True
            if key in {"q", "eof"}:
                return False
            if key == "p":
                self._play(entry.headword)
            elif key == "e":
                if not self._show_details(entry):
                    return False
                self._clear()
                self._header("NEW WORD")
                self._render_word_info(entry)
                self._hint(f"[Enter] 继续   [e] 详细词义   {self._audio_hint()}[q] 退出")

    # -------------------------------------------------------------- recognition
    def ask_recognition(self, entry: WordEntry, position: str, *, mode: str = "review") -> RatingResult:
        started = time.monotonic()
        hinted = False
        revealed = False
        label = self._mode_label(mode)
        self._clear()
        self._header(label, position)
        self._show_word(entry.headword)
        if entry.phonetic:
            self.console.print(Align.center(Text(f"/{entry.phonetic.strip('/')}/", style="dim")))
        self.console.print(Align.center(Text("↑ 不太确定\n← 不记得        → 容易")))
        self._hint(f"{self._audio_hint()}[e] 详情   [q] 退出")
        while True:
            key = self.io.read_char()
            if key in {"q", "eof", "esc"}:
                return RatingResult(quit=True, duration_ms=int((time.monotonic() - started) * 1000))
            if key == "p":
                self._play(entry.headword)
                hinted = True
                continue
            if key == "e":
                if not self._show_details(entry):
                    return RatingResult(quit=True, duration_ms=int((time.monotonic() - started) * 1000))
                hinted = True
                self._clear()
                self._header(label, position)
                self._show_word(entry.headword)
                self.console.print(Align.center(Text("↑ 不太确定\n← 不记得        → 容易")))
                continue
            if key == "right":
                return RatingResult(rating=4, hinted=hinted, duration_ms=int((time.monotonic() - started) * 1000))
            if key in {"left", "up"}:
                check = key == "up"
                self._clear()
                self._header(label, position)
                self._render_back(entry, mode)
                self._hint("[←] 实际没想起来   [→] 想起来了但困难" if check else "[Enter] 下一词")
                while True:
                    answer_key = self.io.read_char()
                    if answer_key in {"q", "eof", "esc"}:
                        return RatingResult(quit=True, duration_ms=int((time.monotonic() - started) * 1000))
                    if not check and answer_key in {"enter", " "}:
                        revealed = True
                        return RatingResult(rating=1, hinted=hinted, revealed=revealed, duration_ms=int((time.monotonic() - started) * 1000))
                    if check and answer_key == "left":
                        return RatingResult(rating=1, hinted=hinted, revealed=True, duration_ms=int((time.monotonic() - started) * 1000))
                    if check and answer_key == "right":
                        return RatingResult(rating=2, hinted=hinted, revealed=True, duration_ms=int((time.monotonic() - started) * 1000))

    # --------------------------------------------------------------- production
    def ask_production(self, entry: WordEntry, prompt: ProductionPrompt, position: str) -> RatingResult:
        started = time.monotonic()
        hinted = False
        hint_text = ""
        while True:
            self._clear()
            self._header("RECALL", position)
            meaning = Text(prompt.meaning.replace("\n", "；"), style="bold")
            if prompt.pos:
                meaning.append(f"（{prompt.pos}）", style="dim")
            self.console.print(Align.center(meaning))
            if prompt.cloze:
                self.console.print()
                self.console.print(Align.center(Text(prompt.cloze, style="italic")))
            if prompt.example_cn:
                self.console.print(Align.center(Text(prompt.example_cn, style="dim")))
            if hint_text:
                self.console.print(Align.center(Text(hint_text, style="yellow")))
            self.console.print()
            self._hint(f"[Enter] 作答   [h] 提示   {self._audio_hint()}[s] 跳过   [q] 退出")
            key = self.io.read_char()
            if key in {"q", "eof", "esc"}:
                return RatingResult(quit=True, duration_ms=int((time.monotonic() - started) * 1000))
            if key == "s":
                return RatingResult(skipped=True, duration_ms=int((time.monotonic() - started) * 1000))
            if key == "p":
                if self.audio_available:
                    self._play(entry.headword)
                    hinted = True
                    hint_text = "已播放发音（视为提示）"
                continue
            if key == "h":
                hinted = True
                first = entry.headword[:1]
                hint_text = f"首字母 {first}，共 {len(entry.headword)} 个字母"
                continue
            if key == "enter":
                answer = self.io.read_line("Your answer: ")
                if answer is None:
                    return RatingResult(quit=True, duration_ms=int((time.monotonic() - started) * 1000))
                answer = answer.strip()
                if not answer:
                    self.notify("答案为空，请重新作答（或按 s 跳过）", "warning")
                    continue
                return RatingResult(
                    answer=answer,
                    hinted=hinted,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )

    def show_feedback(self, feedback: FeedbackView) -> int | None:
        self._clear()
        self._header("FEEDBACK")
        if feedback.correct:
            self.console.print(Text("正确", style="bold green"))
        elif feedback.correct is False:
            self.console.print(Text("需要复习", style="bold red"))
        else:
            self.console.print(Text("无法自动判定", style="bold yellow"))
        self.console.print(Text("Your answer: ", style="dim") + Text(feedback.given))
        self.console.print(Text("Correct answer: ", style="dim") + Text(feedback.expected, style="bold"))
        if feedback.diagnosis:
            self.console.print(Text(feedback.diagnosis, style="yellow"))
        if feedback.message:
            self.console.print(Text(feedback.message, style="dim"))
        if feedback.reference_sentence:
            self.console.print(Text(feedback.reference_sentence, style="italic"))
        suggested = feedback.suggested_rating or 3
        self.console.print()
        self._hint(RATING_HINT)
        self._hint(f"[Enter] 采用建议 [{suggested}]   [1-4] 覆盖评分   [q] 退出")
        while True:
            key = self.io.read_char()
            if key in {"1", "2", "3", "4"}:
                return int(key)
            if key in {"enter", " "}:
                return suggested
            if key in {"q", "eof", "esc"}:
                return None

    # ------------------------------------------------------------- reinforcement
    def ask_reinforcement(self, entry: WordEntry, position: str) -> bool | None:
        self._clear()
        self._header("REINFORCE", position)
        self._show_word(entry.headword)
        self.console.print(Align.center(Text("短时强化：请再次回忆")))
        self._hint(f"[Enter] 显示答案   {self._audio_hint()}[q] 退出")
        while True:
            key = self.io.read_char()
            if key in {"q", "eof", "esc"}:
                return None
            if key == "p":
                self._play(entry.headword)
            elif key == "enter":
                break
        self._render_back(entry, "review")
        self._hint("[y] 想起来了   [n] 仍没想起来   [q] 退出")
        while True:
            key = self.io.read_char()
            if key == "y":
                return True
            if key == "n":
                return False
            if key in {"q", "eof", "esc"}:
                return None

    # ------------------------------------------------------------------ summary
    def show_summary(self, summary: dict) -> str | None:
        lines = [
            Text(f"复习卡片: {summary.get('reviewed', 0)}"),
            Text(f"新学单词: {summary.get('new_words', 0)}"),
            Text(f"跳过: {summary.get('skipped', 0)}"),
            Text(f"用时: {summary.get('minutes', 0)} min"),
            Text(str(summary.get("message", "")), style="dim"),
        ]
        if summary.get("pending"):
            lines.append(Text(f"未完成学习项: {summary['pending']}（已保存）", style="yellow"))
        title = "SESSION SUMMARY"
        if self.compact:
            self.console.print(Text(title, style="bold"))
            self.console.print(Group(*lines))
        else:
            self.console.print(Panel(Group(*lines), title=title, border_style="green"))
        if not self.io.interactive:
            return None
        self._hint("[Enter] 返回主界面   [r] 继续复习   [n] 额外学习新词   [d] 错词强化")
        key = self.io.read_char()
        return {"r": "review", "n": "new", "d": "drill"}.get(key)
