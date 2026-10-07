"""Print a compact digest of the facts recorded in a Claude Code session transcript.

The ``summarize`` skill runs this so that verifiable facts (what the human typed,
which models ran, what commands were executed) come from the transcript itself
rather than from the model's memory of the session.

Usage::

    python3 session_facts.py <session-id or path to .jsonl> [--conversation]

Transcripts live at ``~/.claude/projects/<project>/<session-id>.jsonl``. Each line
is one JSON record. The format is internal to Claude Code and not documented, so
if this script starts reporting nonsense after a Claude Code update, the record
shapes assumed below are the first place to look. The tests in ``tools/ai-tools/tests``
encode those assumptions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROMPT_CHARACTER_LIMIT = 300
COMMAND_CHARACTER_LIMIT = 150
# Large Claude replies are truncated to keep the digest affordable (roughly 65k tokens).
REPLY_WORD_BUDGET = 50_000
MAX_COMMANDS_LISTED = 60
MAX_SUBAGENT_COMMANDS_LISTED = 8

DENIAL_MARKER = "The user doesn't want to proceed with this tool use"
INTERRUPT_MARKER = "[Request interrupted by user"
FILE_EDIT_TOOLS = {"Write", "Edit", "NotebookEdit"}
# Invocations of this skill are not part of the work being summarized.
SKILL_COMMAND_PATTERN = re.compile(r"<command-name>/?(simsci-research:)?summarize</command-name>")


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
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    matches = sorted((config_dir / "projects").glob(f"*/{session}.jsonl"))
    if not matches:
        raise FileNotFoundError(f"No transcript found for session '{session}'")
    if len(matches) > 1:
        paths = ", ".join(str(match) for match in matches)
        raise ValueError(f"Multiple transcripts found for session '{session}': {paths}")
    return matches[0]


def read_records(path: Path) -> list[dict]:
    """Read every JSON record in a transcript, skipping malformed lines."""
    records = []
    with path.open() as file:
        for line in file:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
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
    name = re.search(r"<command-name>(.*?)</command-name>", text, re.S)
    if not name:
        return text
    arguments = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
    return f"{name.group(1).strip()} {arguments.group(1).strip() if arguments else ''}".strip()


def timestamp_of(record: dict) -> datetime | None:
    value = record.get("timestamp")
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


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
        # Claude's last message before each human prompt: what the human was reacting to.
        "replies": [None],
        "title": None,
    }
    for record in records:
        record_type = record.get("type")
        if record_type == "custom-title":
            facts["title"] = record.get("customTitle")
        elif record_type == "system":
            if record.get("subtype") == "compact_boundary":
                facts["compactions"].append(timestamp_of(record))
        elif record_type == "assistant":
            model = record.get("message", {}).get("model")
            if model and not model.startswith("<"):
                facts["models"][model] += 1
            for block in content_blocks(record):
                if block.get("type") == "tool_use":
                    tool_names[block["id"]] = block["name"]
                    tool_input = block.get("input", {})
                    if block["name"] == "Bash":
                        commands[block["id"]] = tool_input.get("command", "")
                    elif block["name"] in FILE_EDIT_TOOLS:
                        path = tool_input.get("file_path") or tool_input.get("notebook_path")
                        if path and path not in facts["edited_files"]:
                            facts["edited_files"].append(path)
                elif block.get("type") == "text" and block.get("text", "").strip():
                    facts["replies"][-1] = block["text"]
        elif record_type == "user":
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
    if record.get("isCompactSummary"):
        return
    if (record.get("origin") or {}).get("kind") == "human":
        text = " ".join(block.get("text", "") for block in content_blocks(record))
        if SKILL_COMMAND_PATTERN.search(text):
            return
        if record.get("permissionMode"):
            facts["permission_modes"][record["permissionMode"]] += 1
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
        elif tool_name == "AskUserQuestion":
            facts["answers"].append(result)
        elif block.get("is_error"):
            facts["tool_errors"] += 1
        if tool_use_id in commands:
            status = "denied" if result.startswith(DENIAL_MARKER) else "failed" if block.get("is_error") else "ok"
            facts["commands"].append((commands[tool_use_id], status))


def describe_subagents(transcript: Path) -> list[list[str]]:
    """Describe each subagent and the shell commands it ran.

    Subagent transcripts live in ``<session-id>/subagents/agent-<id>.jsonl`` next to
    the main transcript, with a sibling ``agent-<id>.meta.json`` naming its type.
    """
    folder = transcript.with_suffix("") / "subagents"
    descriptions = []
    for agent_file in sorted(folder.glob("agent-*.jsonl")):
        meta_file = agent_file.with_suffix(".meta.json")
        meta = json.loads(meta_file.read_text()) if meta_file.is_file() else {}
        facts = summarize_records(read_records(agent_file))
        models = ", ".join(facts["models"]) or "unknown model"
        lines = [
            f"- {meta.get('agentType', 'unknown type')}: {meta.get('description', '')} "
            f"({models}; {len(facts['commands'])} commands, "
            f"{len(facts['edited_files'])} files edited)"
        ]
        for command, status in facts["commands"][:MAX_SUBAGENT_COMMANDS_LISTED]:
            lines.append(f"    - [{status}] {shorten(command, COMMAND_CHARACTER_LIMIT)}")
        if len(facts["commands"]) > MAX_SUBAGENT_COMMANDS_LISTED:
            lines.append(f"    - ... {len(facts['commands']) - MAX_SUBAGENT_COMMANDS_LISTED} more")
        descriptions.append(lines)
    return descriptions


def build_digest(transcript: Path, include_conversation: bool) -> str:
    """Build the markdown digest printed for the model.

    Parameters
    ----------
    transcript
        Path to the main session transcript.
    include_conversation
        Also include Claude's last message before each human prompt, for
        summarizing a session whose details are not in the current context.
        Messages are truncated only if together they exceed ``REPLY_WORD_BUDGET``.

    Returns
    -------
        The digest as markdown text.
    """
    records = read_records(transcript)
    facts = summarize_records(records)
    timestamps = [t for t in (timestamp_of(r) for r in records) if t]
    prompts = facts["prompts"]
    failed = sum(1 for _, status in facts["commands"] if status == "failed")
    denial_counts = Counter(facts["denials"])
    subagents = describe_subagents(transcript)

    lines = [f"# Session facts: {transcript.stem}"]
    if facts["title"]:
        lines.append(f"Title: {facts['title']}")
    if timestamps:
        lines.append(
            f"Span: {min(timestamps):%Y-%m-%d %H:%M} to {max(timestamps):%Y-%m-%d %H:%M} UTC "
            f"({format_duration((max(timestamps) - min(timestamps)).total_seconds())}, including idle time)"
        )
    lines += [
        "Models: " + (", ".join(f"{m} ({n} turns)" for m, n in facts["models"].most_common()) or "none recorded"),
        "Permission mode at each prompt: "
        + (", ".join(f"{m} ({n})" for m, n in facts["permission_modes"].most_common()) or "not recorded"),
        f"Human prompts: {len(prompts)} ({sum(len(text.split()) for _, text in prompts)} words); "
        f"answers to Claude's questions: {len(facts['answers'])}; interruptions: {facts['interruptions']}",
        "Tool calls denied by the human: "
        + (", ".join(f"{name} x{n}" for name, n in denial_counts.items()) or "0"),
        f"Shell commands: {len(facts['commands'])} ({failed} failed); other tool errors: {facts['tool_errors']}",
        f"Compactions (earlier context summarized): {len(facts['compactions'])}"
        + "".join(f"; {when:%Y-%m-%d %H:%M} UTC" for when in facts["compactions"] if when),
        f"Subagents: {len(subagents)}",
        "",
        "## Human prompts (verbatim, truncated)",
    ]
    for number, (when, text) in enumerate(prompts, start=1):
        stamp = f"[{when:%H:%M}] " if when else ""
        lines.append(f"{number}. {stamp}{shorten(text, PROMPT_CHARACTER_LIMIT)}")
    if facts["answers"]:
        lines += ["", "## Human answers to Claude's questions"]
        lines += [f"- {shorten(answer, PROMPT_CHARACTER_LIMIT)}" for answer in facts["answers"]]
    lines += ["", "## Files edited by Claude"]
    lines += [f"- {path}" for path in facts["edited_files"]] or ["- none"]
    lines += ["", "## Shell commands run by Claude (status)"]
    listed = facts["commands"][-MAX_COMMANDS_LISTED:]
    if len(facts["commands"]) > MAX_COMMANDS_LISTED:
        lines.append(f"- ... {len(facts['commands']) - MAX_COMMANDS_LISTED} earlier commands omitted")
    lines += [f"- [{status}] {shorten(command, COMMAND_CHARACTER_LIMIT)}" for command, status in listed]
    if not listed:
        lines.append("- none")
    if subagents:
        lines += ["", "## Subagents"] + [line for agent in subagents for line in agent]
    if include_conversation:
        lines += ["", *conversation_lines([text for text in facts["replies"] if text])]
    return "\n".join(lines)


def conversation_lines(replies: list[str]) -> list[str]:
    """List Claude's replies in full, or truncated evenly if they exceed the budget."""
    total_words = sum(len(reply.split()) for reply in replies)
    if total_words <= REPLY_WORD_BUDGET:
        lines = ["## Claude's last message before each prompt, and at the end"]
        return lines + [f"- {' '.join(reply.split())}" for reply in replies]
    # Assume about 6 characters per word, including the space.
    character_limit = REPLY_WORD_BUDGET * 6 // len(replies)
    lines = [
        "## Claude's last message before each prompt, and at the end",
        f"WARNING: these {total_words} words of replies were truncated to about "
        f"{character_limit} characters each. Details may be missing; tell the user "
        "the summary may be incomplete.",
    ]
    return lines + [f"- {shorten(reply, character_limit)}" for reply in replies]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("session", help="session ID or path to a transcript .jsonl file")
    parser.add_argument(
        "--conversation",
        action="store_true",
        help="also print Claude's replies, for sessions not in context",
    )
    arguments = parser.parse_args()
    try:
        transcript = find_transcript(arguments.session)
    except (FileNotFoundError, ValueError) as error:
        sys.exit(str(error))
    print(build_digest(transcript, arguments.conversation))


if __name__ == "__main__":
    main()
