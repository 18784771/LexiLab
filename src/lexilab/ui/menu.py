from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from lexilab.capabilities import Capability, ai_usable, audio_ready


def _menu_items(caps: dict[str, Capability]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = [
        ("1", "单词复习"),
        ("2", "新词学习"),
    ]
    if audio_ready(caps):
        items.append(("3", "听音辨义 / 听写"))
    if ai_usable(caps):
        items.extend([("4", "AI 阅读"), ("5", "AI 写作")])
    items.extend(
        [
            ("6", "学习统计"),
            ("7", "词库管理"),
            ("8", "快速筛选"),
        ]
    )
    if caps["cached_materials"].ready:
        items.append(("9", "本地材料"))
    return items


def render_main_menu(console: Console, summary: dict, caps: dict[str, Capability]) -> None:
    stats = Table.grid(padding=(0, 3))
    stats.add_row(
        Text(f"待复习：{summary.get('due_count', 0)}"),
        Text(f"今日新词：{summary.get('today_new', 0)}"),
        Text(f"生词：{summary.get('personal_count', 0)}"),
    )
    stats.add_row(
        Text(f"已学习：{summary.get('learned_total', 0)}"),
        Text(f"今日学习：{summary.get('today_minutes', 0)} min"),
        Text(f"今日复习：{summary.get('today_reviews', 0)}"),
    )

    items = _menu_items(caps)
    options = Table.grid(padding=(0, 3))
    row: list[Text] = []
    for key, label in items:
        row.append(Text(f"[{key}] {label}"))
        if len(row) == 2:
            options.add_row(*row)
            row = []
    if row:
        options.add_row(row[0], Text(""))
    footer = Group(
        Text("[Enter] 开始今日学习   [c] 配置   [q] 退出", style="dim"),
    )
    body = Group(stats, Text(""), options, Text(""), footer)
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

