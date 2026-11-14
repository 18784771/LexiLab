from __future__ import annotations

import threading
from typing import Callable

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, Static
from textual.widgets.option_list import Option
from textual.widgets import OptionList

from lexilab.context import AppContext
from lexilab.learning.session import LearningSession, SessionResult
from lexilab.models.word import WordEntry
from lexilab.ui.base import FeedbackView, ProductionPrompt, RatingResult, SessionUI
from lexilab.ui.effects.engine import EffectEvent, EffectsEngine, EffectsState
from lexilab.ui.effects.presets import EffectsRuntime, preset_for
from lexilab.ui.effects.shake import shake_offsets
from lexilab.ui.effects.transitions import TTEAdapter
from lexilab.ui.textual_widgets import ComboBadge, ParticleCanvas, PowerInput

CSS = """
Screen {
    background: $surface;
    color: $text;
}
#logo {
    height: 3;
    content-align: center middle;
    text-style: bold;
    color: $accent;
}
#hud {
    height: 1;
    padding: 0 1;
    background: $panel;
    color: $text-muted;
}
#word {
    height: auto;
    min-height: 4;
    content-align: center middle;
    text-style: bold;
}
#meta {
    height: auto;
    content-align: center middle;
    color: $text-muted;
}
#prompt {
    height: auto;
    content-align: center middle;
}
#answer {
    margin: 1 4;
    border: round $accent;
}
#particles {
    height: 3;
    padding: 0 1;
}
#combo {
    height: 1;
    content-align: center middle;
}
#feedback {
    height: auto;
    margin: 1 3;
}
#notice {
    height: 1;
    padding: 0 1;
    color: $warning;
}
#footer {
    height: 1;
    dock: bottom;
    padding: 0 1;
    background: $panel;
    color: $text-muted;
}
#stats {
    height: auto;
    padding: 1 2;
}
#menu {
    height: auto;
    margin: 1 2;
}
#menu-hint {
    height: 1;
    padding: 0 2;
    color: $text-muted;
}
"""


class TextualSessionUI(SessionUI):
    """Bridge the synchronous LearningSession to the Textual event loop.

    The learning session runs in a worker thread. Each UI call posts a presenter
    to the Textual thread and waits on an event; the UI thread stays responsive
    for animation, command palette and Ctrl+Q.
    """

    def __init__(self, app: "LexiLabSessionApp") -> None:
        self.app = app
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._result = None
        self._quit_value = None
        self._waiting = False

    def _ask(self, presenter: Callable, quit_value, *args):
        with self._lock:
            self._event.clear()
            self._result = quit_value
            self._quit_value = quit_value
            self._waiting = True
        try:
            self.app.call_from_thread(presenter, *args, self._deliver)
        except RuntimeError:
            with self._lock:
                self._waiting = False
            return quit_value
        self._event.wait()
        with self._lock:
            self._waiting = False
            return self._result

    def _deliver(self, value) -> None:
        with self._lock:
            self._result = value
            self._event.set()

    def cancel(self) -> None:
        with self._lock:
            if self._waiting:
                self._result = self._quit_value
                self._event.set()

    def notify(self, message: str, style: str = "info") -> None:
        try:
            self.app.call_from_thread(self.app.notify_message, message, style)
        except RuntimeError:
            pass

    def ask_new_word(self, entry: WordEntry, position: str) -> int:
        return self._ask(self.app.present_new_word, 0, entry, position)

    def show_word_info(self, entry: WordEntry) -> bool:
        return bool(self._ask(self.app.present_word_info, False, entry))

    def ask_recognition(self, entry: WordEntry, position: str, *, mode: str = "review") -> RatingResult:
        return self._ask(self.app.present_recognition, RatingResult(quit=True), entry, position, mode)

    def ask_production(
        self, entry: WordEntry, prompt: ProductionPrompt, position: str
    ) -> RatingResult:
        return self._ask(self.app.present_production, RatingResult(quit=True), entry, prompt, position)

    def show_feedback(self, feedback: FeedbackView) -> int | None:
        return self._ask(self.app.present_feedback, None, feedback)

    def ask_reinforcement(self, entry: WordEntry, position: str) -> bool | None:
        return self._ask(self.app.present_reinforcement, None, entry, position)

    def show_summary(self, summary: dict) -> None:
        self._ask(self.app.present_summary, None, summary)


class LexiLabSessionApp(App):
    ENABLE_COMMAND_PALETTE = True
    CSS = CSS
    BINDINGS = [
        Binding("ctrl+q", "save_quit", "保存退出", priority=True),
        Binding("ctrl+t", "toggle_effects", "切换特效", priority=True),
        Binding("ctrl+p", "command_palette", "命令面板", priority=True),
        Binding("escape", "cancel", "返回/取消", priority=True),
        Binding("f1", "hint", "提示", priority=True),
        Binding("f2", "audio", "发音", priority=True),
    ]

    def __init__(self, context: AppContext, session_id: str, runtime: EffectsRuntime | None = None) -> None:
        super().__init__()
        self.context = context
        self.session_id = session_id
        self.runtime = runtime or preset_for(context.settings)
        self.effects = EffectsEngine(self.runtime, sink=self._effect_sink_safe)
        self._ui_thread = 0
        self._mode = "idle"
        self._stage = "front"
        self._entry: WordEntry | None = None
        self._position = ""
        self._started = 0.0
        self._hinted = False
        self._callback: Callable | None = None
        self._quit_value = None
        self._tte_animator: TTEAdapter | None = None
        self._answer_value = ""
        self._summary: dict = {}

    def compose(self) -> ComposeResult:
        self._canvas = ParticleCanvas(self.effects, id="particles")
        self._combo = ComboBadge(id="combo")
        self._answer_widget = PowerInput(self._canvas, self.effects, id="answer", placeholder="输入答案…", disabled=True)
        self._answer_widget.can_focus = False
        self._answer_widget.display = False
        yield Static("LexiLab", id="logo")
        yield Static("", id="hud")
        yield Static("", id="word")
        yield Static("", id="meta")
        yield Static("", id="prompt")
        yield self._answer_widget
        yield self._canvas
        yield self._combo
        yield Static("", id="feedback")
        yield Static("", id="notice")
        yield Static("", id="footer")

    def on_mount(self) -> None:
        self._ui_thread = threading.get_ident()
        self._session_ui = TextualSessionUI(self)
        self.word = self.query_one("#word", Static)
        self.meta = self.query_one("#meta", Static)
        self.prompt = self.query_one("#prompt", Static)
        self.feedback = self.query_one("#feedback", Static)
        self.notice = self.query_one("#notice", Static)
        self.footer = self.query_one("#footer", Static)
        self.hud = self.query_one("#hud", Static)
        self.logo = self.query_one("#logo", Static)
        self.set_focus(None)
        if self.runtime.decorative_animations:
            self._tte_animator = TTEAdapter(
                self,
                self.logo,
                "LexiLab",
                effect="decrypt",
                fps=30,
                max_frames=24,
            )
            self._tte_animator.start()
            self.set_timer(1.2, self._quiet_logo)
        self._run_learning_session()

    def _quiet_logo(self) -> None:
        if self._tte_animator is not None:
            self._tte_animator.stop(final=True)
            self._tte_animator = None
        self.logo.update(Text("LexiLab", style="bold cyan"))

    @work(thread=True, exclusive=True)
    def _run_learning_session(self) -> None:
        ui = self._session_ui
        try:
            session = LearningSession(
                self.context.settings,
                self.context.repo,
                self.context.memory,
                self.context.vocab,
                ui,
            )
            result = session.run(self.session_id)
        except Exception as exc:  # surfaced in the UI; records already committed
            self.call_from_thread(self._show_error, str(exc))
            return
        self.call_from_thread(self.exit, result)

    def _show_error(self, message: str) -> None:
        self.notice.update(Text(f"会话错误: {message}", style="bold red"))
        self.footer.update(Text("[Enter] 返回", style="dim"))
        self._mode = "error"
        self._callback = None

    # --------------------------------------------------------------- presenters
    def _set_header(self, label: str) -> None:
        self.hud.update(Text(f"{label}   {self._position}", style="bold"))

    def _clear_screen(self) -> None:
        self.feedback.update(Text(""))
        self.notice.update(Text(""))
        self.answer.display = False
        self.answer.disabled = True
        self.answer.can_focus = False
        self.set_focus(None)

    def present_new_word(self, entry: WordEntry, position: str, callback: Callable) -> None:
        self._mode = "new_word"
        self._entry = entry
        self._position = position
        self._callback = callback
        self._clear_screen()
        self._set_header("NEW")
        self.word.update(Text(entry.headword, style="bold cyan"))
        self.meta.update(Text(entry.phonetic, style="dim"))
        self.prompt.update(Text("你认识这个单词吗？\n[1] 认识    [2] 不确定    [3] 不认识", justify="center"))
        self.footer.update(
            Text("[1-3] 回答   [F2] 发音   [Ctrl+P] 命令面板   [Ctrl+Q] 保存退出", style="dim")
        )
        self.effects.emit(EffectEvent.CARD_CHANGED, word=entry.headword)

    def present_word_info(self, entry: WordEntry, callback: Callable) -> None:
        self._mode = "word_info"
        self._entry = entry
        self._callback = callback
        self._clear_screen()
        self._set_header("NEW WORD")
        self.word.update(Text(entry.headword, style="bold cyan"))
        self.meta.update(Text(f"/{entry.phonetic.strip('/')}/  {entry.meaning_with_pos()}", style="dim"))
        lines = [Text(entry.meaning_with_pos(), style="bold")]
        if entry.phrases:
            lines.append(Text(f"{entry.phrases[0].phrase}  {entry.phrases[0].translation}", style="italic"))
        if entry.examples:
            lines.append(Text(entry.examples[0].sentence_en, style="italic"))
            if entry.examples[0].sentence_cn:
                lines.append(Text(entry.examples[0].sentence_cn, style="dim"))
        self.feedback.update(Text("\n").join(lines))
        self.footer.update(Text("[Space/Enter] 继续   [F2] 发音   [Esc] 退出", style="dim"))

    def present_recognition(
        self, entry: WordEntry, position: str, mode: str, callback: Callable
    ) -> None:
        self._mode = f"recognition:{mode}"
        self._stage = "front"
        self._entry = entry
        self._position = position
        self._callback = callback
        self._hinted = False
        self._started = self._monotonic()
        self._clear_screen()
        self._set_header("VERIFY" if mode == "verify" else ("NEW RECALL" if mode == "new" else "REVIEW"))
        self.word.update(Text(entry.headword, style="bold cyan"))
        self.meta.update(Text(entry.phonetic, style="dim"))
        self.prompt.update(Text("请回忆这个单词的含义\n[Space/Enter] 翻面", justify="center"))
        self.footer.update(
            Text("[Space/Enter] 翻面   [S] 跳过   [F2] 发音   [Ctrl+Q] 退出", style="dim")
        )
        self.effects.emit(EffectEvent.CARD_CHANGED, word=entry.headword)

    def _reveal_recognition(self) -> None:
        entry = self._entry
        if entry is None:
            return
        self._stage = "back"
        self.prompt.update(Text(""))
        self.meta.update(Text(f"/{entry.phonetic.strip('/')}/", style="dim"))
        lines = [Text(entry.meaning_with_pos(), style="bold")]
        if entry.phrases:
            lines.append(Text(f"{entry.phrases[0].phrase}  {entry.phrases[0].translation}", style="italic"))
        if entry.examples:
            lines.append(Text(entry.examples[0].sentence_en, style="italic"))
            if entry.examples[0].sentence_cn:
                lines.append(Text(entry.examples[0].sentence_cn, style="dim"))
        self.feedback.update(Text("\n").join(lines))
        self.footer.update(
            Text("[1] 忘记  [2] 困难  [3] 正常  [4] 简单   [S] 跳过   [Ctrl+Q] 退出", style="dim")
        )

    def present_production(
        self, entry: WordEntry, prompt: ProductionPrompt, position: str, callback: Callable
    ) -> None:
        self._mode = "production"
        self._entry = entry
        self._position = position
        self._callback = callback
        self._hinted = False
        self._started = self._monotonic()
        self._clear_screen()
        self._set_header("RECALL")
        self.prompt.update(
            Text(prompt.meaning.replace("\n", "；") + (f"（{prompt.pos}）" if prompt.pos else ""), justify="center")
        )
        lines = []
        if prompt.cloze:
            lines.append(Text(prompt.cloze, style="italic"))
        if prompt.example_cn:
            lines.append(Text(prompt.example_cn, style="dim"))
        self.feedback.update(Text("\n").join(lines))
        self.answer.display = True
        self.answer.disabled = False
        self.answer.can_focus = True
        self.answer.reset_text()
        self.answer.focus()
        self.footer.update(
            Text(
                "[Enter] 提交   [F1] 提示   [F2] 发音   [Esc] 返回   [Ctrl+Q] 退出",
                style="dim",
            )
        )
        self.effects.emit(EffectEvent.CARD_CHANGED, word=entry.headword)

    def present_feedback(self, feedback: FeedbackView, callback: Callable) -> None:
        self._mode = "feedback"
        self._callback = callback
        self._feedback_suggested = feedback.suggested_rating or 3
        self._clear_screen()
        self._set_header("FEEDBACK")
        head = "正确" if feedback.correct else ("无法自动判定" if feedback.correct is None else "需要复习")
        style = "bold green" if feedback.correct else ("bold yellow" if feedback.correct is None else "bold red")
        lines = [
            Text(head, style=style),
            Text(f"Your answer: {feedback.given}"),
            Text(f"Correct answer: {feedback.expected}", style="bold"),
        ]
        if feedback.diagnosis:
            lines.append(Text(feedback.diagnosis, style="yellow"))
        if feedback.message and feedback.message != feedback.diagnosis:
            lines.append(Text(feedback.message, style="dim"))
        if feedback.reference_sentence:
            lines.append(Text(feedback.reference_sentence, style="italic"))
        self.feedback.update(Text("\n").join(lines))
        suggested = feedback.suggested_rating or 3
        self.footer.update(
            Text(
                f"[Enter] 采用建议 [{suggested}]   [1-4] 覆盖评分   [Ctrl+Q] 退出",
                style="dim",
            )
        )
        if feedback.correct:
            self.effects.emit(
                EffectEvent.ANSWER_CORRECT,
                hinted=feedback.hinted,
                combo_visible=self.effects.runtime.combo,
            )
        elif feedback.correct is False:
            self.effects.emit(EffectEvent.ANSWER_INCORRECT, hinted=feedback.hinted)

    def present_reinforcement(self, entry: WordEntry, position: str, callback: Callable) -> None:
        self._mode = "reinforcement"
        self._stage = "front"
        self._entry = entry
        self._position = position
        self._callback = callback
        self._clear_screen()
        self._set_header("REINFORCE")
        self.word.update(Text(entry.headword, style="bold cyan"))
        self.prompt.update(Text("短时强化：请再次回忆\n[Space/Enter] 显示答案", justify="center"))
        self.footer.update(Text("[Space/Enter] 显示答案   [Ctrl+Q] 退出", style="dim"))

    def present_summary(self, summary: dict, callback: Callable) -> None:
        self._mode = "summary"
        self._callback = callback
        self._summary = summary
        self._clear_screen()
        self._set_header("SESSION COMPLETE")
        self.word.update(Text("完成", style="bold green"))
        lines = [
            Text(f"复习卡片: {summary.get('reviewed', 0)}"),
            Text(f"新学单词: {summary.get('new_words', 0)}"),
            Text(f"跳过: {summary.get('skipped', 0)}"),
            Text(f"用时: {summary.get('minutes', 0)} min"),
            Text(str(summary.get("message", "")), style="dim"),
        ]
        if summary.get("pending"):
            lines.append(Text(f"未完成: {summary['pending']}（已保存）", style="yellow"))
        self.feedback.update(Text("\n").join(lines))
        self.footer.update(Text("[Enter] 结束   [Ctrl+Q] 退出", style="dim"))
        self.effects.emit(EffectEvent.SESSION_COMPLETED)
        if self.effects.runtime.decorative_animations:
            self._tte_animator = TTEAdapter(
                self,
                self.word,
                f"SESSION COMPLETE  ×{summary.get('new_words', 0) + summary.get('reviewed', 0)}",
                effect="beams",
                fps=30,
                max_frames=28,
            )
            self._tte_animator.start()

    # ------------------------------------------------------------------ input
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._mode != "production":
            return
        answer = event.value.strip()
        if not answer:
            self.notify_message("答案为空，请继续输入", "warning")
            return
        callback = self._callback
        self._callback = None
        self.answer.display = False
        self.answer.disabled = True
        self.answer.can_focus = False
        self.set_focus(None)
        if callback:
            callback(
                RatingResult(
                    answer=answer,
                    hinted=self._hinted,
                    duration_ms=int((self._monotonic() - self._started) * 1000),
                )
            )

    def on_key(self, event) -> None:
        key = event.key
        if self._mode == "error":
            if key in {"enter", "escape"}:
                self.exit(None)
            return
        if self._mode == "new_word":
            if key in {"1", "2", "3"}:
                self._finish(int(key))
            elif key in {"q", "escape"}:
                self._finish(0)
            elif key == "f2":
                self._play_audio_current()
            event.stop()
            return
        if self._mode == "word_info":
            if key in {"enter", "space"}:
                self._finish(True)
            elif key in {"q", "escape"}:
                self._finish(False)
            elif key == "f2":
                self._play_audio_current()
            event.stop()
            return
        if self._mode.startswith("recognition"):
            if key in {"q", "escape"}:
                self._finish(RatingResult(quit=True, duration_ms=int((self._monotonic() - self._started) * 1000)))
            elif key == "s":
                self._emit_incorrect(skipped=True)
                self._finish(RatingResult(skipped=True, duration_ms=int((self._monotonic() - self._started) * 1000)))
            elif key == "f2":
                self._play_audio_current()
            elif key in {"enter", "space"} and self._stage == "front":
                self._reveal_recognition()
            elif key in {"1", "2", "3", "4"} and self._stage == "back":
                rating = int(key)
                if rating >= 3:
                    self.effects.emit(EffectEvent.ANSWER_CORRECT, hinted=self._hinted)
                else:
                    self.effects.emit(EffectEvent.ANSWER_INCORRECT, hinted=self._hinted)
                self._finish(
                    RatingResult(
                        rating=rating,
                        hinted=self._hinted,
                        duration_ms=int((self._monotonic() - self._started) * 1000),
                    )
                )
            event.stop()
            return
        if self._mode == "feedback":
            if key == "enter":
                self._finish(self._suggested_rating())
            elif key in {"1", "2", "3", "4"}:
                self._finish(int(key))
            elif key in {"q", "escape"}:
                self._finish(None)
            event.stop()
            return
        if self._mode == "reinforcement":
            entry = self._entry
            if key in {"q", "escape"}:
                self._finish(None)
            elif key in {"enter", "space"} and self._stage == "front":
                self._stage = "back"
                assert entry is not None
                self.meta.update(Text(f"/{entry.phonetic.strip('/')}/  {entry.meaning_with_pos()}", style="dim"))
                self.feedback.update(Text(entry.examples[0].sentence_en if entry.examples else entry.meaning_with_pos(), style="italic"))
                self.footer.update(Text("[Y] 想起来了   [N] 仍没想起来   [Ctrl+Q] 退出", style="dim"))
            elif key in {"y", "n"} and self._stage == "back":
                self._finish(key == "y")
            event.stop()
            return
        if self._mode == "summary":
            if key == "enter":
                self._finish(None)
            elif key == "q":
                self._finish(None)
            event.stop()

    def _suggested_rating(self) -> int:
        return getattr(self, "_feedback_suggested", 3)

    def _finish(self, value) -> None:
        callback = self._callback
        self._callback = None
        if callback:
            callback(value)

    # -------------------------------------------------------------- effects
    def _monotonic(self) -> float:
        import time

        return time.monotonic()

    def _effect_sink_safe(self, event: EffectEvent, payload: dict, state: EffectsState) -> None:
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
            if self.effects.runtime.combo and not payload.get("hinted"):
                self._combo.show(state.combo)
            else:
                self._combo.reset()
        elif event == EffectEvent.ANSWER_INCORRECT:
            self._shake()
            self._pulse("red")
            self._canvas.burst(color="bright_red")
            self._combo.reset()
        elif event == EffectEvent.COMBO_INCREASED:
            combo = payload.get("combo", state.combo)
            self._combo.show(combo, milestone=True)
            self._canvas.burst(color="yellow")
        elif event == EffectEvent.SESSION_COMPLETED:
            self._combo.show(state.best_combo, milestone=state.best_combo >= 3)
            self._pulse("green")

    def _target_widget(self):
        if self.answer.display:
            return self.answer
        return self.word

    def _pulse(self, color: str) -> None:
        target = self._target_widget()
        target.styles.border = ("round", color)
        self.set_timer(0.28, lambda: setattr(target.styles, "border", ("round", "cyan")))

    def _shake(self) -> None:
        target = self._target_widget()
        for delay_ms, offset in shake_offsets():
            self.set_timer(
                max(0.02, delay_ms / 1000),
                lambda value=offset: setattr(target.styles, "offset", (value, 0)),
            )

    def _play_audio_current(self) -> None:
        entry = self._entry
        if entry is None:
            return
        self._hinted = True
        self._play_audio(entry.headword)

    @work(thread=True, exclusive=False)
    def _play_audio(self, text: str) -> None:
        result = self.context.audio.speak(text)
        if not result.ok:
            self.call_from_thread(self.notify_message, f"音频不可用: {result.message}", "warning")
        else:
            self.call_from_thread(self.notify_message, "已播放发音（视为提示）", "info")

    def notify_message(self, message: str, style: str = "info") -> None:
        palette = {"info": "cyan", "success": "green", "warning": "yellow", "error": "bold red"}
        self.notice.update(Text(message, style=palette.get(style, "cyan")))

    def action_hint(self) -> None:
        if self._mode != "production" or self._entry is None:
            return
        self._hinted = True
        entry = self._entry
        self.notice.update(Text(f"提示: 首字母 {entry.headword[:1]}，共 {len(entry.headword)} 个字母", style="yellow"))

    def action_audio(self) -> None:
        self._play_audio_current()

    def action_toggle_effects(self) -> None:
        enabled = self.effects.toggle()
        self._canvas.clear()
        self._combo.reset()
        self.notify_message("特效已开启" if enabled else "特效已关闭", "info")

    def action_save_quit(self) -> None:
        self.ui.cancel()
        self.exit(None)

    def action_cancel(self) -> None:
        self.action_save_quit()

    @property
    def ui(self) -> TextualSessionUI:
        return self._session_ui

    @property
    def answer(self) -> PowerInput:
        return self._answer_widget


def run_textual_session(context: AppContext, session_id: str) -> SessionResult | None:
    runtime = preset_for(context.settings)
    app = LexiLabSessionApp(context, session_id, runtime)
    app.run()
    return app.return_value if isinstance(app.return_value, SessionResult) else None


# --------------------------------------------------------------------- menu
class LexiLabMenuApp(App):
    ENABLE_COMMAND_PALETTE = True
    CSS = CSS
    BINDINGS = [
        Binding("ctrl+q", "quit_menu", "退出", priority=True),
        Binding("ctrl+t", "toggle_effects", "切换特效", priority=True),
        Binding("ctrl+p", "command_palette", "命令面板", priority=True),
    ]

    def __init__(self, context: AppContext, options: list[tuple[str, str]]) -> None:
        super().__init__()
        self.context = context
        self.options_data = options
        self.runtime = preset_for(context.settings)
        self.effects = EffectsEngine(self.runtime)

    def compose(self) -> ComposeResult:
        self._menu_widget = OptionList(*[Option(label, id=key) for key, label in self.options_data], id="menu")
        self._menu_widget.can_focus = False
        yield Static("LexiLab", id="logo")
        yield Static("", id="stats")
        yield self._menu_widget
        yield Static(
            "[↑/↓] 选择   [Enter] 打开   [数字] 快捷   [Ctrl+P] 命令面板   [Ctrl+T] 特效   [Ctrl+Q] 退出",
            id="menu-hint",
        )

    def on_mount(self) -> None:
        summary = self.context.analytics.summary()
        self.query_one("#stats", Static).update(
            Text(
                f"待复习 {summary.get('due_count', 0)}   今日新词 {summary.get('today_new', 0)}   "
                f"已学习 {summary.get('learned_total', 0)}   今日 {summary.get('today_minutes', 0)} min",
            )
        )
        self._menu_widget.can_focus = True
        self._menu_widget.focus()
        if self.runtime.decorative_animations:
            animator = TTEAdapter(self, self.query_one("#logo", Static), "LexiLab", effect="decrypt", fps=30, max_frames=20)
            animator.start()
            self.set_timer(0.9, lambda: animator.stop(final=True))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.exit(event.option.id)

    def on_key(self, event) -> None:
        key = event.key
        if key in {"q", "escape"}:
            self.exit("q")
            event.stop()
            return
        digit_map = {
            "1": "review",
            "2": "learn",
            "3": "audio",
            "4": "read",
            "5": "write",
            "6": "stats",
            "7": "vocab",
            "8": "screen",
            "9": "materials",
            "c": "config",
        }
        if key in digit_map:
            available = {option_id for option_id, _ in self.options_data}
            if digit_map[key] in available:
                self.exit(digit_map[key])
                event.stop()

    def action_toggle_effects(self) -> None:
        enabled = self.effects.toggle()
        self.query_one("#menu-hint", Static).update(
            Text("特效已开启" if enabled else "特效已关闭", style="yellow")
        )

    def action_quit_menu(self) -> None:
        self.exit("q")


def run_textual_menu(context: AppContext, options: list[tuple[str, str]]) -> str | None:
    app = LexiLabMenuApp(context, options)
    app.run()
    value = app.return_value
    return str(value) if value is not None else None
