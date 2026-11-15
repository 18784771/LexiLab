from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from lexilab.context import AppContext
from lexilab.relations.model import RELATION_LABELS
from lexilab.relations.model import RelationView
from lexilab.ui.effects.presets import preset_for

CSS = """
Screen { background: $surface; color: $text; }
#title { height: 3; content-align: center middle; text-style: bold; color: $accent; }
#word { height: auto; content-align: center middle; }
#meaning { height: 1; content-align: center middle; color: $text-muted; }
#types { height: 2; padding: 0 1; color: $text-muted; }
#relations { height: 1fr; margin: 1 2; border: round $accent; }
#footer { height: 1; dock: bottom; padding: 0 1; background: $panel; color: $text-muted; }
"""


class LexiLabRelationsApp(App):
    ENABLE_COMMAND_PALETTE = True
    CSS = CSS
    BINDINGS = [
        Binding("ctrl+q", "quit", "退出", priority=True),
        Binding("escape", "quit", "返回", priority=True),
        Binding("tab", "focus_next", "切换", priority=False),
    ]

    def __init__(
        self,
        context: AppContext,
        word: str,
        relation_type: str | None = None,
        limit: int = 30,
    ) -> None:
        super().__init__()
        self.context = context
        self.word = word
        self.requested_type = relation_type
        self.limit = limit
        self.runtime = preset_for(context.settings)
        self.groups = context.relations.groups(word, limit=limit)
        self.types = [
            kind
            for kind in (
                "synonym",
                "antonym",
                "derivation",
                "hypernym",
                "hyponym",
                "similar",
                "related",
                "orthographic_similar",
                "user_confusion",
            )
            if self.groups.get(kind)
        ]
        self.active = relation_type if relation_type in self.types else (self.types[0] if self.types else "")

    def compose(self) -> ComposeResult:
        yield Static("LEXILAB / WORD RELATIONS", id="title")
        yield Static("", id="word")
        yield Static("", id="meaning")
        yield Static("", id="types")
        yield OptionList(id="relations")
        yield Static(
            "[1-9] 切换关系   [↑/↓] 选择   [Enter] 学习该词   [Esc] 返回",
            id="footer",
        )

    def on_mount(self) -> None:
        entry = self.context.vocab.display_entry(self.context.vocab.lookup(self.word))
        self.query_one("#word", Static).update(
            Text(entry.headword if entry else self.word, style="bold cyan")
        )
        if entry:
            self.query_one("#meaning", Static).update(Text(entry.meaning_with_pos(), style="dim"))
        self._render_types()
        self._load(self.active)

    def _render_types(self) -> None:
        labels = []
        for index, kind in enumerate(self.types, 1):
            label = RELATION_LABELS.get(kind, kind)
            marker = "▶" if kind == self.active else " "
            labels.append(f"{marker}[{index}] {label}({len(self.groups[kind])})")
        self.query_one("#types", Static).update(Text("   ".join(labels) or "暂无关系数据"))

    def _load(self, kind: str) -> None:
        self.active = kind
        widget = self.query_one("#relations", OptionList)
        widget.clear_options()
        for index, view in enumerate(self.groups.get(kind, [])):
            widget.add_option(Option(self._label(view), id=f"{index}:{view.word_key}"))
        if self.groups.get(kind):
            widget.focus()
        self._render_types()

    @staticmethod
    def _label(view: RelationView) -> str:
        parts = [view.headword]
        if view.meaning:
            parts.append(view.meaning)
        if view.source_sense:
            parts.append(f"sense={view.source_sense}")
        return "   ".join(parts)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.exit(event.option.id.split(":", 1)[1])

    def on_key(self, event) -> None:
        key = event.key
        if key.isdigit():
            index = int(key) - 1
            if 0 <= index < len(self.types):
                self._load(self.types[index])
                event.stop()
        elif key == "q":
            self.exit(None)
            event.stop()

    def action_quit(self) -> None:
        self.exit(None)


def run_textual_relations(
    context: AppContext,
    word: str,
    *,
    relation_type: str | None = None,
    limit: int = 30,
) -> str | None:
    app = LexiLabRelationsApp(context, word, relation_type=relation_type, limit=limit)
    app.run()
    value = app.return_value
    return str(value) if value is not None else None
