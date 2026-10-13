"""Tests for detecting changes to Claude Code's transcript format."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import transcript_parser
import format_check
from transcript_records import (
    human,
    assistant,
    write_transcript,
    canary_session,
)


class TestFormatWarnings:
    """Warnings about one session's records."""

    def test_normal_transcript_has_no_format_warnings(self, records: list[dict], facts: dict) -> None:
        assert format_check.format_warnings(records, facts) == []

    def test_missing_origin_field_is_flagged(self) -> None:
        records = [{"type": "user", "timestamp": "2026-10-01T10:00:00Z", "message": {"content": "hello"}}]
        facts = transcript_parser.summarize_records(records)
        (warning,) = format_check.format_warnings(records, facts)
        assert "human prompts cannot be identified" in warning
        assert "claude -p" in warning

    def test_missing_model_field_is_flagged(self) -> None:
        records = [human("go"), {"type": "assistant", "timestamp": "2026-10-01T10:00:00Z", "message": {"content": []}}]
        facts = transcript_parser.summarize_records(records)
        (warning,) = format_check.format_warnings(records, facts)
        assert "none has a model field" in warning

    def test_placeholder_model_is_not_flagged(self) -> None:
        records = [human("go"), assistant(model="<synthetic>")]
        assert format_check.format_warnings(records, transcript_parser.summarize_records(records)) == []

    def test_unrecognized_records_are_flagged(self) -> None:
        records = [{"type": "something-new", "timestamp": "2026-10-01T10:00:00Z"}]
        (warning,) = format_check.format_warnings(records, transcript_parser.summarize_records(records))
        assert "no user or assistant records" in warning

    def test_unpaired_compaction_is_flagged(self) -> None:
        boundary = {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-10-01T11:00:00Z"}
        summary = {"type": "user", "isCompactSummary": True, "message": {"content": "Continued."}}
        for records in ([human("go"), boundary], [human("go"), summary]):
            facts = transcript_parser.summarize_records(records)
            (warning,) = format_check.format_warnings(records, facts)
            assert "they always come in pairs" in warning
        records = [human("go"), boundary, summary]
        assert format_check.format_warnings(records, transcript_parser.summarize_records(records)) == []

    def test_permission_mode_missing_from_prompts_is_flagged(self) -> None:
        prompt = human("go")
        del prompt["permissionMode"]
        records = [prompt, {"type": "permission-mode", "permissionMode": "auto"}]
        (warning,) = format_check.format_warnings(records, transcript_parser.summarize_records(records))
        assert "no human prompt records a permission mode" in warning

    def test_subagent_transcripts_without_dispatches_are_flagged(self) -> None:
        records = [human("go"), assistant()]
        facts = transcript_parser.summarize_records(records)
        assert format_check.format_warnings(records, facts, subagent_transcripts=0) == []
        (warning,) = format_check.format_warnings(records, facts, subagent_transcripts=2)
        assert "no subagent dispatch was found" in warning


class TestStaleFacts:
    """Facts that stopped appearing across many sessions."""

    def test_canary_session_has_no_stale_facts(self, tmp_path: Path) -> None:
        assert format_check.stale_facts([canary_session(tmp_path)]) == []

    def test_fact_that_stopped_appearing_is_flagged(self, tmp_path: Path) -> None:
        older = canary_session(tmp_path, "older", "2.1.290")
        newer = canary_session(tmp_path, "newer", "2.1.291")
        newer.write_text(newer.read_text().replace("[Request interrupted by user]", "[Interrupted]"))
        assert format_check.stale_facts([older, newer]) == [
            "interruptions (Esc): last seen in 2.1.290, absent from 1 later sessions "
            "(in 100% of earlier sessions, so 0% likely by chance)"
        ]

    def test_absence_likely_by_chance_is_not_flagged(self, tmp_path: Path) -> None:
        with_fact = canary_session(tmp_path, "with", "2.1.290")
        without_fact = canary_session(tmp_path, "without", "2.1.290")
        newer = canary_session(tmp_path, "newer", "2.1.291")
        for transcript in (without_fact, newer):
            transcript.write_text(transcript.read_text().replace("[Request interrupted by user]", "[Interrupted]"))
        # In half of the earlier sessions, so one later session without it is 50% likely by chance.
        assert format_check.stale_facts([with_fact, without_fact, newer]) == []

    def test_sessions_without_human_prompts_are_skipped(self, tmp_path: Path) -> None:
        older = canary_session(tmp_path, "older", "2.1.290")
        # A newer non-interactive session lacks nearly every fact; counting it would flag them all.
        non_interactive = write_transcript(
            tmp_path / "newer.jsonl",
            [{"type": "user", "version": "2.1.291", "timestamp": "2026-10-01T10:00:00Z", "message": {"content": "hi"}}],
        )
        assert format_check.stale_facts([older, non_interactive]) == []

    @pytest.mark.parametrize("index", range(16))
    def test_each_fact_is_flagged_when_it_stops_appearing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index: int
    ) -> None:
        older = canary_session(tmp_path, "older", "2.1.290")
        newer = canary_session(tmp_path, "newer", "2.1.291")
        real_fact_counts = format_check.fact_counts

        def without_one_fact(transcript: Path) -> tuple[dict, list[tuple[str, int]]]:
            facts, counts = real_fact_counts(transcript)
            if transcript == newer:
                counts = [(label, 0 if position == index else count) for position, (label, count) in enumerate(counts)]
            return facts, counts

        monkeypatch.setattr(format_check, "fact_counts", without_one_fact)
        label = real_fact_counts(older)[1][index][0]
        (flagged,) = format_check.stale_facts([older, newer])
        assert flagged.startswith(f"{label}: last seen in 2.1.290, absent from 1 later sessions")

    def test_versions_are_compared_as_numbers(self, tmp_path: Path) -> None:
        older = canary_session(tmp_path, "older", "2.1.9")
        newer = canary_session(tmp_path, "newer", "2.1.10")
        newer.write_text(newer.read_text().replace("[Request interrupted by user]", "[Interrupted]"))
        (flagged,) = format_check.stale_facts([older, newer])
        assert flagged.startswith("interruptions (Esc): last seen in 2.1.9")

    def test_sessions_without_a_version_are_not_later(self, tmp_path: Path) -> None:
        older = canary_session(tmp_path, "older", "2.1.290")
        unversioned = canary_session(tmp_path, "unversioned", None)
        unversioned.write_text(unversioned.read_text().replace("[Request interrupted by user]", "[Interrupted]"))
        assert format_check.stale_facts([older, unversioned]) == []

    def test_fact_in_no_session_is_not_flagged(self, tmp_path: Path) -> None:
        sessions = [canary_session(tmp_path, "older", "2.1.290"), canary_session(tmp_path, "newer", "2.1.291")]
        for transcript in sessions:
            transcript.write_text(transcript.read_text().replace("[Request interrupted by user]", "[Interrupted]"))
        assert format_check.stale_facts(sessions) == []


class TestRecentTranscripts:
    """Choosing which sessions the format check reads."""

    def test_recent_transcripts_skips_old_sessions_and_subagents(self, isolated_config: Path) -> None:
        projects = isolated_config / "projects" / "-repo"
        recent = write_transcript(projects / "recent.jsonl", [human("go")])
        old = write_transcript(projects / "old.jsonl", [human("go")])
        write_transcript(projects / "recent" / "subagents" / "agent-a1.jsonl", [assistant()])
        month_ago = old.stat().st_mtime - 30 * 24 * 60 * 60
        os.utime(old, (month_ago, month_ago))
        assert format_check.recent_transcripts() == [recent]

    def test_no_projects_folder_means_no_sessions(self, isolated_config: Path) -> None:
        assert not isolated_config.exists()
        assert format_check.recent_transcripts() == []
