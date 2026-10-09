"""Read a Claude Code session transcript and extract the facts a summary needs.

Transcripts live at ``~/.claude/projects/<project>/<session-id>.jsonl``, one JSON
record per line. Every Claude Code-specific value this module relies on is in
``transcript_format.py``; keys from Anthropic's public Messages API, such as
"message", "content", and "tool_use", are stable and used inline.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

from transcript_format import (
    CONFIG_DIR_VARIABLE,
    DEFAULT_CONFIG_FOLDER,
    TRANSCRIPTS_FOLDER,
    TRANSCRIPT_SUFFIX,
    SUBAGENTS_FOLDER,
    SUBAGENT_TRANSCRIPT_PATTERN,
    SUBAGENT_META_SUFFIX,
    SUBAGENT_TYPE_KEY,
    SUBAGENT_DESCRIPTION_KEY,
    SUBAGENT_TOOL_USE_KEY,
    RECORD_TYPE_KEY,
    TIMESTAMP_KEY,
    VERSION_KEY,
    TITLE_RECORD,
    TITLE_KEY,
    SYSTEM_RECORD,
    SUBTYPE_KEY,
    COMPACTION_SUBTYPE,
    ASSISTANT_RECORD,
    USER_RECORD,
    COMPACT_SUMMARY_KEY,
    ORIGIN_KEY,
    ORIGIN_KIND_KEY,
    HUMAN_ORIGIN,
    PERMISSION_MODE_KEY,
    PERMISSION_MODE_RECORD,
    PLACEHOLDER_MODEL_PREFIX,
    DENIAL_MARKER,
    INTERRUPT_MARKER,
    BASH_TOOL,
    BASH_COMMAND_KEY,
    QUESTION_TOOL,
    SUBAGENT_TOOLS,
    SUBAGENT_TYPE_INPUT_KEY,
    SUBAGENT_DESCRIPTION_INPUT_KEY,
    FILE_EDIT_TOOLS,
    FILE_PATH_KEY,
    NOTEBOOK_PATH_KEY,
    COMMAND_NAME_PATTERN,
    COMMAND_ARGS_PATTERN,
    SKILL_COMMAND_PATTERN,
)

COMMAND_CHARACTER_LIMIT = 150
MAX_SUBAGENT_COMMANDS_LISTED = 8


def find_transcript(session: str) -> Path:
    """Resolve a session ID or file path to a transcript file.

    Parameters
    ----------
    session
        A session ID (UUID) or a path to a transcript ``.jsonl`` file.

    Returns
    -------
        The path to the transcript.

    Raises
    ------
    FileNotFoundError
        If no transcript matches.
    ValueError
        If more than one transcript matches.
    """
    path = Path(session).expanduser()
    if path.is_file():
        return path
    matches = sorted(transcripts_folder().glob(f"*/{session}{TRANSCRIPT_SUFFIX}"))
    if not matches:
        raise FileNotFoundError(f"No transcript found for session '{session}'")
    if len(matches) > 1:
        paths = ", ".join(str(match) for match in matches)
        raise ValueError(f"Multiple transcripts found for session '{session}': {paths}")
    return matches[0]


def transcripts_folder() -> Path:
    """Return the folder holding one subfolder of session transcripts per project."""
    config_dir = Path(os.environ.get(CONFIG_DIR_VARIABLE, Path.home() / DEFAULT_CONFIG_FOLDER))
    return config_dir / TRANSCRIPTS_FOLDER


def read_records(path: Path) -> list[dict]:
    """Read every JSON record in a transcript, skipping lines that are not one.

    A damaged line (invalid JSON, invalid UTF-8, or JSON that is not an object) is
    skipped rather than failing the whole file. Every summary also reads the
    user's other recent sessions, so one damaged file must not break them all.
    """
    records = []
    with path.open(errors="replace") as file:
        for line in file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def content_blocks(record: dict) -> list[dict]:
    """Return a record's message content as a list of blocks."""
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def text_of(block_content: object) -> str:
    """Flatten a tool result's content, which may be a string or a list of blocks."""
    if isinstance(block_content, str):
        return block_content
    if isinstance(block_content, list):
        return " ".join(str(part.get("text", "")) for part in block_content if isinstance(part, dict))
    return ""


def shorten(text: str, limit: int) -> str:
    """Collapse whitespace and truncate to ``limit`` characters."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def render_prompt(text: str) -> str:
    """Turn a slash-command record into ``/command args``; leave other text alone."""
    name = COMMAND_NAME_PATTERN.search(text)
    if not name:
        return text
    arguments = COMMAND_ARGS_PATTERN.search(text)
    return f"{name.group(1).strip()} {arguments.group(1).strip() if arguments else ''}".strip()


def timestamp_of(record: dict) -> datetime | None:
    """Return a record's timestamp, or None if it has none or it cannot be parsed."""
    value = record.get(TIMESTAMP_KEY)
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def version_tuple(version: str) -> tuple[int, ...] | None:
    """Turn a version like ``2.1.292`` into ``(2, 1, 292)``; None if it is not numeric."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return None


def summarize_records(records: list[dict]) -> dict:
    """Extract the facts the summary needs from a list of transcript records.

    Parameters
    ----------
    records
        Transcript records, in file order.

    Returns
    -------
        A dictionary of facts: prompts, answers, models, commands, edits, and counts.
    """
    tool_names: dict[str, str] = {}
    commands: dict[str, str] = {}
    facts = {
        "prompts": [],
        "answers": [],
        "models": Counter(),
        "permission_modes": Counter(),
        "commands": [],
        "edited_files": [],
        "tool_errors": 0,
        "denials": [],
        "interruptions": 0,
        "compactions": [],
        "compact_summaries": 0,
        # Plugin and skill commands typed by the human, including this skill's own.
        "slash_commands": 0,
        "permission_mode_records": 0,
        # Each subagent dispatch: the tool call ID, subagent type, and description.
        "subagent_calls": [],
        # The newest Claude Code version that wrote a record, if any.
        "version": None,
        # Claude's last message before each human prompt: what the human was reacting to.
        "replies": [None],
        "title": None,
    }
    for record in records:
        version = record.get(VERSION_KEY)
        if version and version_tuple(version) and (
            facts["version"] is None or version_tuple(version) > version_tuple(facts["version"])
        ):
            facts["version"] = version
        record_type = record.get(RECORD_TYPE_KEY)
        if record_type == TITLE_RECORD:
            facts["title"] = record.get(TITLE_KEY)
        elif record_type == PERMISSION_MODE_RECORD:
            facts["permission_mode_records"] += 1
        elif record_type == SYSTEM_RECORD:
            if record.get(SUBTYPE_KEY) == COMPACTION_SUBTYPE:
                facts["compactions"].append(timestamp_of(record))
        elif record_type == ASSISTANT_RECORD:
            model = record.get("message", {}).get("model")
            if model and not model.startswith(PLACEHOLDER_MODEL_PREFIX):
                facts["models"][model] += 1
            for block in content_blocks(record):
                if block.get("type") == "tool_use":
                    tool_names[block["id"]] = block["name"]
                    tool_input = block.get("input", {})
                    if block["name"] == BASH_TOOL:
                        commands[block["id"]] = tool_input.get(BASH_COMMAND_KEY, "")
                    elif block["name"] in SUBAGENT_TOOLS:
                        facts["subagent_calls"].append(
                            {
                                "id": block["id"],
                                "type": tool_input.get(SUBAGENT_TYPE_INPUT_KEY, "unknown type"),
                                "description": tool_input.get(SUBAGENT_DESCRIPTION_INPUT_KEY, ""),
                            }
                        )
                    elif block["name"] in FILE_EDIT_TOOLS:
                        path = tool_input.get(FILE_PATH_KEY) or tool_input.get(NOTEBOOK_PATH_KEY)
                        if path and path not in facts["edited_files"]:
                            facts["edited_files"].append(path)
                elif block.get("type") == "text" and block.get("text", "").strip():
                    facts["replies"][-1] = block["text"]
        elif record_type == USER_RECORD:
            add_user_record(record, facts, tool_names, commands)
    return facts


def add_user_record(
    record: dict, facts: dict, tool_names: dict[str, str], commands: dict[str, str]
) -> None:
    """Classify one ``user`` record: a human prompt, a tool result, or system noise.

    Records typed by the human carry ``origin.kind == "human"``. Everything else
    with ``type == "user"`` is a tool result, a system reminder, a task
    notification, or similar, and only matters for the counts below.
    """
    if record.get(COMPACT_SUMMARY_KEY):
        facts["compact_summaries"] += 1
        return
    if (record.get(ORIGIN_KEY) or {}).get(ORIGIN_KIND_KEY) == HUMAN_ORIGIN:
        text = " ".join(block.get("text", "") for block in content_blocks(record))
        if COMMAND_NAME_PATTERN.search(text):
            facts["slash_commands"] += 1
        if SKILL_COMMAND_PATTERN.search(text):
            return
        if record.get(PERMISSION_MODE_KEY):
            facts["permission_modes"][record[PERMISSION_MODE_KEY]] += 1
        facts["prompts"].append((timestamp_of(record), render_prompt(text)))
        facts["replies"].append(None)
        return
    for block in content_blocks(record):
        if block.get("type") == "text" and block.get("text", "").startswith(INTERRUPT_MARKER):
            facts["interruptions"] += 1
        if block.get("type") != "tool_result":
            continue
        tool_use_id = block.get("tool_use_id")
        tool_name = tool_names.get(tool_use_id, "unknown tool")
        result = text_of(block.get("content"))
        if result.startswith(DENIAL_MARKER):
            facts["denials"].append(tool_name)
        elif tool_name == QUESTION_TOOL:
            facts["answers"].append(result)
        elif block.get("is_error"):
            facts["tool_errors"] += 1
        if tool_use_id in commands:
            status = "denied" if result.startswith(DENIAL_MARKER) else "failed" if block.get("is_error") else "ok"
            facts["commands"].append((commands[tool_use_id], status))


def read_meta(meta_file: Path) -> dict:
    """Read a subagent's metadata file; an empty dict if it is missing or damaged."""
    if not meta_file.is_file():
        return {}
    try:
        meta = json.loads(meta_file.read_text(errors="replace"))
    except json.JSONDecodeError:
        return {}
    return meta if isinstance(meta, dict) else {}


def describe_subagents(transcript: Path) -> list[dict]:
    """Describe each subagent transcript and the shell commands it ran.

    Subagent transcripts live in ``<session-id>/subagents/agent-<id>.jsonl`` next to
    the main transcript, with a sibling ``agent-<id>.meta.json`` naming its type and
    the ID of the tool call that dispatched it.

    Parameters
    ----------
    transcript
        Path to the main session transcript.

    Returns
    -------
        One dictionary per subagent transcript, with the dispatching tool call's
        ID (``tool_use_id``, None if unknown), whether its metadata names a type
        (``has_type``), and its digest lines (``lines``).
    """
    folder = transcript.with_suffix("") / SUBAGENTS_FOLDER
    descriptions = []
    for agent_file in sorted(folder.glob(SUBAGENT_TRANSCRIPT_PATTERN)):
        meta_file = agent_file.with_suffix(SUBAGENT_META_SUFFIX)
        meta = read_meta(meta_file)
        facts = summarize_records(read_records(agent_file))
        models = ", ".join(facts["models"]) or "unknown model"
        lines = [
            f"- {meta.get(SUBAGENT_TYPE_KEY, 'unknown type')}: {meta.get(SUBAGENT_DESCRIPTION_KEY, '')} "
            f"({models}; {len(facts['commands'])} commands, "
            f"{len(facts['edited_files'])} files edited)"
        ]
        for command, status in facts["commands"][:MAX_SUBAGENT_COMMANDS_LISTED]:
            lines.append(f"    - [{status}] {shorten(command, COMMAND_CHARACTER_LIMIT)}")
        if len(facts["commands"]) > MAX_SUBAGENT_COMMANDS_LISTED:
            lines.append(f"    - ... {len(facts['commands']) - MAX_SUBAGENT_COMMANDS_LISTED} more")
        descriptions.append(
            {"tool_use_id": meta.get(SUBAGENT_TOOL_USE_KEY), "has_type": SUBAGENT_TYPE_KEY in meta, "lines": lines}
        )
    return descriptions
