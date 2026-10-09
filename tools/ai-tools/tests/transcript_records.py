"""Build small imitations of Claude Code transcript records for the tests.

Each record shape here was copied from a real transcript; if Claude Code changes
its format, update these records to match and fix the scripts.
"""

from __future__ import annotations

import json
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "skills" / "summarize" / "scripts"


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


def canary_session(tmp_path: Path, name: str = "canary", version: str | None = "2.1.290") -> Path:
    """Write a transcript in which every optional fact appears once."""
    records = [
        {"type": "custom-title", "customTitle": "canary"},
        {"type": "permission-mode", "permissionMode": "default"},
        human("start the canary session"),
        human("<command-name>/simsci-research:summarize</command-name>\n<command-args></command-args>"),
        assistant(
            tool_use("b1", "Bash", command="rm -rf build"),
            tool_use("e1", "Edit", file_path="/repo/a.py"),
            tool_use("q1", "AskUserQuestion", questions=[]),
            tool_use("d1", "Agent", subagent_type="general-purpose", description="Look around"),
        ),
        tool_result("b1", DENIAL, is_error=True),
        tool_result("e1", "File updated"),
        tool_result("q1", 'Your questions have been answered: "Which?"="This one".'),
        {"type": "user", "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}},
        {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-10-01T11:00:00Z"},
        {"type": "user", "isCompactSummary": True, "message": {"content": "Continued."}},
    ]
    if version:
        records = [dict(record, version=version) for record in records]
    transcript = write_transcript(tmp_path / f"{name}.jsonl", records)
    subagent_folder = tmp_path / name / "subagents"
    write_transcript(subagent_folder / "agent-a1.jsonl", [assistant()])
    (subagent_folder / "agent-a1.meta.json").write_text(
        json.dumps({"agentType": "general-purpose", "description": "Look around", "toolUseId": "d1"})
    )
    return transcript
