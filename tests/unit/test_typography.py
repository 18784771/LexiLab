from __future__ import annotations

from lexilab.config.settings import Settings
from lexilab.ui.typography import block_word, word_text


def test_default_display_mode_is_comfortable_and_readable():
    ui = Settings().ui
    assert ui.display_mode == "comfortable"
    assert ui.large_word_display is True
    assert ui.high_contrast is True
    assert ui.compact_mode is False


def test_block_word_is_centered_five_line_glyphs():
    rendered = block_word("mitigate", mode="comfortable", width=80)
    assert rendered is not None
    lines = rendered.splitlines()
    assert len(lines) == 5
    assert "█" in rendered
    assert max(len(line) for line in lines) <= 78


def test_long_word_falls_back_instead_of_being_truncated():
    assert block_word("internationalization", mode="large", width=30) is None
    text = word_text("internationalization", mode="large", width=30)
    assert text.plain == "internationalization"


def test_large_mode_falls_back_to_comfortable_then_plain():
    assert block_word("mitigate", mode="large", width=80) is not None
    assert block_word("mitigate", mode="large", width=20) is None
    assert word_text("mitigate", mode="large", width=20).plain == "mitigate"


def test_normal_mode_never_uses_block_art():
    assert block_word("mitigate", mode="normal", width=100) is None
    assert word_text("mitigate", mode="normal", width=100).plain == "mitigate"
