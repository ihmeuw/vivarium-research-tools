"""Tests for the summarize skill's word counter."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "skills" / "summarize" / "scripts"))

from count_words import count_summary_words  # noqa: E402


def test_session_section_prompt_list_and_note_are_excluded() -> None:
    text = (
        "**Session**\n- Title and ID: title (`abc`)\n- Models: claude-opus-5\n- Prompts: 3\n\n"
        "**One**\n- two three\n\n"
        "**Four five**\n- six seven eight\n\n"
        "<details><summary>Prompts (3)</summary>\n\n1. many words here\n</details>\n\n"
        "This is over the limit. Want a longer version?"
    )
    assert count_summary_words(text) == 8


def test_summary_without_prompt_list_counts_everything_but_the_session_section() -> None:
    assert count_summary_words("**Session**\n- x y z\n**Summary**\n- a b") == 3


def test_bullets_and_punctuation_are_not_words() -> None:
    assert count_summary_words("- a\n- b - c\n---") == 3


def test_other_details_blocks_are_counted() -> None:
    body = "**Summary**\n- one two\n\n<details><summary>More context</summary>\nthree four\n</details>\n\n"
    prompt_list = "<details><summary>Prompts (1)</summary>\n\n1. not counted\n</details>"
    assert count_summary_words(body + prompt_list) == count_summary_words(body)
    assert count_summary_words(body) > count_summary_words("**Summary**\n- one two")


def test_command_line_prints_the_count(tmp_path: Path) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text("**Summary**\n- one two")
    script = Path(__file__).parents[1] / "skills" / "summarize" / "scripts" / "count_words.py"
    result = subprocess.run([sys.executable, str(script), str(draft)], capture_output=True, text=True)
    assert result.stdout.strip() == "3"
