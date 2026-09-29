import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "skills" / "summarize" / "scripts" / "tool_calls.py"
_spec = importlib.util.spec_from_file_location("tool_calls", SCRIPT)
tool_calls = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool_calls)

CUTOFF = "2026-01-01T01:00:00.000Z"


def _tool_use(call_id: str, name: str, tool_input: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "model": "test-model",
            "content": [{"type": "tool_use", "id": call_id, "name": name, "input": tool_input}],
        },
    }


def _text_reply(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _tool_result(call_id: str, is_error: bool = False) -> dict:
    block = {"type": "tool_result", "tool_use_id": call_id, "content": "ok"}
    if is_error:
        block["is_error"] = True
    return {"type": "user", "message": {"content": [block]}}


def _user(content: object, at: str = "2026-01-01T00:00:01.000Z", **fields: object) -> dict:
    return {"type": "user", "timestamp": at, "cwd": "/repo", "message": {"content": content}, **fields}


def _attachment(attachment: dict, at: str = "2026-01-01T00:00:01.000Z") -> dict:
    return {"type": "attachment", "timestamp": at, "attachment": attachment}


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def _write_agent(
    directory: Path,
    agent_id: str,
    records: list[dict],
    timestamp: str | None = "2026-01-01T00:00:00.000Z",
    meta: dict | None = None,
) -> Path:
    brief = {"type": "user", "message": {"content": "check the thing"}}
    if timestamp:
        brief["timestamp"] = timestamp
    transcript = directory / f"agent-{agent_id}.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in [brief, *records]) + "\n")
    if meta is not None:
        transcript.with_suffix(".meta.json").write_text(json.dumps(meta))
    return transcript


def _digest(directory: Path, records: list[dict]) -> str:
    return tool_calls.summarize_agent(_write_agent(directory, "a", records))


def _prompts(directory: Path, records: list[dict]) -> list[str]:
    transcript = directory / "session.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    listing = tool_calls.list_prompts(transcript, tool_calls._parse_timestamp(CUTOFF))
    return listing.splitlines()


class TestAgents:
    """The ``agents`` mode: what each sub-agent opened, ran, and reported."""

    def test_error_flag_marks_only_the_errored_call(self, tmp_path: Path) -> None:
        """A failed result flags its own call, matched by id, and no other."""
        digest = _digest(
            tmp_path,
            [
                _tool_use("t1", "Read", {"file_path": "/good.py"}),
                _tool_result("t1"),
                _tool_use("t2", "Read", {"file_path": "/bad.py"}),
                _tool_result("t2", is_error=True),
            ],
        )
        lines = digest.splitlines()
        assert any("/good.py" in line and "[ERROR]" not in line for line in lines)
        assert any("/bad.py" in line and line.endswith("[ERROR]") for line in lines)

    def test_structured_arguments_show_a_placeholder(self, tmp_path: Path) -> None:
        """A dict or list argument of an unmapped tool shows as a placeholder, not dropped."""
        digest = _digest(
            tmp_path, [_tool_use("t1", "mcp__jira__search", {"params": {"jql": "x"}, "limit": 5})]
        )
        assert "mcp__jira__search: params=<dict> | limit=5" in digest

    def test_grep_shows_its_flags(self, tmp_path: Path) -> None:
        """Grep shows every argument, since flags like -i change what it searched."""
        digest = _digest(
            tmp_path, [_tool_use("t1", "Grep", {"pattern": "foo", "-i": True, "glob": "*.py"})]
        )
        assert "Grep: pattern=foo | -i=True | glob=*.py" in digest

    def test_task_is_formatted_like_agent(self, tmp_path: Path) -> None:
        """The older Task dispatch shows its agent type and description, not its prompt."""
        digest = _digest(
            tmp_path,
            [
                _tool_use(
                    "t1", "Task", {"subagent_type": "reviewer", "description": "d", "prompt": "long"}
                )
            ],
        )
        assert "Task: reviewer | d" in digest
        assert "prompt=" not in digest

    def test_report_within_the_cap_is_printed_in_full(self, tmp_path: Path) -> None:
        """A report up to REPORT_CHARS is printed whole, since every claim in it gets checked."""
        report = "x" * tool_calls.REPORT_CHARS
        digest = _digest(tmp_path, [_tool_use("t1", "SubagentHandback", {"message": report})])
        assert digest.endswith(f"report (handback): {report}")

    def test_report_beyond_the_cap_is_counted(self, tmp_path: Path) -> None:
        """Characters past REPORT_CHARS are counted, not printed."""
        report = "x" * (tool_calls.REPORT_CHARS + 7)
        digest = _digest(tmp_path, [_tool_use("t1", "SubagentHandback", {"message": report})])
        assert digest.endswith(f"{'x' * tool_calls.REPORT_CHARS} ... 7 more characters not shown")

    def test_last_text_is_the_report_without_a_handback(self, tmp_path: Path) -> None:
        """Without a SubagentHandback, the last text is the report, labelled as such."""
        digest = _digest(tmp_path, [_text_reply("SCORE: 50")])
        assert "report (last text (no handback)): SCORE: 50" in digest

    def test_later_text_replaces_earlier_text(self, tmp_path: Path) -> None:
        """Without a handback, only the final text reply is the report."""
        digest = _digest(tmp_path, [_text_reply("draft"), _text_reply("final")])
        assert digest.endswith("report (last text (no handback)): final")

    def test_handback_wins_over_later_text(self, tmp_path: Path) -> None:
        """A handback is the report even when the agent writes text after it."""
        digest = _digest(
            tmp_path,
            [
                _tool_use("t1", "SubagentHandback", {"message": "official"}),
                _text_reply("recap after delivery"),
            ],
        )
        assert digest.endswith("report (handback): official")

    def test_missing_meta_shows_unknown_type(self, tmp_path: Path) -> None:
        """Without a .meta.json, the type and description show as unknown."""
        assert "type: ? | description: ?" in _digest(tmp_path, [])

    def test_calls_beyond_the_cap_are_counted(self, tmp_path: Path) -> None:
        """Calls past MAX_CALLS are counted, not listed."""
        total_calls = tool_calls.MAX_CALLS + 5
        records = [_tool_use(f"t{i}", "Read", {"file_path": f"/f{i}"}) for i in range(total_calls)]
        digest = _digest(tmp_path, records)
        assert f"tool calls ({total_calls}):" in digest
        assert "... 5 more calls not shown" in digest
        assert f"/f{total_calls - 1}\n" not in digest

    @pytest.mark.parametrize("agent_type", ["simsci:_trace_extractor", "_trace_extractor"])
    def test_trace_extractor_is_listed_with_its_report_omitted(
        self, tmp_path: Path, agent_type: str
    ) -> None:
        """A _trace_extractor, in any plugin namespace, keeps its calls but not its digest report."""
        transcript = _write_agent(
            tmp_path,
            "extractor",
            [
                _tool_use("t1", "Read", {"file_path": "/session.jsonl"}),
                _tool_use("t2", "SubagentHandback", {"message": "digest " * 10}),
            ],
            meta={"agentType": agent_type},
        )
        digest = tool_calls.summarize_agent(transcript)
        assert "Read: /session.jsonl" in digest
        assert digest.endswith(
            "report (handback): (report omitted: transcript digest, 69 characters)"
        )

    def test_other_agents_keep_their_report(self, tmp_path: Path) -> None:
        """Only _trace_extractor reports are omitted; a similarly named agent keeps its report."""
        transcript = _write_agent(
            tmp_path,
            "reviewer",
            [_tool_use("t1", "SubagentHandback", {"message": "finding"})],
            meta={"agentType": "simsci:_trace_extractor_v2"},
        )
        assert tool_calls.summarize_agent(transcript).endswith("report (handback): finding")

    def test_cutoff_excludes_later_agents_and_orders_by_start(self, tmp_path: Path) -> None:
        """Agents started at or after the cutoff are left out; the rest print in start order."""
        # Neither creation order nor name order matches start order.
        _write_agent(tmp_path, "late", [], timestamp="2026-01-01T00:00:02.000Z")
        _write_agent(tmp_path, "a-middle", [], timestamp="2026-01-01T00:00:01.000Z")
        _write_agent(tmp_path, "z-early", [], timestamp="2026-01-01T00:00:00.000Z")
        result = _cli("agents", str(tmp_path), "2026-01-01T00:00:02.000Z")
        assert result.returncode == 0
        assert "agent-late.jsonl" not in result.stdout
        assert result.stdout.index("agent-z-early") < result.stdout.index("agent-a-middle")

    def test_cutoff_accepts_an_equivalent_offset(self, tmp_path: Path) -> None:
        """A cutoff written as +00:00 compares equal to the transcripts' Z timestamps."""
        _write_agent(tmp_path, "late", [], timestamp="2026-01-01T00:00:02.000Z")
        result = _cli("agents", str(tmp_path), "2026-01-01T00:00:02+00:00")
        assert result.stdout.strip() == "no sub-agent transcripts found"

    @pytest.mark.parametrize("cutoff", ["yesterday", "2026-01-01T00:00:00"])
    def test_malformed_cutoff_fails_loudly(self, tmp_path: Path, cutoff: str) -> None:
        """An unparseable or timezone-less cutoff exits with an error instead of filtering."""
        _write_agent(tmp_path, "a", [])
        result = _cli("agents", str(tmp_path), cutoff)
        assert result.returncode != 0
        assert "invalid cutoff" in result.stderr

    def test_missing_timestamp_is_included_and_flagged(self, tmp_path: Path) -> None:
        """An agent with no start time is kept and marked, since the cutoff cannot apply."""
        _write_agent(tmp_path, "a", [], timestamp=None)
        result = _cli("agents", str(tmp_path), "2026-01-01T00:00:00.000Z")
        assert "agent-a.jsonl" in result.stdout
        assert "start time unknown" in result.stdout

    def test_one_malformed_transcript_does_not_hide_the_others(self, tmp_path: Path) -> None:
        """A transcript with a bad line gets a parse-error entry; other agents still print."""
        _write_agent(tmp_path, "good", [_tool_use("t1", "Read", {"file_path": "/x"})])
        broken = _write_agent(tmp_path, "broken", [])
        broken.write_text(broken.read_text() + "{not json\n")
        result = _cli("agents", str(tmp_path))
        assert result.returncode == 0
        assert "Read: /x" in result.stdout
        assert "agent-broken.jsonl\nparse error: line 2 is not valid JSON" in result.stdout

    def test_empty_directory(self, tmp_path: Path) -> None:
        """A directory with no sub-agent transcripts says so."""
        assert _cli("agents", str(tmp_path)).stdout.strip() == "no sub-agent transcripts found"


class TestPrompts:
    """The ``prompts`` mode: the human input in the main transcript."""

    def test_header_gives_start_and_working_directories(self, tmp_path: Path) -> None:
        """The header names the first timestamp and each distinct cwd, for the git check."""
        lines = _prompts(
            tmp_path,
            [
                {"type": "custom-title", "customTitle": "t"},
                _user("first", at="2026-01-01T00:00:00.500Z"),
                _user("second", cwd="/repo/sub"),
            ],
        )
        assert lines[:3] == [
            "session start: 2026-01-01T00:00:00.500Z",
            "working directories: /repo, /repo/sub",
            "inputs (2):",
        ]

    def test_typed_and_midturn_prompts_are_kept(self, tmp_path: Path) -> None:
        """Typed prompts, in either content form, and mid-turn prompts are listed in order."""
        lines = _prompts(
            tmp_path,
            [
                _user("review this"),
                _attachment(
                    {"type": "queued_command", "commandMode": "prompt", "prompt": "also tests"}
                ),
                _user([{"type": "text", "text": "with an image"}]),
            ],
        )
        assert lines[3:] == [
            "L1 TYPED: review this",
            "L2 MIDTURN: also tests",
            "L3 TYPED: with an image",
        ]

    def test_harness_messages_are_left_out(self, tmp_path: Path) -> None:
        """Sub-agent reports and task notifications are skipped in user records and queued commands."""
        lines = _prompts(
            tmp_path,
            [
                _user('Another Claude session sent a message: <agent-message from="a1">report'),
                _user("<task-notification><task-id>a1</task-id></task-notification>"),
                _attachment(
                    {"type": "queued_command", "commandMode": "prompt", "prompt": "<agent-message x>"}
                ),
                _attachment(
                    {"type": "queued_command", "commandMode": "task-notification", "prompt": "done"}
                ),
                _user("<system-reminder>context</system-reminder>"),
                _user("summary of earlier turns", isCompactSummary=True),
            ],
        )
        assert lines[2] == "inputs (0):"

    def test_answers_are_matched_by_question_id_not_wording(self, tmp_path: Path) -> None:
        """Only the result of an AskUserQuestion call is an answer, whatever its wording."""
        lines = _prompts(
            tmp_path,
            [
                _tool_use("q1", "AskUserQuestion", {"questions": []}),
                _user(
                    [{"type": "tool_result", "tool_use_id": "q1", "content": "Any new wording: yes"}]
                ),
                _tool_use("b1", "Bash", {"command": "ls"}),
                _user(
                    [{"type": "tool_result", "tool_use_id": "b1", "content": "Your questions ..."}]
                ),
            ],
        )
        assert lines[3:] == ["L2 ANSWER: Any new wording: yes"]

    def test_rejections_use_the_denial_field_not_error_text(self, tmp_path: Path) -> None:
        """A user rejection is listed with its reason; a failed command mentioning 'rejected' is not."""
        lines = _prompts(
            tmp_path,
            [
                _user(
                    [{"type": "tool_result", "tool_use_id": "e1", "is_error": True, "content": "no"}],
                    toolDenialKind="user-rejected",
                    userFeedback="ask me first",
                ),
                _user(
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": "e2",
                            "is_error": True,
                            "content": "! [rejected]",
                        }
                    ]
                ),
            ],
        )
        assert lines[3:] == ["L1 REJECTED TOOL CALL: ask me first"]

    def test_commands_shell_interrupts_and_edits_are_labelled(self, tmp_path: Path) -> None:
        """Slash commands, shell commands, interrupts, and edits outside Claude get their own labels."""
        lines = _prompts(
            tmp_path,
            [
                _user("<command-name>/compact</command-name>"),
                _user("<bash-input>git status</bash-input>"),
                _user("<bash-stdout>clean</bash-stdout>"),
                _user("[Request interrupted by user for tool use]"),
                _attachment({"type": "edited_text_file", "filename": "/repo/a.py", "snippet": "x"}),
            ],
        )
        assert lines[3:] == [
            "L1 COMMAND: <command-name>/compact</command-name>",
            "L2 SHELL: <bash-input>git status</bash-input>",
            "L4 INTERRUPTED: [Request interrupted by user for tool use]",
            "L5 EDITED OUTSIDE CLAUDE: /repo/a.py",
        ]

    def test_listing_stops_at_the_cutoff(self, tmp_path: Path) -> None:
        """The invocation record and everything after it are left out."""
        lines = _prompts(
            tmp_path,
            [
                _user("before"),
                _user("<command-name>/simsci-research:summarize</command-name>", at=CUTOFF),
                _user("after", at="2026-01-01T02:00:00.000Z"),
            ],
        )
        assert lines[3:] == ["L1 TYPED: before"]

    def test_malformed_cutoff_fails_loudly(self, tmp_path: Path) -> None:
        """A cutoff without a timezone exits with an error."""
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(json.dumps(_user("hi")) + "\n")
        result = _cli("prompts", str(transcript), "2026-01-01T00:00:00")
        assert result.returncode != 0
        assert "invalid cutoff" in result.stderr
