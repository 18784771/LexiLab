from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from lexilab.capabilities import Capability


def _menu_items(caps: dict[str, Capability]) -> list[tuple[str, str]]:
    # The default surface is deliberately tiny. Everything else lives under
    # Settings so opening LexiLab never requires choosing a learning mode.
    return [
        ("study", "开始今日学习"),
        ("settings", "设置"),
        ("q", "退出"),
    ]


def render_main_menu(console: Console, summary: dict, caps: dict[str, Capability]) -> None:
    target = int(summary.get("new_target", 0) or 0)
    review_target = int(summary.get("review_target", summary.get("due_count", 0)) or 0)
    stats = Table.grid(padding=(0, 3))
    stats.add_row(
        Text(f"今日新词：{summary.get('today_new', 0)}/{target}"),
        Text(f"今日复习：{summary.get('today_reviews', 0)}/{review_target}"),
    )
    stats.add_row(
        Text(f"学习时间：{summary.get('today_minutes', 0)} min"),
        Text(f"总体进度：{round(float(summary.get('progress', 0)) * 100)}%"),
    )

    items = _menu_items(caps)
    options = Table.grid(padding=(0, 3))
    for index, (_, label) in enumerate(items):
        mark = ">" if index == 0 else " "
        options.add_row(Text(f"{mark} {label}"))

    body = Group(
        stats,
        Text(""),
        options,
        Text(""),
        Text("Enter 开始   ↑/↓ 选择   Esc 退出", style="dim"),
    )
    if console.width < 60:
        console.print(Text("LexiLab", style="bold cyan"))
        console.print(body)
    else:
        console.print(
            Panel(
                body,
                title=Text("LexiLab", style="bold cyan"),
                subtitle="Vocabulary-driven English Learning",
                border_style="cyan",
            )
        )


def menu_keys(caps: dict[str, Capability]) -> set[str]:
    return {key for key, _ in _menu_items(caps)}

