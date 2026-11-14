from __future__ import annotations

import threading
import time

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, LoadingIndicator, Static

from lexilab.context import AppContext
from lexilab.training.judge import judge_listening
from lexilab.ui.effects.engine import EffectEvent, EffectsEngine, EffectsState
from lexilab.ui.effects.presets import preset_for
from lexilab.ui.textual_widgets import ParticleCanvas, PowerInput
from lexilab.vocabulary.normalize import contains_word

CSS = """
Screen { background: $surface; color: $text; }
#logo { height: 3; content-align: center middle; text-style: bold; color: $accent; }
#status { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
#sentence { height: auto; content-align: center middle; padding: 1 2; }
#answer { margin: 1 3; border: round $accent; }
#particles { height: 3; padding: 0 1; }
#feedback { height: auto; padding: 1 2; }
#notice { height: 1; padding: 0 2; color: $warning; }
#footer { height: 1; dock: bottom; padding: 0 1; background: $panel; color: $text-muted; }
"""


class LexiLabListeningApp(App):
    ENABLE_COMMAND_PALETTE = True
    CSS = CSS
    BINDINGS = [
        Binding("ctrl+q", "save_quit", "退出", priority=True),
        Binding("ctrl+t", "toggle_effects", "切换特效", priority=True),
        Binding("ctrl+p", "command_palette", "命令面板", priority=True),
        Binding("escape", "back", "返回", priority=True),
        Binding("f1", "hint", "提示", priority=True),
        Binding("f2", "play", "播放", priority=True),
        Binding("f3", "replay", "重播", priority=True),
    ]

    def __init__(self, context: AppContext, *, topic, difficulty, count, force_new, words):
        super().__init__()
        self.context = context
        self.topic = topic
        self.difficulty = difficulty
        self.count = count
        self.force_new = force_new
        self.words = words
        self.runtime = preset_for(context.settings)
        self.effects = EffectsEngine(self.runtime, sink=self._effect_sink)
        self._ui_thread = 0
        self.mode = "loading"
        self.material: dict | None = None
        self.index = 0
        self.correct = 0
        self.answered = 0
        self.index_started = 0.0
        self.plays = 0
        self.replays = 0
        self._hinted = False
        self.result: dict | None = None

    def compose(self) -> ComposeResult:
        self._canvas = ParticleCanvas(self.effects, id="particles")
        self._answer = PowerInput(self._canvas, self.effects, id="answer", placeholder="输入你听到的内容…")
        yield Static("LexiLab · Listening", id="logo")
        yield Static("AI 正在生成听力材料…", id="status")
        yield LoadingIndicator(id="loading")
        yield Static("", id="sentence")
        yield self._answer
        yield self._canvas
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
        self._generate_task()

    @work(thread=True, exclusive=True)
    def _generate_task(self) -> None:
        try:
            result = self.context.materials.get_listening(
                topic=self.topic,
                difficulty=self.difficulty,
                target_words=self.words,
                count=self.count,
                force_new=self.force_new,
            )
        except Exception as exc:
            self.call_from_thread(self._error, str(exc))
            return
        self.call_from_thread(self._show_material, result)

    def _show_material(self, result) -> None:
        self.material = result.material
        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#status", Static).update(
            Text(f"LISTENING  |  {self.material['topic']}  |  {result.meta.label}", style="bold")
        )
        self._next_sentence()

    def _next_sentence(self) -> None:
        if self.material is None:
            return
        if self.index >= len(self.material["questions"]):
            self._summary()
            return
        self.mode = "listening"
        self._hinted = False
        self.plays = 0
        self.replays = 0
        self.index_started = time.monotonic()
        self.query_one("#sentence", Static).update(
            Text(f"Sentence {self.index + 1}/{len(self.material['questions'])}\n[F2] 播放   [F3] 重播", justify="center")
        )
        self.query_one("#feedback", Static).update(Text(""))
        self._answer.display = True
        self._answer.disabled = False
        self._answer.can_focus = True
        self._answer.reset_text()
        self._answer.focus()
        self.query_one("#footer", Static).update(
            Text(
                "[Enter] 提交   [F1] 提示   [F2] 播放   [F3] 重播   [Ctrl+Q] 退出",
                style="dim",
            )
        )
        self.action_play()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.mode != "listening" or self.material is None:
            return
        answer = event.value.strip()
        if not answer:
            self.notify_message("答案为空")
            return
        item = self.material["questions"][self.index]
        expected = item["answer"]
        judge = judge_listening(answer, expected)
        self.answered += 1
        if judge.correct:
            self.correct += 1
            self.effects.emit(EffectEvent.ANSWER_CORRECT, hinted=self._hinted)
        else:
            self.effects.emit(EffectEvent.ANSWER_INCORRECT, hinted=self._hinted)
        self.mode = "feedback"
        self._answer.can_focus = False
        self._answer.display = False
        self.set_focus(None)
        self.query_one("#feedback", Static).update(
            Text(
                ("正确" if judge.correct else "需要复习")
                + "\n原文: "
                + expected
                + (("\n翻译: " + item.get("translation", "")) if item.get("translation") else ""),
                style="bold green" if judge.correct else "bold red",
            )
        )
        self.context.repo.record_material_attempt(
            self.material["id"],
            self.index,
            answer,
            {
                "expected": expected,
                "correct": bool(judge.correct),
                "plays": self.plays,
                "replays": self.replays,
                "hinted": self._hinted,
            },
            bool(judge.correct),
            hinted=self._hinted,
        )
        involved = [
            target
            for target in self.material["target_words"]
            if contains_word(expected, target, self.context.vocab.forms_for(target))
        ] or self.material["target_words"][:1]
        for target in involved:
            self.context.repo.add_training_log(
                target,
                "listening",
                correct=judge.correct,
                hinted=self._hinted or self.plays > 1,
                duration_ms=int((time.monotonic() - self.index_started) * 1000),
                error_type=None if judge.correct else "dictation_error",
                detail={
                    "material_id": self.material["id"],
                    "sentence": self.index + 1,
                    "plays": self.plays,
                    "replays": self.replays,
                    "answer": answer,
                    "expected": expected,
                },
                material_id=self.material["id"],
            )
            if not judge.correct:
                self.context.repo.add_word_error(target, "listening", "dictation_error", "听写错误")
        self.query_one("#footer", Static).update(Text("[Enter] 下一句   [Ctrl+Q] 退出", style="dim"))

    def on_key(self, event) -> None:
        if self.mode == "feedback" and event.key in {"enter", "space"}:
            self.index += 1
            self._next_sentence()
            event.stop()
        elif self.mode in {"summary", "error"} and event.key in {"enter", "escape", "q"}:
            self.exit(self.result)
            event.stop()

    def _summary(self) -> None:
        if self.material is None:
            return
        self.mode = "summary"
        self.context.repo.mark_material_used(self.material["id"])
        self.query_one("#sentence", Static).update(
            Text(f"听力完成: {self.correct}/{self.answered} 正确", style="bold")
        )
        self.query_one("#answer", PowerInput).display = False
        self.query_one("#feedback", Static).update(Text("结果已保存", style="dim"))
        self.query_one("#footer", Static).update(Text("[Enter] 结束", style="dim"))
        self.result = {
            "material_id": self.material["id"],
            "answered": self.answered,
            "correct": self.correct,
        }
        self.effects.emit(EffectEvent.SESSION_COMPLETED)

    def action_play(self) -> None:
        self._play_current(replay=False)

    def action_replay(self) -> None:
        self._play_current(replay=True)

    def _play_current(self, *, replay: bool) -> None:
        if self.material is None or self.mode != "listening":
            return
        expected = self.material["questions"][self.index]["answer"]
        self._play_audio(expected, replay=replay)

    @work(thread=True, exclusive=False)
    def _play_audio(self, text: str, *, replay: bool) -> None:
        result = self.context.audio.speak(text)
        if result.ok:
            self.call_from_thread(self._count_play, replay)
        else:
            self.call_from_thread(self.notify_message, f"音频不可用: {result.message}", "warning")

    def _count_play(self, replay: bool) -> None:
        self.plays += 1
        if replay:
            self.replays += 1

    def action_hint(self) -> None:
        if self.material is None or self.mode != "listening":
            return
        self._hinted = True
        translation = self.material["questions"][self.index].get("translation", "")
        self.notify_message("提示: " + (translation or "注意目标词"), "warning")

    def _error(self, message: str) -> None:
        self.mode = "error"
        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#status", Static).update(Text("AI 请求失败", style="bold red"))
        self.query_one("#feedback", Static).update(Text(message, style="red"))
        self.query_one("#footer", Static).update(Text("[Enter] 返回", style="dim"))

    def action_toggle_effects(self) -> None:
        enabled = self.effects.toggle()
        self._canvas.clear()
        self.notify_message("特效已开启" if enabled else "特效已关闭")

    def action_save_quit(self) -> None:
        self.exit(None)

    def action_back(self) -> None:
        self.exit(None)

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

    def _apply_effect(self, event, payload, state) -> None:
        if not self.effects.runtime.enabled:
            return
        target = self.query_one("#sentence", Static)
        if event == EffectEvent.ANSWER_CORRECT:
            self._canvas.burst(color="bright_green")
            target.styles.border = ("round", "green")
            self.set_timer(0.3, lambda: setattr(target.styles, "border", ("round", "cyan")))
        elif event == EffectEvent.ANSWER_INCORRECT:
            self._canvas.burst(color="bright_red")
            target.styles.border = ("round", "red")
            self.set_timer(0.3, lambda: setattr(target.styles, "border", ("round", "cyan")))


def run_textual_listening(
    context: AppContext, *, topic, difficulty, count, force_new, words
) -> dict | None:
    app = LexiLabListeningApp(
        context,
        topic=topic,
        difficulty=difficulty,
        count=count,
        force_new=force_new,
        words=words,
    )
    app.run()
    return app.return_value if isinstance(app.return_value, dict) else None
