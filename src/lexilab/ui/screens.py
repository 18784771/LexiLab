from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from lexilab.models.word import LookupResult, WordEntry


def _bar(accuracy: float | None, width: int = 10) -> str:
    if accuracy is None:
        return "未评估"
    filled = max(0, min(width, round(accuracy * width)))
    return "█" * filled + "░" * (width - filled) + f"  {accuracy:.0%}"


def lookup_screen(console: Console, result: LookupResult, entry: WordEntry | None) -> None:
    if not result.found or entry is None:
        console.print(Panel(Text(f"未找到单词: {result.word_key}", style="yellow"), border_style="yellow"))
        return
    blocks: list = [Text(entry.headword, style="bold cyan")]
    if entry.phonetic:
        blocks.append(Text(f"/{entry.phonetic.strip('/')}/", style="dim"))
    if entry.definitions:
        for definition in entry.definitions[:10]:
            line = Text()
            if definition.pos:
                line.append(f"{definition.pos}. ", style="bold")
            line.append(definition.meaning_cn)
            if definition.meaning_en:
                line.append(f"  {definition.meaning_en[:200]}", style="dim")
            blocks.append(line)
    else:
        blocks.append(Text(entry.translation or "(无释义)"))
    if entry.phrases:
        blocks.append(Text("短语", style="bold"))
        blocks.extend(Text(f"  {p.phrase}  {p.translation}") for p in entry.phrases[:8])
    if entry.examples:
        blocks.append(Text("例句", style="bold"))
        for example in entry.examples[:4]:
            blocks.append(Text("  " + example.sentence_en, style="italic"))
            if example.sentence_cn:
                blocks.append(Text("  " + example.sentence_cn, style="dim"))
    if entry.synonyms:
        blocks.append(Text("同近义词: " + ", ".join(entry.synonyms[:12]), style="dim"))
    if entry.derivatives:
        blocks.append(Text("同根词: " + "; ".join(entry.derivatives[:8]), style="dim"))
    if result.ecdict:
        ec = result.ecdict
        blocks.append(
            Text(
                f"ECDICT: tag={ec.tag or '-'}  frq={ec.frq or '-'}  bnc={ec.bnc or '-'}  "
                f"collins={ec.collins or '-'}  exchange={ec.exchange or '-'}",
                style="dim",
            )
        )
    if result.personal:
        note = result.personal.get("note") or "已加入学习库"
        blocks.append(Text(f"个人生词: {note}", style="green"))
    blocks.append(Text(f"来源: {result.found_in}", style="dim"))
    console.print(Panel(Group(*blocks), title="LOOKUP", border_style="cyan", expand=False))


def stats_screen(console: Console, summary: dict) -> None:
    lines: list = [
        Text(f"今日学习时间: {summary.get('today_minutes', 0)} min"),
        Text(f"今日新词: {summary.get('today_new', 0)}"),
        Text(f"今日复习: {summary.get('today_reviews', 0)}"),
        Text(f"待复习卡片: {summary.get('due_count', 0)}"),
        Text(f"已学习词汇: {summary.get('learned_total', 0)}"),
        Text(f"个人生词: {summary.get('personal_count', 0)}"),
        Text(""),
    ]
    labels = {
        "recognition": "词义识别",
        "recall": "主动提取",
        "spelling": "拼写能力",
        "listening": "听力识别",
        "context": "语境理解",
        "production": "写作运用",
    }
    for skill, label in labels.items():
        data = summary.get("skills", {}).get(skill, {})
        sample = data.get("sample", 0)
        if not sample:
            lines.append(Text(f"{label}: 未评估", style="dim"))
        elif sample < 5:
            lines.append(Text(f"{label}: 数据不足 (n={sample})", style="dim"))
        else:
            lines.append(Text(f"{label}: {_bar(data.get('accuracy'))}  (n={sample})"))
    lines.append(Text(""))
    for key, label in (("delayed_7d", "7 天延迟回忆"), ("delayed_30d", "30 天延迟回忆")):
        data = summary.get(key, {})
        if not data.get("sufficient"):
            lines.append(Text(f"{label}: 数据不足 (n={data.get('sample', 0)})", style="dim"))
        else:
            lines.append(Text(f"{label}: {_bar(data.get('accuracy'))}  (n={data.get('sample')})"))
    lines.append(Text(""))
    weak = summary.get("weak_words") or []
    lines.append(Text("重点强化: " + (", ".join(weak[:8]) if weak else "无")))
    avg_ms = summary.get("avg_response_ms")
    lines.append(
        Text(f"平均反应时间: {avg_ms} ms" if avg_ms else "平均反应时间: 数据不足", style="dim")
    )
    upcoming = summary.get("upcoming") or []
    if upcoming:
        lines.append(Text("未来 7 天复习负担: " + "  ".join(str(item["count"]) for item in upcoming), style="dim"))
    console.print(Panel(Group(*lines), title="LEARNING REPORT", border_style="green", expand=False))


def books_screen(console: Console, books: list, active: str) -> None:
    table = Table(title="词库", show_lines=False)
    table.add_column("代码")
    table.add_column("名称")
    table.add_column("词条数", justify="right")
    table.add_column("当前")
    for book in books:
        table.add_row(
            book["code"],
            book["name"],
            str(book["word_count"]),
            "*" if book["code"] == active else "",
        )
    console.print(table)


def mistakes_screen(console: Console, errors: list[dict]) -> None:
    if not errors:
        console.print(Text("没有未解决的错误。", style="green"))
        return
    table = Table(title="未解决错误", show_lines=False)
    table.add_column("单词")
    table.add_column("能力")
    table.add_column("错误类型")
    table.add_column("次数", justify="right")
    table.add_column("最近")
    for item in errors:
        table.add_row(
            item["word_key"],
            item["skill"],
            item["error_type"],
            str(item["n"]),
            str(item.get("last_at", ""))[:16],
        )
    console.print(table)


def doctor_screen(console: Console, checks: list[dict]) -> None:
    table = Table(title="lexi doctor", show_lines=False)
    table.add_column("检查项")
    table.add_column("状态")
    table.add_column("说明")
    palette = {
        "ready": ("OK", "green"),
        "disabled": ("OFF", "dim"),
        "unconfigured": ("SETUP", "yellow"),
        "unavailable": ("N/A", "yellow"),
        "error": ("ERROR", "red"),
    }
    for check in checks:
        state = check.get("state")
        if state:
            label, color = palette.get(str(state), ("?", "white"))
        else:
            label, color = ("OK", "green") if check.get("ok") else ("FAIL", "red")
        table.add_row(check["name"], Text(label, style=color), str(check["detail"]))
    console.print(table)
