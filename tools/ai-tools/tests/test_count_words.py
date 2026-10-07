"""Tests for the summarize skill's word counter."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "skills" / "summarize" / "scripts"))

from count_words import count_summary_words  # noqa: E402


def test_session_line_prompt_list_and_note_are_excluded() -> None:
    text = (
        "**Session:** title (`abc`) - claude-opus-5 - 3 prompts\n\n"
        "**Summary**\n- one two three\n\n"
        "**Not verified**\n- four five\n\n"
        "<details><summary>Prompts (3)</summary>\n\n1. many words here\n</details>\n\n"
        "This is over the limit. Want a longer version?"
    )
    assert count_summary_words(text) == 8


def test_summary_without_prompt_list_counts_everything_but_the_session_line() -> None:
    assert count_summary_words("**Session:** x y z\n**Summary**\n- a b") == 3


def test_bullets_and_punctuation_are_not_words() -> None:
    assert count_summary_words("- a\n- b - c\n---") == 3
