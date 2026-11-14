from __future__ import annotations

import threading

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Input, LoadingIndicator, Static

from lexilab.context import AppContext
from lexilab.ui.effects.engine import EffectEvent, EffectsEngine, EffectsState
from lexilab.ui.effects.presets import preset_for
from lexilab.ui.textual_widgets import ParticleCanvas, PowerInput

CSS = """
Screen { background: $surface; color: $text; }
#logo { height: 3; content-align: center middle; text-style: bold; color: $accent; }
#status { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
#article { height: 12; margin: 1 2; border: round $accent; padding: 0 1; }
#question { height: auto; padding: 1 2; text-style: bold; }
#answer { margin: 1 3; border: round $accent; }
#particles { height: 3; padding: 0 1; }
#feedback { height: auto; padding: 1 2; }
#notice { height: 1; padding: 0 2; color: $warning; }
#footer { height: 1; dock: bottom; padding: 0 1; background: $panel; color: $text-muted; }
"""


class LexiLabReadingApp(App):
    ENABLE_COMMAND_PALETTE = True
    CSS = CSS
    BINDINGS = [
        Binding("ctrl+q", "save_quit", "退出", priority=True),
        Binding("ctrl+t", "toggle_effects", "切换特效", priority=True),
        Binding("ctrl+p", "command_palette", "命令面板", priority=True),
        Binding("escape", "back", "返回", priority=True),
        Binding("pageup", "scroll_up", "上翻", priority=True),
        Binding("pagedown", "scroll_down", "下翻", priority=True),
    ]

    def __init__(self, context: AppContext, *, topic, difficulty, force_new, words):
        super().__init__()
        self.context = context
        self.topic = topic
        self.difficulty = difficulty
        self.force_new = force_new
        self.words = words
        self.runtime = preset_for(context.settings)
        self.effects = EffectsEngine(self.runtime, sink=self._effect_sink)
        self._ui_thread = 0
        self.mode = "loading"
        self.material: dict | None = None
        self.question_index = 0
        self.answers: list[str] = []
        self.grades: list[dict] = []
        self._hinted = False
        self.result: dict | None = None
        self._manual = False

    def compose(self) -> ComposeResult:
        self._canvas = ParticleCanvas(self.effects, id="particles")
        self._article = Static("", id="article")
        self._question = Static("", id="question")
        self._answer = PowerInput(self._canvas, self.effects, id="answer", placeholder="输入答案…")
        yield Static("LexiLab · Reading", id="logo")
        yield Static("AI 正在生成阅读材料…", id="status")
        yield LoadingIndicator(id="loading")
        yield VerticalScroll(self._article, id="article-scroll")
        yield self._question
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
        self.query_one("#loading", LoadingIndicator).display = True
        self._generate_task()

    @work(thread=True, exclusive=True)
    def _generate_task(self) -> None:
        try:
            result = self.context.materials.get_reading(
                topic=self.topic,
                difficulty=self.difficulty,
                target_words=self.words,
                force_new=self.force_new,
            )
        except Exception as exc:
            self.call_from_thread(self._error, str(exc))
            return
        self.call_from_thread(self._show_material, result)

    def _show_material(self, result) -> None:
        self.material = result.material
        self.mode = "question"
        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#status", Static).update(
            Text(f"READING  |  {self.material['topic']}  |  {result.meta.label}", style="bold")
        )
        self._article.update(Text(self.material["body"]))
        self.query_one("#footer", Static).update(
            Text(
                "目标词: " + ", ".join(self.material["target_words"])
                + "   [PageUp/PageDown] 滚动   [Ctrl+Q] 退出",
                style="dim",
            )
        )
        self._ask_question()

    def _ask_question(self) -> None:
        if self.material is None:
            return
        questions = self.material["questions"]
        if self.question_index >= len(questions):
            self._start_grading()
            return
        q = questions[self.question_index]
        self.mode = "question"
        self.query_one("#question", Static).update(
            Text(f"Question {self.question_index + 1}/{len(questions)}\n{q.get('question', '')}")
        )
        self.query_one("#feedback", Static).update(Text(""))
        self._answer.display = True
        self._answer.disabled = False
        self._answer.can_focus = True
        self._answer.reset_text()
        self._answer.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.mode != "question":
            return
        answer = event.value.strip()
        if not answer:
            self.notify_message("答案为空")
            return
        self.answers.append(answer)
        self.question_index += 1
        self._answer.can_focus = False
        self._answer.display = False
        self.set_focus(None)
        self._ask_question()

    def _start_grading(self) -> None:
        assert self.material is not None
        self.mode = "grading"
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#status", Static).update(Text("AI 正在批改阅读理解…", style="bold"))
        self.query_one("#question", Static).update(Text(""))
        self._grade_task(self.answers)

    @work(thread=True, exclusive=True)
    def _grade_task(self, answers: list[str]) -> None:
        assert self.material is not None
        try:
            grades, meta = self.context.materials.grade_reading(
                self.material["id"], answers, hinted=self._hinted
            )
        except Exception as exc:
            self.call_from_thread(self._error, str(exc))
            return
        self.call_from_thread(self._show_grades, grades, meta)

    def _show_grades(self, grades, meta) -> None:
        self.grades = grades
        self.mode = "feedback"
        self.query_one("#loading", LoadingIndicator).display = False
        understood = sum(1 for grade in grades if grade.get("understood"))
        self.query_one("#status", Static).update(
            Text(f"FEEDBACK  |  {understood}/{len(grades)} 理解正确  |  {meta.label}", style="bold")
        )
        lines = []
        for index, grade in enumerate(grades, 1):
            lines.append(
                Text(
                    f"Q{index}: " + ("理解正确" if grade.get("understood") else "未完全理解"),
                    style="bold green" if grade.get("understood") else "bold yellow",
                )
            )
            if grade.get("missing"):
                lines.append(Text("遗漏: " + "；".join(grade["missing"]), style="dim"))
            if grade.get("misunderstanding"):
                lines.append(Text("误解: " + "；".join(grade["misunderstanding"]), style="yellow"))
            if grade.get("explanation"):
                lines.append(Text(grade["explanation"]))
            if grade.get("reference_answer"):
                lines.append(Text("参考: " + grade["reference_answer"], style="dim"))
        self.query_one("#feedback", Static).update(Text("\n").join(lines))
        self.query_one("#footer", Static).update(
            Text("[O] 标记为可接受（人工纠正）   [Enter] 结束", style="dim")
        )
        if understood >= max(1, len(grades) // 2):
            self.effects.emit(EffectEvent.ANSWER_CORRECT, hinted=self._hinted, reading=True)
        else:
            self.effects.emit(EffectEvent.ANSWER_INCORRECT, hinted=self._hinted, reading=True)

    def _error(self, message: str) -> None:
        self.mode = "error"
        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#status", Static).update(Text("AI 请求失败", style="bold red"))
        self.query_one("#feedback", Static).update(Text(message, style="red"))
        self.query_one("#footer", Static).update(Text("[Enter/Esc] 返回", style="dim"))

    def on_key(self, event) -> None:
        if self.mode == "error" and event.key in {"enter", "escape"}:
            self.exit(None)
            event.stop()
        elif self.mode == "feedback":
            if event.key == "o":
                self._manual_override()
            elif event.key == "enter":
                self.result = {
                    "material_id": self.material["id"] if self.material else "",
                    "answered": len(self.answers),
                    "manual_override": self._manual,
                }
                self.exit(self.result)
            event.stop()

    def _manual_override(self) -> None:
        if self.material is None or self._manual:
            return
        for target in self.material["target_words"]:
            self.context.repo.add_training_log(
                target,
                "context",
                correct=True,
                detail={"manual_override": True, "material_id": self.material["id"]},
                material_id=self.material["id"],
            )
            self.context.repo.resolve_errors(target, "context")
        self._manual = True
        self.notify_message("已保存人工判断", "success")

    def action_scroll_up(self) -> None:
        self.query_one("#article-scroll", VerticalScroll).scroll_up(animate=False)

    def action_scroll_down(self) -> None:
        self.query_one("#article-scroll", VerticalScroll).scroll_down(animate=False)

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
        if event == EffectEvent.ANSWER_CORRECT:
            self._canvas.burst(color="bright_green")
            self._article.styles.border = ("round", "green")
            self.set_timer(0.3, lambda: setattr(self._article.styles, "border", ("round", "cyan")))
        elif event == EffectEvent.ANSWER_INCORRECT:
            self._canvas.burst(color="bright_red")
            self._article.styles.border = ("round", "red")
            self.set_timer(0.3, lambda: setattr(self._article.styles, "border", ("round", "cyan")))


def run_textual_reading(
    context: AppContext, *, topic, difficulty, force_new, words
) -> dict | None:
    app = LexiLabReadingApp(
        context, topic=topic, difficulty=difficulty, force_new=force_new, words=words
    )
    app.run()
    return app.return_value if isinstance(app.return_value, dict) else None
