from __future__ import annotations

import asyncio
import html
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lexilab.context import AppContext
from lexilab.config.settings import Settings
from lexilab.models.session import ItemType, PlanItem, SessionPlan
from lexilab.ui.effects.presets import preset_for
from lexilab.ui.textual_app import LexiLabMenuApp, LexiLabSessionApp
from tests.helpers import make_due_card, seed_vocab

OUT = Path("docs/screenshots")


def _display_width(text: str) -> int:
    return sum(
        0
        if unicodedata.combining(char)
        else 2 if unicodedata.east_asian_width(char) in "WF" else 1
        for char in text
    )


def normalize_svg(path: Path) -> None:
    """Textual's SVG export measures CJK by character count, not cell width.

    Without this correction a browser draws every Chinese label on top of itself
    when converting the real Textual export to a preview.  The SVG remains the
    original Textual render; only textLength is corrected to the terminal cell
    width.
    """
    svg = path.read_text(encoding="utf-8")
    matrix = re.search(r"\.terminal-[^{}]+-matrix\s*\{([^}]+)\}", svg)
    font_size = 20.0
    if matrix:
        size = re.search(r"font-size:\s*([\d.]+)px", matrix.group(1))
        if size:
            font_size = float(size.group(1))
    cell_width = font_size * 0.61

    def repl(match: re.Match[str]) -> str:
        attrs, body = match.group(1), match.group(2)
        if "textLength=" not in attrs:
            return match.group(0)
        plain = html.unescape(re.sub(r"<[^>]+>", "", body))
        attrs = re.sub(
            r'textLength="[^"]*"',
            f'textLength="{_display_width(plain) * cell_width:.1f}"',
            attrs,
        )
        if "lengthAdjust=" not in attrs:
            attrs += ' lengthAdjust="spacingAndGlyphs"'
        return f"<text{attrs}>{body}</text>"

    path.write_text(
        re.sub(r"<text([^>]*)>(.*?)</text>", repl, svg, flags=re.S),
        encoding="utf-8",
    )


def context_for(mode: str) -> AppContext:
    s = Settings()
    s.data_dir = Path("/tmp/lexilab-screenshot-db")
    s.general.data_dir = str(s.data_dir)
    s.audio.enabled = False
    s.effects.startup_animation = False
    s.ui.display_mode = mode
    s.ui.large_word_display = True
    s.ui.high_contrast = True
    s.ensure_dirs()
    ctx = AppContext(s)
    seed_vocab(ctx.vocab_repo)
    ctx.vocab_repo.db.execute(
        "UPDATE words SET phonetic_uk=?, phonetic_us=? WHERE word_key=?",
        ("ˈmɪtɪɡeɪt", "ˈmɪtɪɡeɪt", "mitigate"),
    )
    return ctx


async def capture_main(path: Path, size: tuple[int, int] = (100, 30)) -> None:
    ctx = context_for("comfortable")
    app = LexiLabMenuApp(ctx, [("study", "开始今日学习"), ("settings", "设置"), ("q", "退出")])
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.2)
        path.write_text(app.export_screenshot(title="LexiLab main menu"), encoding="utf-8")
        await pilot.press("enter")
        await pilot.pause(0.1)


async def capture_session(path: Path, mode: str, size: tuple[int, int]) -> None:
    ctx = context_for(mode)
    card = make_due_card(ctx.repo, "mitigate", "recognition")
    item = PlanItem(ItemType.REVIEW_RECOGNITION, "mitigate", direction="recognition", card_row_id=card["id"])
    sid = ctx.repo.create_session("review", SessionPlan(kind="review", items=[item]))
    app = LexiLabSessionApp(ctx, sid, preset_for(ctx.settings))
    async with app.run_test(size=size) as pilot:
        await pilot.pause(0.2)
        path.write_text(
            app.export_screenshot(title=f"LexiLab word ({mode}, {size[0]}x{size[1]})"),
            encoding="utf-8",
        )
        await pilot.press("right")
        await pilot.pause(0.3)
        await pilot.press("enter")
        await pilot.pause(0.1)


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    await capture_main(OUT / "main_menu.svg")
    await capture_session(OUT / "word_before_normal.svg", "normal", (100, 30))
    await capture_session(OUT / "word_after_comfortable.svg", "comfortable", (100, 30))
    await capture_session(OUT / "word_after_large.svg", "large", (100, 30))
    await capture_session(OUT / "word_small_terminal.svg", "large", (44, 16))
    for path in OUT.glob("*.svg"):
        normalize_svg(path)
    print("screenshots:", ", ".join(sorted(p.name for p in OUT.glob("*.svg"))))


if __name__ == "__main__":
    asyncio.run(main())
