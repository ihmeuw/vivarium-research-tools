"""Tests for reading transcripts and extracting their facts."""

from __future__ import annotations

from pathlib import Path

import pytest

import transcript_parser
from transcript_records import (
    DENIAL,
    human,
    assistant,
    tool_use,
    tool_result,
    write_transcript,
)


class TestFindTranscript:
    """Finding a session's transcript by ID or path."""

    def test_find_transcript_by_id_and_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        transcript = write_transcript(tmp_path / "projects" / "-repo" / "abc-123.jsonl", [])
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        assert transcript_parser.find_transcript("abc-123") == transcript
        assert transcript_parser.find_transcript(str(transcript)) == transcript
        with pytest.raises(FileNotFoundError):
            transcript_parser.find_transcript("missing")

    def test_find_transcript_rejects_duplicate_ids(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        write_transcript(tmp_path / "projects" / "-repo-a" / "abc-123.jsonl", [])
        write_transcript(tmp_path / "projects" / "-repo-b" / "abc-123.jsonl", [])
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
        with pytest.raises(ValueError, match="Multiple transcripts found for session 'abc-123'"):
            transcript_parser.find_transcript("abc-123")

    def test_path_that_is_not_a_file_or_id_is_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="No transcript found"):
            transcript_parser.find_transcript(str(tmp_path / "missing.jsonl"))

    def test_home_folder_in_a_path_is_expanded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        transcript = write_transcript(tmp_path / "session.jsonl", [])
        assert transcript_parser.find_transcript("~/session.jsonl") == transcript


class TestReadRecords:
    """Reading the JSON records of a transcript."""

    def test_malformed_lines_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "session.jsonl"
        path.write_text('{"type": "custom-title", "customTitle": "ok"}\nnot json\n')
        assert transcript_parser.read_records(path) == [{"type": "custom-title", "customTitle": "ok"}]

    def test_undecodable_bytes_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "session.jsonl"
        path.write_bytes(b'{"type": "custom-title", "customTitle": "ok"}\n\xff\xfe damaged\n')
        assert transcript_parser.read_records(path) == [{"type": "custom-title", "customTitle": "ok"}]

    def test_json_that_is_not_an_object_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "session.jsonl"
        path.write_text('[]\n5\n"text"\n{"type": "custom-title", "customTitle": "ok"}\n')
        assert transcript_parser.read_records(path) == [{"type": "custom-title", "customTitle": "ok"}]

    def test_empty_file_has_no_records(self, tmp_path: Path) -> None:
        path = tmp_path / "session.jsonl"
        path.write_text("")
        assert transcript_parser.read_records(path) == []

    def test_unreadable_lines_before_the_last_are_counted(self, tmp_path: Path) -> None:
        path = tmp_path / "session.jsonl"
        path.write_text('{"type": "a"}\nnot json\n{"type": "b"}\n{"type": "c", "trun')
        records, unreadable = transcript_parser.read_records_and_skips(path)
        assert records == [{"type": "a"}, {"type": "b"}]
        # The damaged last line may still be being written, so it is not counted.
        assert unreadable == 1

    def test_blank_lines_are_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "session.jsonl"
        path.write_text('{"type": "a"}\n\n   \n{"type": "b"}\n\n')
        assert transcript_parser.read_records_and_skips(path) == ([{"type": "a"}, {"type": "b"}], 0)


class TestSummarizeRecords:
    """Extracting facts from a transcript's records."""

    def test_only_human_prompts_are_collected(self, facts: dict) -> None:
        texts = [text for _, text in facts["prompts"]]
        assert texts == ["Compare Tessema and Crider effect sizes", "/simsci:pr-prep open the PR"]

    def test_permission_mode_recorded_per_prompt(self, facts: dict) -> None:
        assert facts["permission_modes"] == {"default": 1, "auto": 1}

    def test_command_statuses(self, facts: dict) -> None:
        assert facts["commands"] == [
            ("pytest tests/", "ok"),
            ("rm -rf build", "denied"),
            ("cat notes.txt", "ok"),
            ("python check.py", "failed"),
        ]

    def test_denials_require_the_marker_at_the_start(self, facts: dict) -> None:
        assert facts["denials"] == ["Bash"]

    def test_synthetic_models_are_ignored(self, facts: dict) -> None:
        assert facts["models"] == {"claude-opus-5-5": 2}

    def test_edited_files_are_deduplicated(self, facts: dict) -> None:
        assert facts["edited_files"] == ["/repo/model.py"]

    def test_answers_interruptions_and_compactions(self, facts: dict) -> None:
        assert facts["answers"] == ['Your questions have been answered: "Which table?"="Table 3".']
        assert facts["interruptions"] == 1
        assert len(facts["compactions"]) == 1
        assert facts["title"] == "folate update"

    def test_replies_keep_only_the_last_message_of_each_turn(self) -> None:
        facts = transcript_parser.summarize_records(
            [
                human("first"),
                assistant({"type": "text", "text": "Let me look."}),
                assistant({"type": "text", "text": "Done with first."}),
                human("second"),
                assistant({"type": "text", "text": "Done with second."}),
            ]
        )
        assert [reply for reply in facts["replies"] if reply] == ["Done with first.", "Done with second."]

    def test_slash_command_without_arguments(self) -> None:
        facts = transcript_parser.summarize_records(
            [human("<command-message>clear</command-message>\n<command-name>/clear</command-name>")]
        )
        assert [text for _, text in facts["prompts"]] == ["/clear"]

    def test_bare_summarize_invocation_is_dropped(self) -> None:
        facts = transcript_parser.summarize_records(
            [human("<command-name>/summarize</command-name>\n<command-args></command-args>")]
        )
        assert facts["prompts"] == []
        # Still counted as a slash command, which the format check relies on.
        assert facts["slash_commands"] == 1

    def test_non_bash_tool_errors_are_counted(self) -> None:
        facts = transcript_parser.summarize_records(
            [assistant(tool_use("t1", "Read", file_path="/missing")), tool_result("t1", "File not found", is_error=True)]
        )
        assert facts["tool_errors"] == 1
        assert facts["commands"] == []

    def test_result_without_matching_call_is_an_unknown_tool(self) -> None:
        facts = transcript_parser.summarize_records([tool_result("orphan", DENIAL, is_error=True)])
        assert facts["denials"] == ["unknown tool"]

    def test_newest_version_is_recorded(self) -> None:
        records = [dict(human("a"), version="2.1.9"), dict(human("b"), version="2.1.10"), dict(human("c"), version="dev")]
        assert transcript_parser.summarize_records(records)["version"] == "2.1.10"

    def test_notebook_edits_are_listed(self) -> None:
        facts = transcript_parser.summarize_records(
            [assistant(tool_use("n1", "NotebookEdit", notebook_path="/repo/model.ipynb"))]
        )
        assert facts["edited_files"] == ["/repo/model.ipynb"]

    def test_interruption_written_as_plain_text_is_counted(self) -> None:
        facts = transcript_parser.summarize_records(
            [{"type": "user", "message": {"content": "[Request interrupted by user for tool use]"}}]
        )
        assert facts["interruptions"] == 1


class TestTimestampOf:
    """Reading a record's timestamp."""

    def test_utc_timestamp_is_parsed(self) -> None:
        when = transcript_parser.timestamp_of({"timestamp": "2026-10-01T10:00:00Z"})
        assert when is not None and when.isoformat() == "2026-10-01T10:00:00+00:00"

    def test_missing_unparseable_and_non_string_timestamps_are_none(self) -> None:
        for record in ({}, {"timestamp": "yesterday"}, {"timestamp": 1727776800}, {"timestamp": None}):
            assert transcript_parser.timestamp_of(record) is None


class TestDescribeSubagents:
    """Describing the subagent transcripts next to a session."""

    def test_subagent_commands_are_capped_and_missing_meta_is_unknown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(transcript_parser, "MAX_SUBAGENT_COMMANDS_LISTED", 1)
        transcript = write_transcript(tmp_path / "session.jsonl", [human("go")])
        write_transcript(
            tmp_path / "session" / "subagents" / "agent-a1.jsonl",
            [
                assistant(tool_use("s1", "Bash", command="first")),
                tool_result("s1", "ok"),
                assistant(tool_use("s2", "Bash", command="second")),
                tool_result("s2", "ok"),
            ],
        )
        (subagent,) = transcript_parser.describe_subagents(transcript)
        assert subagent["tool_use_id"] is None
        assert not subagent["has_type"]
        assert subagent["lines"][0].startswith("- unknown type: ")
        assert subagent["lines"][1:] == ["    - [ok] first", "    - ... 1 more"]

    def test_damaged_metadata_is_treated_as_missing(self, tmp_path: Path) -> None:
        transcript = write_transcript(tmp_path / "session.jsonl", [human("go")])
        folder = tmp_path / "session" / "subagents"
        write_transcript(folder / "agent-a1.jsonl", [assistant()])
        write_transcript(folder / "agent-a2.jsonl", [assistant()])
        (folder / "agent-a1.meta.json").write_text("{not json")
        (folder / "agent-a2.meta.json").write_text("[1, 2]")
        subagents = transcript_parser.describe_subagents(transcript)
        assert [subagent["has_type"] for subagent in subagents] == [False, False]
        assert all(subagent["lines"][0].startswith("- unknown type: ") for subagent in subagents)


class TestTextHelpers:
    """Flattening and shortening text."""

    def test_text_of_handles_block_lists(self) -> None:
        assert transcript_parser.text_of([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "a b"
        assert transcript_parser.text_of(None) == ""

    def test_shorten_truncates_and_collapses_whitespace(self) -> None:
        assert transcript_parser.shorten("a\n\n b", 10) == "a b"
        assert transcript_parser.shorten("x" * 20, 10) == "xxxxxxx..."
