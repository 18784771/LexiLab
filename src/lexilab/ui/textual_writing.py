from __future__ import annotations

import threading

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import LoadingIndicator, Static

from lexilab.ai.base import AIError
from lexilab.context import AppContext
from lexilab.ui.effects.engine import EffectEvent, EffectsEngine, EffectsState
from lexilab.ui.effects.presets import preset_for
from lexilab.ui.textual_widgets import ParticleCanvas, PowerTextArea

CSS = """
Screen { background: $surface; color: $text; }
#logo { height: 3; content-align: center middle; text-style: bold; color: $accent; }
#status { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
#prompt { height: auto; padding: 1 2; }
#meta { height: 1; padding: 0 2; color: $text-muted; }
#writing { height: 10; margin: 1 2; border: round $accent; }
#loading { height: 3; }
#particles { height: 3; padding: 0 1; }
#feedback { height: auto; padding: 1 2; }
#notice { height: 1; padding: 0 2; color: $warning; }
#footer { height: 1; dock: bottom; padding: 0 1; background: $panel; color: $text-muted; }
"""


class LexiLabWritingApp(App):
    ENABLE_COMMAND_PALETTE = True
    CSS = CSS
    BINDINGS = [
        Binding("ctrl+q", "save_quit", "保存退出", priority=True),
        Binding("ctrl+t", "toggle_effects", "切换特效", priority=True),
        Binding("ctrl+p", "command_palette", "命令面板", priority=True),
        Binding("ctrl+enter", "submit_writing", "提交写作", priority=True),
        Binding("escape", "back", "返回", priority=True),
        Binding("f1", "skip_animation", "立即显示", priority=True),
    ]

    def __init__(
        self,
        context: AppContext,
        *,
        level: int,
        topic: str | None,
        force_new: bool,
        words: list[str] | None,
    ) -> None:
        super().__init__()
        self.context = context
        self.level = level
        self.topic = topic
        self.force_new = force_new
        self.words = words
        self.runtime = preset_for(context.settings)
        self.effects = EffectsEngine(self.runtime, sink=self._effect_sink)
        self._ui_thread = 0
        self._mode = "loading"
        self.material: dict | None = None
        self.grade = None
        self._manual_override = False
        self._answer = ""
        self.result: dict | None = None

    def compose(self) -> ComposeResult:
        self._canvas = ParticleCanvas(self.effects, id="particles")
        self._textarea = PowerTextArea(
            self._canvas,
            self.effects,
            id="writing",
            placeholder="输入英文写作内容… Ctrl+Enter 提交",
        )
        self._textarea.display = False
        self._textarea.can_focus = False
        yield Static("LexiLab · Writing", id="logo")
        yield Static("AI 正在生成写作题目…", id="status")
        yield LoadingIndicator(id="loading")
        yield Static("", id="prompt")
        yield Static("", id="meta")
        yield self._textarea
        yield self._canvas
        yield Static("", id="feedback")
        yield Static("", id="notice")
        yield Static("", id="footer")

    def on_mount(self) -> None:
        self._ui_thread = threading.get_ident()
        self._generate_task()

    @work(thread=True, exclusive=True)
    def _generate_task(self) -> None:
        try:
            result = self.context.materials.get_writing(
                level=self.level,
                topic=self.topic,
                target_words=self.words,
                force_new=self.force_new,
            )
        except Exception as exc:
            self.call_from_thread(self._show_error, str(exc))
            return
        self.call_from_thread(self._show_material, result)

    def _show_material(self, result) -> None:
        self.material = result.material
        self._mode = "writing"
        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#status", Static).update(
            Text(f"WRITING LEVEL {self.level}  |  {result.meta.label}", style="bold")
        )
        guidance = (self.material.get("meta") or {}).get("guidance") or ""
        self.query_one("#prompt", Static).update(Text(self.material["body"], style="bold"))
        self.query_one("#meta", Static).update(
            Text(
                ("目标词: " + ", ".join(self.material["target_words"]) + "   " if self.material["target_words"] else "")
                + guidance,
                style="dim",
            )
        )
        self._textarea.display = True
        self._textarea.can_focus = True
        self._textarea.reset_text()
        self._textarea.focus()
        self.query_one("#footer", Static).update(
            Text(
                "[Ctrl+Enter] 提交   [Ctrl+T] 特效   [Esc] 返回   [Ctrl+Q] 退出",
                style="dim",
            )
        )
        self.effects.emit(EffectEvent.AI_GENERATING, phase="done")

    def _show_error(self, message: str) -> None:
        self._mode = "error"
        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#status", Static).update(Text("AI 请求失败", style="bold red"))
        self.query_one("#feedback", Static).update(Text(message, style="red"))
        self.query_one("#footer", Static).update(Text("[Enter/Esc] 返回", style="dim"))

    def action_submit_writing(self) -> None:
        if self._mode != "writing":
            return
        answer = self._textarea.text.strip()
        if not answer:
            self.notify_message("写作内容为空", "warning")
            return
        self._answer = answer
        self._mode = "grading"
        self._textarea.can_focus = False
        self._textarea.display = False
        self.query_one("#loading", LoadingIndicator).display = True
        self.query_one("#status", Static).update(Text("AI 正在批改…", style="bold"))
        self.effects.emit(EffectEvent.AI_GENERATING, phase="grading")
        self._grade_task(answer)

    @work(thread=True, exclusive=True)
    def _grade_task(self, answer: str) -> None:
        assert self.material is not None
        try:
            grade, meta = self.context.materials.grade_writing(self.material["id"], answer)
        except AIError as exc:
            self.call_from_thread(self._show_error, str(exc))
            return
        self.call_from_thread(self._show_grade, grade, meta)

    def _show_grade(self, grade, meta) -> None:
        self.grade = grade
        self._mode = "feedback"
        self.query_one("#loading", LoadingIndicator).display = False
        self.query_one("#status", Static).update(Text(f"FEEDBACK  |  {meta.label}", style="bold"))
        self.query_one("#prompt", Static).update(Text(""))
        self.query_one("#meta", Static).update(Text(""))
        lines = [
            Text(
                ("任务完成" if grade.task_completed else "任务未完成") + f"   score={grade.score:.0%}",
                style="bold",
            )
        ]
        for issue in grade.issues:
            if issue.category == "style":
                lines.append(Text(f"[风格建议] {issue.explanation}", style="yellow"))
            else:
                lines.append(Text(f"[{issue.category}] {issue.excerpt}  {issue.explanation}", style="red"))
                if issue.correction:
                    lines.append(Text(f"  修改: {issue.correction}", style="green"))
        for item in grade.target_words:
            status = "使用正确" if item.used and item.meaning_correct and item.collocation_correct else "需要强化"
            lines.append(Text(f"{item.target_word}: {status}  {item.feedback}", style="dim"))
        if grade.minimal_correction:
            lines.append(Text("最小修改: " + grade.minimal_correction, style="green"))
        if grade.overall_comment:
            lines.append(Text(grade.overall_comment, style="dim"))
        self.query_one("#feedback", Static).update(Text("\n").join(lines))
        self.query_one("#footer", Static).update(
            Text("[O] 标记为可接受（人工纠正）   [Enter] 结束", style="dim")
        )
        if grade.task_completed and grade.score >= 0.6:
            self.effects.emit(EffectEvent.ANSWER_CORRECT, hinted=False, writing=True)
        else:
            self.effects.emit(EffectEvent.ANSWER_INCORRECT, hinted=False, writing=True)

    def on_key(self, event) -> None:
        if self._mode == "error" and event.key in {"enter", "escape"}:
            self.exit(None)
            event.stop()
            return
        if self._mode == "feedback":
            if event.key == "o":
                self._apply_manual_override()
            elif event.key == "enter":
                self.result = {
                    "material_id": self.material["id"] if self.material else "",
                    "submitted": True,
                    "score": self.grade.score if self.grade else 0,
                    "manual_override": self._manual_override,
                }
                self.exit(self.result)
            event.stop()
            return

    def _apply_manual_override(self) -> None:
        if self.material is None or self._manual_override:
            return
        for target in self.material["target_words"]:
            self.context.repo.add_training_log(
                target,
                "production",
                correct=True,
                detail={
                    "manual_override": True,
                    "material_id": self.material["id"],
                    "raw_answer": self._answer[:200],
                },
                material_id=self.material["id"],
            )
            self.context.repo.resolve_errors(target, "production")
        self._manual_override = True
        self.notify_message("已保存人工判断", "success")

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
        if event in {EffectEvent.ANSWER_CORRECT, EffectEvent.ANSWER_INCORRECT}:
            color = "green" if event == EffectEvent.ANSWER_CORRECT else "red"
            target = self._textarea
            target.styles.border = ("round", color)
            self.set_timer(0.28, lambda: setattr(target.styles, "border", ("round", "cyan")))
            self._canvas.burst(color="bright_green" if color == "green" else "bright_red")

    def action_toggle_effects(self) -> None:
        enabled = self.effects.toggle()
        self._canvas.clear()
        self.notify_message("特效已开启" if enabled else "特效已关闭", "info")

    def action_save_quit(self) -> None:
        self.exit(None)

    def action_back(self) -> None:
        self.exit(None)

    def action_skip_animation(self) -> None:
        self.notify_message("已立即显示当前内容", "info")

    def notify_message(self, message: str, style: str = "info") -> None:
        palette = {"info": "cyan", "success": "green", "warning": "yellow", "error": "bold red"}
        self.query_one("#notice", Static).update(Text(message, style=palette.get(style, "cyan")))


def run_textual_writing(
    context: AppContext,
    *,
    level: int,
    topic: str | None,
    force_new: bool,
    words: list[str] | None,
) -> dict | None:
    app = LexiLabWritingApp(
        context, level=level, topic=topic, force_new=force_new, words=words
    )
    app.run()
    return app.return_value if isinstance(app.return_value, dict) else None
