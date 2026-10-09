"""Fixtures shared by the summarize skill's tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from transcript_records import (
    SCRIPTS,
    DENIAL,
    human,
    assistant,
    tool_use,
    tool_result,
)

# Make the scripts importable by name, as the skill runs them.
sys.path.insert(0, str(SCRIPTS))

import transcript_parser  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point Claude Code's config folder at an empty temporary one.

    Every digest scans the user's recent transcripts, so without this the tests
    would read the real ``~/.claude``.
    """
    config = tmp_path / "config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    return config


@pytest.fixture
def records() -> list[dict]:
    return [
        {"type": "custom-title", "customTitle": "folate update"},
        {"type": "user", "isMeta": True, "message": {"content": "<system-reminder>noise</system-reminder>"}},
        human("Compare Tessema and Crider effect sizes", mode="default"),
        assistant(
            {"type": "text", "text": "Here is the comparison."},
            tool_use("t1", "Bash", command="pytest tests/"),
            tool_use("t2", "Bash", command="rm -rf build"),
            tool_use("t3", "Edit", file_path="/repo/model.py"),
            tool_use("t4", "Write", file_path="/repo/model.py"),
            tool_use("t5", "Bash", command="cat notes.txt"),
        ),
        tool_result("t1", "5 passed"),
        tool_result("t2", DENIAL, is_error=True),
        tool_result("t3", "File updated"),
        tool_result("t4", "File written"),
        # Output that merely quotes the denial text is not a denial.
        tool_result("t5", f"notes: {DENIAL}"),
        assistant(tool_use("t6", "Bash", command="python check.py"), model="<synthetic>"),
        tool_result("t6", "Exit code 1", is_error=True),
        assistant(tool_use("t7", "AskUserQuestion", questions=[])),
        tool_result("t7", 'Your questions have been answered: "Which table?"="Table 3".'),
        {"type": "user", "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}},
        {
            "type": "system",
            "subtype": "compact_boundary",
            "content": "Conversation compacted",
            "timestamp": "2026-10-01T11:00:00Z",
        },
        {
            "type": "user",
            "isCompactSummary": True,
            "message": {"content": "This session is being continued from a previous conversation."},
        },
        human(
            "<command-message>simsci:pr-prep</command-message>\n<command-name>/simsci:pr-prep</command-name>\n"
            "<command-args>open the PR</command-args>",
            timestamp="2026-10-01T12:30:00Z",
            mode="auto",
        ),
        human(
            "<command-message>simsci-research:summarize</command-message>\n"
            "<command-name>/simsci-research:summarize</command-name>\n<command-args>150</command-args>",
            mode="auto",
        ),
    ]


@pytest.fixture
def facts(records: list[dict]) -> dict:
    return transcript_parser.summarize_records(records)
