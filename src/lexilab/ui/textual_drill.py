from __future__ import annotations

import threading
import time

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, Static

from lexilab.context import AppContext
from lexilab.training.judge import judge_word_answer
from lexilab.ui.effects.engine import EffectEvent, EffectsEngine, EffectsState
from lexilab.ui.effects.presets import preset_for
from lexilab.ui.effects.shake import shake_offsets
from lexilab.ui.textual_widgets import ComboBadge, ParticleCanvas, PowerInput

CSS = """
Screen { background: $surface; color: $text; }
#logo { height: 3; content-align: center middle; text-style: bold; color: $accent; }
#hud { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
#prompt { height: auto; content-align: center middle; }
#meta { height: 1; padding: 0 2; color: $text-muted; }
#answer { margin: 1 4; border: round $accent; }
#particles { height: 3; padding: 0 1; }
#combo { height: 1; content-align: center middle; }
#feedback { height: auto; margin: 1 3; }
#notice { height: 1; padding: 0 1; color: $warning; }
#footer { height: 1; dock: bottom; padding: 0 1; background: $panel; color: $text-muted; }
"""


class LexiLabDrillApp(App):
    ENABLE_COMMAND_PALETTE = True
    CSS = CSS
    BINDINGS = [
        Binding("ctrl+q", "save_quit", "保存退出", priority=True),
        Binding("ctrl+t", "toggle_effects", "切换特效", priority=True),
        Binding("ctrl+p", "command_palette", "命令面板", priority=True),
        Binding("escape", "back", "返回", priority=True),
        Binding("f1", "hint", "提示", priority=True),
        Binding("f2", "audio", "发音", priority=True),
    ]

    def __init__(self, context: AppContext, kind: str, count: int) -> None:
        super().__init__()
        self.context = context
        self.kind = kind
        self.count = count
        self.runtime = preset_for(context.settings)
        self.effects = EffectsEngine(self.runtime, sink=self._effect_sink)
        self._ui_thread = 0
        self.words = self._select_words(count)
        self.index = 0
        self.correct = 0
        self.answered = 0
        self.mode = "idle"
        self.entry = None
        self._started = 0.0
        self._hinted = False
        self._last_judge = None

    def _select_words(self, count: int) -> list[str]:
        rows = self.context.repo.db.query_all(
            """SELECT c.word_key,
                      COALESCE((SELECT COUNT(*) FROM word_errors e
                                WHERE e.word_key=c.word_key AND e.resolved=0), 0) AS n
               FROM cards c GROUP BY c.word_key
               ORDER BY n DESC, MIN(c.due) ASC LIMIT ?""",
            (count * 3,),
        )
        words = [row["word_key"] for row in rows]
        if len(words) < count:
            words.extend(self.context.materials.select_target_words(count, exclude=set(words)))
        return words[:count]

    def compose(self) -> ComposeResult:
        self._canvas = ParticleCanvas(self.effects, id="particles")
        self._combo = ComboBadge(id="combo")
        self._answer = PowerInput(self._canvas, self.effects, id="answer", placeholder="输入英文…")
        yield Static("LexiLab · Drill", id="logo")
        yield Static("", id="hud")
        yield Static("", id="prompt")
        yield Static("", id="meta")
        yield self._answer
        yield self._canvas
        yield self._combo
        yield Static("", id="feedback")
        yield Static("", id="notice")
        yield Static("", id="footer")

    @property
    def answer(self) -> PowerInput:
        return self._answer

    def on_mount(self) -> None:
        self._ui_thread = threading.get_ident()
        self._answer.display = False
        self._answer.disabled = True
        self._answer.can_focus = False
        self.query_one("#footer", Static).update(Text("[Ctrl+Q] 退出   [Ctrl+T] 特效", style="dim"))
        if not self.words:
            self._finish_empty()
            return
        self._present_word()

    def _present_word(self) -> None:
        if self.index >= len(self.words):
            self._present_summary()
            return
        word = self.words[self.index]
        self.entry = self.context.vocab.display_entry(self.context.vocab.lookup(word))
        if self.entry is None:
            self.index += 1
            self._present_word()
            return
        self.mode = "typing"
        self._hinted = False
        self._started = time.monotonic()
        self.query_one("#hud", Static).update(
            Text(f"{self.kind.upper()}   {self.index + 1}/{len(self.words)}", style="bold")
        )
        self.query_one("#prompt", Static).update(Text(self.entry.meaning_with_pos(), style="bold"))
        self.query_one("#meta", Static).update(Text(f"/{self.entry.phonetic.strip('/')}/", style="dim"))
        self.query_one("#feedback", Static).update(Text(""))
        self.query_one("#notice", Static).update(Text(""))
        self._answer.display = True
        self._answer.disabled = False
        self._answer.can_focus = True
        self._answer.reset_text()
        self._answer.focus()
        self.query_one("#footer", Static).update(
            Text(
                "[Enter] 提交   [F1] 提示   [F2] 发音   [Ctrl+Q] 退出",
                style="dim",
            )
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.mode != "typing" or self.entry is None:
            return
        answer = event.value.strip()
        if not answer:
            self.notify_message("答案为空")
            return
        judge = judge_word_answer(
            answer,
            self.entry.headword,
            known_forms=self.context.vocab.forms_for(self.entry.word_key),
        )
        self._last_judge = judge
        self.answered += 1
        if judge.correct:
            self.correct += 1
            self.effects.emit(EffectEvent.ANSWER_CORRECT, hinted=self._hinted)
        else:
            self.effects.emit(EffectEvent.ANSWER_INCORRECT, hinted=self._hinted)
        self.context.repo.add_training_log(
            self.entry.word_key,
            self.kind,
            correct=judge.correct,
            hinted=self._hinted,
            duration_ms=int((time.monotonic() - self._started) * 1000),
            error_type=judge.error_type,
            detail={"answer": answer, "expected": self.entry.headword},
        )
        if not judge.correct:
            self.context.repo.add_word_error(
                self.entry.word_key,
                self.kind,
                judge.error_type or "wrong_answer",
                judge.message,
            )
        elif self.kind in {"spelling", "recall"}:
            self.context.repo.resolve_errors(self.entry.word_key, self.kind)
        self.mode = "feedback"
        self._answer.can_focus = False
        self._answer.display = False
        self.set_focus(None)
        lines = [
            Text("正确" if judge.correct else "错误", style="bold green" if judge.correct else "bold red"),
            Text(f"参考答案: {self.entry.headword}", style="bold"),
        ]
        if judge.message:
            lines.append(Text(judge.message, style="yellow"))
        self.query_one("#feedback", Static).update(Text("\n").join(lines))
        self.query_one("#footer", Static).update(Text("[Enter] 下一题   [Ctrl+Q] 退出", style="dim"))

    def on_key(self, event) -> None:
        if self.mode == "feedback" and event.key in {"enter", "space"}:
            self.index += 1
            self._present_word()
            event.stop()
        elif self.mode == "summary" and event.key in {"enter", "space", "q", "escape"}:
            self.exit(self._result())
            event.stop()

    def _present_summary(self) -> None:
        self.mode = "summary"
        self.query_one("#hud", Static).update(Text("DRILL COMPLETE", style="bold"))
        self.query_one("#prompt", Static).update(Text(f"{self.correct}/{self.answered} 正确", style="bold"))
        self.query_one("#meta", Static).update(Text(""))
        self.query_one("#answer", PowerInput).display = False
        self.query_one("#feedback", Static).update(Text("训练结果已保存", style="dim"))
        self.query_one("#footer", Static).update(Text("[Enter] 结束", style="dim"))
        self.effects.emit(EffectEvent.SESSION_COMPLETED)

    def _finish_empty(self) -> None:
        self.mode = "summary"
        self.query_one("#prompt", Static).update(Text("没有可训练的词", style="yellow"))
        self.query_one("#footer", Static).update(Text("[Enter] 结束", style="dim"))
        self.set_timer(0.05, lambda: self.exit(self._result()))

    def _result(self) -> dict:
        return {"answered": self.answered, "correct": self.correct, "quit": False}

    def action_hint(self) -> None:
        if self.mode != "typing" or self.entry is None:
            return
        self._hinted = True
        self.notify_message(f"提示: 首字母 {self.entry.headword[:1]}，共 {len(self.entry.headword)} 个字母")

    def action_audio(self) -> None:
        if self.entry is None:
            return
        self._hinted = True
        self._play_audio(self.entry.headword)

    @work(thread=True, exclusive=False)
    def _play_audio(self, text: str) -> None:
        result = self.context.audio.speak(text)
        if not result.ok:
            self.call_from_thread(self.notify_message, f"音频不可用: {result.message}")

    def notify_message(self, message: str, style: str = "info") -> None:
        palette = {"info": "cyan", "success": "green", "warning": "yellow", "error": "bold red"}
        self.query_one("#notice", Static).update(Text(message, style=palette.get(style, "cyan")))

    def _effect_sink(self, event: EffectEvent, payload: dict, state: EffectsState) -> None:
        if threading.get_ident() == self._ui_thread:
            self._apply_effect(event, payload, state)
        else:
            try:
                self.call_from_thread(self._apply_effect, event, payload, state)
            except RuntimeError:
                pass

    def _apply_effect(self, event: EffectEvent, payload: dict, state: EffectsState) -> None:
        if not self.effects.runtime.enabled:
            return
        if event == EffectEvent.ANSWER_CORRECT:
            self._pulse("green")
            self._canvas.burst(color="bright_green")
            self._combo.show(state.combo)
        elif event == EffectEvent.ANSWER_INCORRECT:
            self._shake()
            self._pulse("red")
            self._canvas.burst(color="bright_red")
            self._combo.reset()
        elif event == EffectEvent.COMBO_INCREASED:
            self._combo.show(payload.get("combo", state.combo), milestone=True)

    def _pulse(self, color: str) -> None:
        target = self._answer if self._answer.display else self.query_one("#prompt", Static)
        target.styles.border = ("round", color)
        self.set_timer(0.28, lambda: setattr(target.styles, "border", ("round", "cyan")))

    def _shake(self) -> None:
        target = self._answer if self._answer.display else self.query_one("#prompt", Static)
        for delay_ms, offset in shake_offsets():
            self.set_timer(
                max(0.02, delay_ms / 1000),
                lambda value=offset: setattr(target.styles, "offset", (value, 0)),
            )

    def action_toggle_effects(self) -> None:
        enabled = self.effects.toggle()
        self._canvas.clear()
        self._combo.reset()
        self.notify_message("特效已开启" if enabled else "特效已关闭")

    def action_save_quit(self) -> None:
        self.exit(self._result())

    def action_back(self) -> None:
        self.exit(self._result())


def run_textual_drill(context: AppContext, kind: str, count: int) -> dict | None:
    app = LexiLabDrillApp(context, kind, count)
    app.run()
    return app.return_value if isinstance(app.return_value, dict) else None
