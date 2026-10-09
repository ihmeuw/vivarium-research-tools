"""Tests for the digest and the command line."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import transcript_parser
import session_facts
from transcript_records import (
    SCRIPTS,
    human,
    assistant,
    tool_use,
    tool_result,
    write_transcript,
    canary_session,
)


class TestBuildDigest:
    """The digest's contents."""

    def test_digest_includes_subagents(self, tmp_path: Path, records: list[dict]) -> None:
        dispatch = assistant(tool_use("d1", "Agent", subagent_type="general-purpose", description="Audit arithmetic"))
        transcript = write_transcript(tmp_path / "session.jsonl", records + [dispatch])
        subagent_folder = tmp_path / "session" / "subagents"
        write_transcript(
            subagent_folder / "agent-a1.jsonl",
            [assistant(tool_use("s1", "Bash", command="python recompute.py")), tool_result("s1", "ok")],
        )
        (subagent_folder / "agent-a1.meta.json").write_text(
            json.dumps({"agentType": "general-purpose", "description": "Audit arithmetic", "toolUseId": "d1"})
        )

        digest = session_facts.build_digest(transcript, include_replies=False)

        assert "Subagents: 1\n" in digest
        assert "FORMAT WARNING" not in digest
        assert "- general-purpose: Audit arithmetic (claude-opus-5-5; 1 commands, 0 files edited)" in digest
        assert "    - [ok] python recompute.py" in digest
        assert "Human prompts: 2 (" in digest
        assert "Tool calls denied by the human: Bash x1" in digest
        assert "Compactions (earlier context summarized): 1; 2026-10-01 11:00 UTC" in digest
        # The fixture session was compacted, so Claude's replies are included automatically.
        assert "- Here is the comparison." in digest

    def test_long_prompts_are_truncated_in_the_digest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_facts, "PROMPT_CHARACTER_LIMIT", 10)
        transcript = write_transcript(tmp_path / "session.jsonl", [human("abcdefghijklmnop")])
        assert "1. [10:00] abcdefg..." in session_facts.build_digest(transcript, include_replies=False)

    def test_command_list_is_capped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_facts, "MAX_COMMANDS_LISTED", 2)
        records = [human("go")]
        for number in range(3):
            records += [assistant(tool_use(f"t{number}", "Bash", command=f"step {number}")), tool_result(f"t{number}", "ok")]
        digest = session_facts.build_digest(write_transcript(tmp_path / "session.jsonl", records), include_replies=False)
        assert "Shell commands: 3 (0 failed)" in digest
        assert "- ... 1 earlier commands omitted" in digest
        assert "step 0" not in digest
        assert "- [ok] step 2" in digest

    def test_digest_without_timestamps_or_prompts(self, tmp_path: Path) -> None:
        records = [{"type": "assistant", "message": {"model": "claude-opus-5-5", "content": []}}]
        digest = session_facts.build_digest(write_transcript(tmp_path / "session.jsonl", records), include_replies=False)
        assert "Span:" not in digest
        assert "Human prompts: 0 (0 words)" in digest
        assert "FORMAT WARNING: no record has a timestamp" in digest

    def test_subagents_without_transcripts_are_counted(self, tmp_path: Path) -> None:
        records = [
            human("go"),
            assistant(
                tool_use("d1", "Agent", subagent_type="reviewer", description="Review design"),
                tool_use("d2", "Task", subagent_type="validator", description="Run tests"),
            ),
        ]
        transcript = write_transcript(tmp_path / "session.jsonl", records)
        subagent_folder = tmp_path / "session" / "subagents"
        write_transcript(subagent_folder / "agent-a1.jsonl", [assistant()])
        (subagent_folder / "agent-a1.meta.json").write_text(
            json.dumps({"agentType": "reviewer", "description": "Review design", "toolUseId": "d1"})
        )
        digest = session_facts.build_digest(transcript, include_replies=False)
        assert "Subagents: 2 (1 without a transcript in this session's folder)" in digest
        assert "- validator: Run tests (no transcript in this session's folder)" in digest
        assert "- reviewer: Review design (claude-opus-5-5; 0 commands, 0 files edited)" in digest

    def test_digest_reports_the_claude_code_version(self, tmp_path: Path) -> None:
        transcript = write_transcript(tmp_path / "session.jsonl", [dict(human("go"), version="2.1.292")])
        assert "Claude Code version: 2.1.292" in session_facts.build_digest(transcript, include_replies=False)
        assert transcript_parser.version_tuple("2.1.292") == (2, 1, 292)
        assert transcript_parser.version_tuple("2.1.x") is None

    def test_digest_reports_facts_that_stopped_appearing_in_recent_sessions(
        self, tmp_path: Path, isolated_config: Path
    ) -> None:
        projects = isolated_config / "projects" / "-repo"
        older = canary_session(projects, "older", "2.1.290")
        newer = canary_session(projects, "newer", "2.1.291")
        newer.write_text(newer.read_text().replace("[Request interrupted by user]", "[Interrupted]"))
        digest = session_facts.build_digest(newer, include_replies=False)
        assert (
            "FORMAT WARNING: across your sessions from the last 14 days, interruptions (Esc): last seen in 2.1.290"
        ) in digest
        assert digest.count("FORMAT WARNING") == 1

    def test_digest_has_no_format_warning_when_recent_sessions_look_normal(self, isolated_config: Path) -> None:
        transcript = canary_session(isolated_config / "projects" / "-repo")
        assert "FORMAT WARNING" not in session_facts.build_digest(transcript, include_replies=False)

    def test_damaged_recent_session_does_not_break_the_digest(self, isolated_config: Path) -> None:
        projects = isolated_config / "projects" / "-repo"
        damaged = projects / "damaged.jsonl"
        damaged.parent.mkdir(parents=True)
        damaged.write_bytes(b'\xff\xfe\n[]\n{"type": "user", "origin": {"kind": "human"}, "timestamp": "yesterday"}\n')
        transcript = write_transcript(projects / "session.jsonl", [human("go")])
        digest = session_facts.build_digest(transcript, include_replies=False)
        assert "Human prompts: 1 (" in digest
        # Damage in another session is not this summary's problem.
        assert "NOTE" not in digest

    def test_span_line_gives_times_and_duration(self, tmp_path: Path) -> None:
        short = write_transcript(
            tmp_path / "short.jsonl", [human("a", "2026-10-01T10:00:00Z"), human("b", "2026-10-01T10:45:00Z")]
        )
        long = write_transcript(
            tmp_path / "long.jsonl", [human("a", "2026-10-01T10:00:00Z"), human("b", "2026-10-01T12:30:00Z")]
        )
        assert "Span: 2026-10-01 10:00 to 2026-10-01 10:45 UTC (45m, including idle time)" in (
            session_facts.build_digest(short, include_replies=False)
        )
        assert "Span: 2026-10-01 10:00 to 2026-10-01 12:30 UTC (2h 30m, including idle time)" in (
            session_facts.build_digest(long, include_replies=False)
        )

    def test_renamed_session_has_a_title_line(self, tmp_path: Path, records: list[dict]) -> None:
        transcript = write_transcript(tmp_path / "session.jsonl", records)
        assert "Title: folate update" in session_facts.build_digest(transcript, include_replies=False)

    def test_models_line_lists_each_model_most_used_first(self, tmp_path: Path) -> None:
        records = [human("go"), assistant(model="claude-haiku-4-5"), assistant(), assistant()]
        transcript = write_transcript(tmp_path / "session.jsonl", records)
        assert "Models: claude-opus-5-5 (2 turns), claude-haiku-4-5 (1 turns)" in (
            session_facts.build_digest(transcript, include_replies=False)
        )

    def test_every_compaction_date_is_listed(self, tmp_path: Path) -> None:
        records = [human("go")]
        for hour in ("11", "12"):
            records += [
                {"type": "system", "subtype": "compact_boundary", "timestamp": f"2026-10-01T{hour}:00:00Z"},
                {"type": "user", "isCompactSummary": True, "message": {"content": "Continued."}},
            ]
        transcript = write_transcript(tmp_path / "session.jsonl", records)
        assert "Compactions (earlier context summarized): 2; 2026-10-01 11:00 UTC; 2026-10-01 12:00 UTC" in (
            session_facts.build_digest(transcript, include_replies=False)
        )

    def test_long_commands_are_truncated(self, tmp_path: Path) -> None:
        records = [human("go"), assistant(tool_use("b1", "Bash", command="x" * 200)), tool_result("b1", "ok")]
        digest = session_facts.build_digest(write_transcript(tmp_path / "session.jsonl", records), include_replies=False)
        assert "- [ok] " + "x" * 147 + "..." in digest

    def test_other_sessions_prompt_text_never_appears(self, isolated_config: Path) -> None:
        projects = isolated_config / "projects" / "-repo"
        write_transcript(projects / "other.jsonl", [human("private text from another project")])
        transcript = write_transcript(projects / "session.jsonl", [human("go")])
        assert "private text from another project" not in session_facts.build_digest(transcript, include_replies=True)

    def test_unreadable_lines_add_a_note_not_a_warning(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(json.dumps(human("go")) + "\nnot json\n" + json.dumps(human("more")) + "\n")
        digest = session_facts.build_digest(transcript, include_replies=False)
        assert "NOTE: 1 transcript lines could not be read, so counts may be low." in digest
        assert "FORMAT WARNING" not in digest

    @pytest.mark.parametrize(
        "damaged_line",
        [b"not json", b"\xff\xfe invalid utf-8", b"[]", b"5", b'"just a string"'],
        ids=["invalid json", "invalid utf-8", "json list", "json number", "json string"],
    )
    def test_every_kind_of_skipped_line_adds_a_note(self, tmp_path: Path, damaged_line: bytes) -> None:
        transcript = tmp_path / "session.jsonl"
        good = [json.dumps(human(text)).encode() for text in ("go", "more")]
        transcript.write_bytes(b"\n".join([good[0], damaged_line, good[1]]) + b"\n")
        digest = session_facts.build_digest(transcript, include_replies=False)
        assert "NOTE: 1 transcript lines could not be read, so counts may be low." in digest
        assert "Human prompts: 2 (" in digest

    def test_damaged_last_line_adds_no_note(self, tmp_path: Path) -> None:
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(json.dumps(human("go")) + "\n" + json.dumps(human("more"))[:20])
        assert "NOTE" not in session_facts.build_digest(transcript, include_replies=False)


class TestReplies:
    """Whether and how Claude's replies are included."""

    def test_include_replies_adds_assistant_text(self, tmp_path: Path, records: list[dict]) -> None:
        transcript = write_transcript(tmp_path / "session.jsonl", records)
        digest = session_facts.build_digest(transcript, include_replies=True)
        assert "## Claude's last message before each prompt" in digest
        assert "- Here is the comparison." in digest
        assert "FORMAT WARNING" not in digest
        assert "Subagents: 0" in digest

    def test_long_replies_are_kept_in_full_under_the_budget(self) -> None:
        reply = "word " * 1000
        lines = session_facts.reply_lines([reply])
        assert lines[1] == "- " + reply.strip()

    def test_replies_over_the_budget_are_truncated_with_a_note(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_facts, "REPLY_WORD_BUDGET", 10)
        lines = session_facts.reply_lines(["word " * 20, "short reply"])
        assert lines[1].startswith("NOTE: these 22 words of replies were truncated to about 30 characters")
        assert lines[2] == "- " + ("word " * 20)[:27] + "..."
        assert lines[3] == "- short reply"

    def test_replies_are_omitted_without_compaction_or_flag(self, tmp_path: Path) -> None:
        records = [human("first"), assistant({"type": "text", "text": "Done with first."})]
        transcript = write_transcript(tmp_path / "session.jsonl", records)
        assert "Done with first." not in session_facts.build_digest(transcript, include_replies=False)
        assert "- Done with first." in session_facts.build_digest(transcript, include_replies=True)

    def test_replies_exactly_at_the_budget_are_kept_in_full(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(session_facts, "REPLY_WORD_BUDGET", 10)
        reply = "word " * 10
        assert session_facts.reply_lines([reply]) == [
            "## Claude's last message before each prompt, and at the end",
            "- " + reply.strip(),
        ]


class TestCommandLine:
    """Running the script from the command line."""

    def test_command_line_reports_a_missing_session(self, tmp_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "session_facts.py"), "missing-id"],
            capture_output=True,
            text=True,
            env={"CLAUDE_CONFIG_DIR": str(tmp_path)},
        )
        assert result.returncode == 1
        assert "No transcript found for session 'missing-id'" in result.stderr

    def test_command_line_include_replies_flag(self, tmp_path: Path) -> None:
        records = [human("first"), assistant({"type": "text", "text": "Done with first."})]
        transcript = write_transcript(tmp_path / "session.jsonl", records)
        command = [sys.executable, str(SCRIPTS / "session_facts.py"), str(transcript)]
        assert "Done with first." not in subprocess.run(command, capture_output=True, text=True).stdout
        assert "- Done with first." in subprocess.run(command + ["--include-replies"], capture_output=True, text=True).stdout

    def test_second_session_argument_is_rejected(self, tmp_path: Path) -> None:
        first = write_transcript(tmp_path / "a.jsonl", [human("go")])
        second = write_transcript(tmp_path / "b.jsonl", [human("go")])
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "session_facts.py"), str(first), str(second)], capture_output=True, text=True
        )
        assert result.returncode == 2
        assert "unrecognized arguments" in result.stderr
