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


def _run(directory: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(directory), *args], capture_output=True, text=True
    )


def test_error_flag_marks_only_the_errored_call(tmp_path: Path) -> None:
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


def test_structured_arguments_show_a_placeholder(tmp_path: Path) -> None:
    """A dict or list argument of an unmapped tool shows as a placeholder, not dropped."""
    digest = _digest(
        tmp_path, [_tool_use("t1", "mcp__jira__search", {"params": {"jql": "x"}, "limit": 5})]
    )
    assert "mcp__jira__search: params=<dict> | limit=5" in digest


def test_grep_shows_its_flags(tmp_path: Path) -> None:
    """Grep shows every argument, since flags like -i change what it searched."""
    digest = _digest(
        tmp_path, [_tool_use("t1", "Grep", {"pattern": "foo", "-i": True, "glob": "*.py"})]
    )
    assert "Grep: pattern=foo | -i=True | glob=*.py" in digest


def test_task_is_formatted_like_agent(tmp_path: Path) -> None:
    """The older Task dispatch shows its agent type and description, not its prompt."""
    digest = _digest(
        tmp_path,
        [_tool_use("t1", "Task", {"subagent_type": "reviewer", "description": "d", "prompt": "long"})],
    )
    assert "Task: reviewer | d" in digest
    assert "prompt=" not in digest


def test_report_is_not_clipped(tmp_path: Path) -> None:
    """A long final report is printed in full, since every claim in it gets checked."""
    report = "finding " * 1000
    digest = _digest(tmp_path, [_tool_use("t1", "SubagentHandback", {"message": report})])
    assert report.strip() in digest


def test_last_text_is_the_report_without_a_handback(tmp_path: Path) -> None:
    """Without a SubagentHandback, the last text is the report, labelled as such."""
    digest = _digest(tmp_path, [_text_reply("SCORE: 50")])
    assert "report (last text (no handback)): SCORE: 50" in digest


def test_later_text_replaces_earlier_text(tmp_path: Path) -> None:
    """Without a handback, only the final text reply is the report."""
    digest = _digest(tmp_path, [_text_reply("draft"), _text_reply("final")])
    assert digest.endswith("report (last text (no handback)): final")


def test_handback_wins_over_later_text(tmp_path: Path) -> None:
    """A handback is the report even when the agent writes text after it."""
    digest = _digest(
        tmp_path,
        [
            _tool_use("t1", "SubagentHandback", {"message": "official"}),
            _text_reply("recap after delivery"),
        ],
    )
    assert digest.endswith("report (handback): official")


def test_missing_meta_shows_unknown_type(tmp_path: Path) -> None:
    """Without a .meta.json, the type and description show as unknown."""
    assert "type: ? | description: ?" in _digest(tmp_path, [])


def test_calls_beyond_the_cap_are_counted(tmp_path: Path) -> None:
    """Calls past MAX_CALLS are counted, not listed."""
    total_calls = tool_calls.MAX_CALLS + 5
    records = [_tool_use(f"t{i}", "Read", {"file_path": f"/f{i}"}) for i in range(total_calls)]
    digest = _digest(tmp_path, records)
    assert f"tool calls ({total_calls}):" in digest
    assert "... 5 more calls not shown" in digest
    assert f"/f{total_calls - 1}\n" not in digest


def test_cutoff_excludes_later_agents_and_orders_by_start(tmp_path: Path) -> None:
    """Agents started at or after the cutoff are left out; the rest print in start order."""
    # Neither creation order nor name order matches start order.
    _write_agent(tmp_path, "late", [], timestamp="2026-01-01T00:00:02.000Z")
    _write_agent(tmp_path, "a-middle", [], timestamp="2026-01-01T00:00:01.000Z")
    _write_agent(tmp_path, "z-early", [], timestamp="2026-01-01T00:00:00.000Z")
    result = _run(tmp_path, "2026-01-01T00:00:02.000Z")
    assert result.returncode == 0
    assert "agent-late.jsonl" not in result.stdout
    assert result.stdout.index("agent-z-early") < result.stdout.index("agent-a-middle")


def test_cutoff_accepts_an_equivalent_offset(tmp_path: Path) -> None:
    """A cutoff written as +00:00 compares equal to the transcripts' Z timestamps."""
    _write_agent(tmp_path, "late", [], timestamp="2026-01-01T00:00:02.000Z")
    result = _run(tmp_path, "2026-01-01T00:00:02+00:00")
    assert result.stdout.strip() == "no sub-agent transcripts found"


@pytest.mark.parametrize("cutoff", ["yesterday", "2026-01-01T00:00:00"])
def test_malformed_cutoff_fails_loudly(tmp_path: Path, cutoff: str) -> None:
    """An unparseable or timezone-less cutoff exits with an error instead of filtering."""
    _write_agent(tmp_path, "a", [])
    result = _run(tmp_path, cutoff)
    assert result.returncode != 0
    assert "invalid cutoff" in result.stderr


def test_missing_timestamp_is_included_and_flagged(tmp_path: Path) -> None:
    """An agent with no start time is kept and marked, since the cutoff cannot apply."""
    _write_agent(tmp_path, "a", [], timestamp=None)
    result = _run(tmp_path, "2026-01-01T00:00:00.000Z")
    assert "agent-a.jsonl" in result.stdout
    assert "start time unknown" in result.stdout


def test_one_malformed_transcript_does_not_hide_the_others(tmp_path: Path) -> None:
    """A transcript with a bad line gets a parse-error entry; other agents still print."""
    _write_agent(tmp_path, "good", [_tool_use("t1", "Read", {"file_path": "/x"})])
    broken = _write_agent(tmp_path, "broken", [])
    broken.write_text(broken.read_text() + "{not json\n")
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "Read: /x" in result.stdout
    assert "agent-broken.jsonl\nparse error: line 2 is not valid JSON" in result.stdout


def test_empty_directory(tmp_path: Path) -> None:
    """A directory with no sub-agent transcripts says so."""
    assert _run(tmp_path).stdout.strip() == "no sub-agent transcripts found"
