from __future__ import annotations

from rich.text import Text

# A deliberately small 5x5 block face. It is readable at typical terminal
# widths and, unlike decorative fonts, preserves letter shapes well enough for
# spelling recognition. Unsupported characters fall back to normal text.
_GLYPHS: dict[str, tuple[str, ...]] = {
    "A": (".###.", "#...#", "#####", "#...#", "#...#"),
    "B": ("####.", "#...#", "####.", "#...#", "####."),
    "C": (".####", "#....", "#....", "#....", ".####"),
    "D": ("####.", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "####.", "#....", "#####"),
    "F": ("#####", "#....", "####.", "#....", "#...."),
    "G": (".####", "#....", "#..##", "#...#", ".###."),
    "H": ("#...#", "#...#", "#####", "#...#", "#...#"),
    "I": ("#####", "..#..", "..#..", "..#..", "#####"),
    "J": ("..###", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "###..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "#.#.#", "#..##", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "####.", "#....", "#...."),
    "Q": (".###.", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "####.", "#..#.", "#...#"),
    "S": (".####", "#....", ".###.", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#.#.#", "##.##", "#...#"),
    "X": ("#...#", ".#.#.", "..#..", ".#.#.", "#...#"),
    "Y": ("#...#", ".#.#.", "..#..", "..#..", "..#.."),
    "Z": ("#####", "...#.", "..#..", ".#...", "#####"),
    "0": (".###.", "#...#", "#...#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "#####"),
    "2": (".###.", "....#", "..##.", ".#...", "#####"),
    "3": ("####.", "....#", ".###.", "....#", "####."),
    "4": ("#...#", "#...#", "#####", "....#", "....#"),
    "5": ("#####", "#....", "####.", "....#", "####."),
    "6": (".###.", "#....", "####.", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", "..#.."),
    "8": (".###.", "#...#", ".###.", "#...#", ".###."),
    "9": (".###.", "#...#", ".####", "....#", ".###."),
    "-": (".....", ".....", "#####", ".....", "....."),
    "'": ("..#..", "..#..", ".....", ".....", "....."),
}


def block_word(word: str, *, mode: str = "comfortable", width: int = 80) -> str | None:
    """Return a 5-line block rendering, or None when it would not fit.

    Long words and unsupported characters deliberately return None so callers
    can use a readable normal-text fallback rather than truncating a word.
    """
    if mode == "normal" or not word:
        return None
    upper = word.upper()
    if any(char not in _GLYPHS for char in upper):
        return None
    gap = 2 if mode == "large" else 1
    lines = ["", "", "", "", ""]
    for char in upper:
        glyph = _GLYPHS[char]
        for index, row in enumerate(glyph):
            lines[index] += row.replace(".", " ").replace("#", "█") + (" " * gap)
    rendered = "\n".join(line.rstrip() for line in lines)
    needed = max((len(line) for line in lines), default=0)
    if needed > max(10, width - 2):
        if mode == "large":
            return block_word(word, mode="comfortable", width=width)
        return None
    return rendered


def word_text(
    word: str,
    *,
    mode: str = "comfortable",
    width: int = 80,
    large_word_display: bool = True,
    high_contrast: bool = True,
) -> Text:
    block = (
        block_word(word, mode=mode, width=width)
        if large_word_display or mode == "large"
        else None
    )
    if block:
        style = "bold bright_cyan" if high_contrast else "bold cyan"
        return Text(block, style=style, justify="center")
    style = "bold bright_white" if high_contrast else "bold white"
    return Text(word, style=style, justify="center")


def muted_style(high_contrast: bool) -> str:
    return "white" if high_contrast else "dim"


def answer_style(high_contrast: bool) -> str:
    return "bold bright_white" if high_contrast else "bold"
