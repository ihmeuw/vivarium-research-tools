"""Tests for the summarize skill's transcript parser.

The transcripts below are small hand-written imitations of real Claude Code
transcripts.  Each record shape here was copied from a real transcript; if Claude
Code changes its format, update these records to match and fix the script.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "skills" / "summarize" / "scripts"))

import session_facts  # noqa: E402

DENIAL = (
    "The user doesn't want to proceed with this tool use. The tool use was rejected "
    "(eg. if it was a file edit, the new_string was NOT written to the file)."
)


def human(text: str, timestamp: str = "2026-10-01T10:00:00Z", mode: str = "default") -> dict:
    return {
        "type": "user",
        "origin": {"kind": "human"},
        "permissionMode": mode,
        "timestamp": timestamp,
        "message": {"role": "user", "content": text},
    }


def assistant(*blocks: dict, model: str = "claude-opus-5-5") -> dict:
    return {
        "type": "assistant",
        "timestamp": "2026-10-01T10:05:00Z",
        "message": {"role": "assistant", "model": model, "content": list(blocks)},
    }


def tool_use(tool_id: str, name: str, **tool_input: object) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def tool_result(tool_id: str, content: str, is_error: bool = False) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": content, "is_error": is_error}
            ],
        },
    }


def write_transcript(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return path


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
    return session_facts.summarize_records(records)


def test_only_human_prompts_are_collected(facts: dict) -> None:
    texts = [text for _, text in facts["prompts"]]
    assert texts == ["Compare Tessema and Crider effect sizes", "/simsci:pr-prep open the PR"]


def test_permission_mode_recorded_per_prompt(facts: dict) -> None:
    assert facts["permission_modes"] == {"default": 1, "auto": 1}


def test_command_statuses(facts: dict) -> None:
    assert facts["commands"] == [
        ("pytest tests/", "ok"),
        ("rm -rf build", "denied"),
        ("cat notes.txt", "ok"),
        ("python check.py", "failed"),
    ]


def test_denials_require_the_marker_at_the_start(facts: dict) -> None:
    assert facts["denials"] == ["Bash"]


def test_synthetic_models_are_ignored(facts: dict) -> None:
    assert facts["models"] == {"claude-opus-5-5": 2}


def test_edited_files_are_deduplicated(facts: dict) -> None:
    assert facts["edited_files"] == ["/repo/model.py"]


def test_answers_interruptions_and_compactions(facts: dict) -> None:
    assert facts["answers"] == ['Your questions have been answered: "Which table?"="Table 3".']
    assert facts["interruptions"] == 1
    assert len(facts["compactions"]) == 1
    assert facts["title"] == "folate update"


def test_text_of_handles_block_lists() -> None:
    assert session_facts.text_of([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "a b"
    assert session_facts.text_of(None) == ""


def test_shorten_truncates_and_collapses_whitespace() -> None:
    assert session_facts.shorten("a\n\n b", 10) == "a b"
    assert session_facts.shorten("x" * 20, 10) == "xxxxxxx..."


def test_find_transcript_by_id_and_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    transcript = write_transcript(tmp_path / "projects" / "-repo" / "abc-123.jsonl", [])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert session_facts.find_transcript("abc-123") == transcript
    assert session_facts.find_transcript(str(transcript)) == transcript
    with pytest.raises(FileNotFoundError):
        session_facts.find_transcript("missing")


def test_find_transcript_rejects_duplicate_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_transcript(tmp_path / "projects" / "-repo-a" / "abc-123.jsonl", [])
    write_transcript(tmp_path / "projects" / "-repo-b" / "abc-123.jsonl", [])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="Multiple transcripts found for session 'abc-123'"):
        session_facts.find_transcript("abc-123")


def test_malformed_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text('{"type": "custom-title", "customTitle": "ok"}\nnot json\n')
    assert session_facts.read_records(path) == [{"type": "custom-title", "customTitle": "ok"}]


def test_digest_includes_subagents(tmp_path: Path, records: list[dict]) -> None:
    transcript = write_transcript(tmp_path / "session.jsonl", records)
    subagent_folder = tmp_path / "session" / "subagents"
    write_transcript(
        subagent_folder / "agent-a1.jsonl",
        [assistant(tool_use("s1", "Bash", command="python recompute.py")), tool_result("s1", "ok")],
    )
    (subagent_folder / "agent-a1.meta.json").write_text(
        json.dumps({"agentType": "general-purpose", "description": "Audit arithmetic"})
    )

    digest = session_facts.build_digest(transcript, include_conversation=False)

    assert "Subagents: 1" in digest
    assert "- general-purpose: Audit arithmetic (claude-opus-5-5; 1 commands, 0 files edited)" in digest
    assert "    - [ok] python recompute.py" in digest
    assert "Human prompts: 2 (" in digest
    assert "Tool calls denied by the human: Bash x1" in digest
    assert "Compactions (earlier context summarized): 1; 2026-10-01 11:00 UTC" in digest
    assert "Here is the comparison." not in digest


def test_digest_conversation_flag_adds_assistant_text(tmp_path: Path, records: list[dict]) -> None:
    transcript = write_transcript(tmp_path / "session.jsonl", records)
    digest = session_facts.build_digest(transcript, include_conversation=True)
    assert "## Claude's last message before each prompt" in digest
    assert "- Here is the comparison." in digest
    assert "WARNING" not in digest
    assert "Subagents: 0" in digest


def test_long_replies_are_kept_in_full_under_the_budget() -> None:
    reply = "word " * 1000
    lines = session_facts.conversation_lines([reply])
    assert lines[1] == "- " + reply.strip()


def test_replies_over_the_budget_are_truncated_with_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_facts, "REPLY_WORD_BUDGET", 10)
    lines = session_facts.conversation_lines(["word " * 20, "short reply"])
    assert lines[1].startswith("WARNING: these 22 words of replies were truncated to about 30 characters")
    assert lines[2] == "- " + ("word " * 20)[:27] + "..."
    assert lines[3] == "- short reply"


def test_replies_keep_only_the_last_message_of_each_turn() -> None:
    facts = session_facts.summarize_records(
        [
            human("first"),
            assistant({"type": "text", "text": "Let me look."}),
            assistant({"type": "text", "text": "Done with first."}),
            human("second"),
            assistant({"type": "text", "text": "Done with second."}),
        ]
    )
    assert [reply for reply in facts["replies"] if reply] == ["Done with first.", "Done with second."]
