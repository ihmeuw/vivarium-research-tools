"""List what a Claude Code session's human and sub-agents did, from its transcripts.

Usage:
    python3 tool_calls.py prompts <session-id>
    python3 tool_calls.py agents <session-id>

Both find the session's main transcript under ``$CLAUDE_CONFIG_DIR`` (else
``~/.claude``) and take as the cutoff the last ``summarize`` invocation in it,
whether a slash command or a Skill tool call; nothing from the cutoff on is
listed.

``prompts`` first checks whether the transcript holds only part of its session
and, if so, says why and exits with status 3. Otherwise it prints the
transcript and sub-agent paths, the cutoff, the session start and working
directories, then every typed prompt, mid-turn prompt, answer to a question,
rejected tool call with the user's reason, slash command, shell command the
user ran, and file edited outside Claude. Messages the harness delivers in the
same records (task notifications, sub-agent reports) are left out.

``agents`` reads every sub-agent ``agent-<id>.jsonl`` (plus its ``.meta.json``)
started before the cutoff and prints, per sub-agent in start order: its type
and description, model, brief, every tool call with its target, errored calls,
and its final report. No model is involved, so this is the cheap evidence for
"what did this sub-agent actually check". ``_trace_extractor`` sub-agents are
listed like any other, but their reports are omitted: each is a digest of
another transcript, often long, and says nothing the transcripts themselves do
not. Sub-agents started at or after the cutoff, such as the ones ``summarize``
itself dispatches, are left out.

Transcript format
-----------------
Claude Code does not document its transcript format. Everything below was
worked out from real transcripts, and all of it lives in this file, so a Claude
Code release that changes the format is fixed here and in the tests' record
fixtures, not in ``SKILL.md``. A change usually shows up silently, as a summary
missing something, not as an error. To update, open a fresh transcript that
shows the missing kind of record, find the new shape, change the matching line
below, and update the fixture that builds that record.

- Location: ``<config-dir>/projects/<project>/<session-id>.jsonl``, with
  sub-agent transcripts in ``<session-id>/subagents/agent-<id>.jsonl`` and a
  ``.meta.json`` beside each (``config_dir``, ``find_transcript``).
- One JSON record per line, with ``type``, ``timestamp`` (UTC ISO-8601), and
  ``cwd``; conversation records carry ``message.content``, a string or a list of
  ``text``, ``tool_use``, and ``tool_result`` blocks.
- Invocation: a ``user`` record containing
  ``<command-name>/[plugin:]summarize</command-name>``, or a ``Skill`` tool call
  whose ``skill`` ends in ``summarize`` (``INVOCATION``, ``_is_invocation``).
- Mid-turn prompt: an ``attachment`` record of type ``queued_command`` with
  ``commandMode`` ``prompt``, text in ``attachment.prompt`` (``list_prompts``).
- Edit outside Claude: an ``attachment`` of type ``edited_text_file`` with
  ``attachment.filename``, recorded only for files Claude opened with Read.
- Harness messages: text containing ``<task-notification>`` or
  ``<agent-message``, in ``user`` records and queued commands
  (``HARNESS_MARKERS``).
- Answer: the ``tool_result`` whose ``tool_use_id`` is an ``AskUserQuestion``
  call's ``id``. Rejection: a ``user`` record with ``toolDenialKind`` set, the
  reason in ``userFeedback``.
- Sub-agent report: the ``message`` input of a ``SubagentHandback`` tool call;
  sub-agent type: ``agentType`` in ``.meta.json`` (``summarize_agent``,
  ``_meta``).
- Partial transcript: Claude Code starts a new file at the same path when the
  old one is renamed, moved, or deleted, so a suffixed copy beside it, or
  session files older than its first record, mean earlier turns are elsewhere
  (``partial_reasons``).
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRIEF_CHARS = 400
TARGET_CHARS = 160
MAX_CALLS = 40
REPORT_CHARS = 5000
PROMPT_CHARS = 1500
DIGEST_AGENT = "_trace_extractor"
# Text the harness puts in user records and queued commands; the person did not type it.
HARNESS_MARKERS = ("<task-notification>", "<agent-message")
# The slash command in any plugin namespace, e.g. /simsci-research:summarize.
INVOCATION = re.compile(r"<command-name>/(?:[\w-]+:)?summarize</command-name>")
PARTIAL_MARGIN = timedelta(minutes=1)

# The input fields that name what a tool call touched. Tools not listed here,
# including Grep, Glob, and MCP tools, show every argument, because their
# optional flags change what the call did.
TARGET_KEYS = {
    "Read": ("file_path",),
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "NotebookEdit": ("notebook_path",),
    "Bash": ("command",),
    "WebFetch": ("url",),
    "WebSearch": ("query",),
    "Agent": ("subagent_type", "description"),
    # Older transcripts name the sub-agent dispatch tool Task.
    "Task": ("subagent_type", "description"),
    "Skill": ("skill",),
}


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _clip(text: str, limit: int) -> str:
    text = _normalize(text)
    return text if len(text) <= limit else text[:limit] + "..."


def _clip_middle(text: str, limit: int) -> str:
    # Paths and commands carry the useful part at both ends.
    text = _normalize(text)
    if len(text) <= limit:
        return text
    half = (limit - 3) // 2
    return text[:half] + "..." + text[-half:]


def _argument(key: str, value: object) -> str:
    if isinstance(value, (str, int, float, bool)):
        return f"{key}={value}"
    return f"{key}=<{type(value).__name__}>"


def _target(name: str, tool_input: dict) -> str:
    keys = TARGET_KEYS.get(name)
    if keys is None:
        parts = [_argument(k, v) for k, v in tool_input.items()]
    else:
        parts = [str(tool_input[k]) for k in keys if tool_input.get(k)]
    return _clip_middle(" | ".join(parts), TARGET_CHARS)


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def _parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp that carries a timezone."""
    # fromisoformat only accepts a trailing Z from Python 3.11.
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp has no timezone: {value}")
    return parsed


def _started_at(transcript: Path) -> datetime | None:
    """Return a transcript's first timestamp, or None if it has none."""
    with transcript.open() as lines:
        for line in lines:
            timestamp = json.loads(line).get("timestamp")
            if timestamp:
                return _parse_timestamp(timestamp)
    return None


def _meta(transcript: Path) -> dict:
    """Return a transcript's ``.meta.json`` contents, or an empty dict if it has none."""
    meta_path = transcript.with_suffix(".meta.json")
    return json.loads(meta_path.read_text()) if meta_path.exists() else {}


def _is_digest(meta: dict) -> bool:
    # Match any plugin namespace, e.g. simsci:_trace_extractor.
    return meta.get("agentType", "").split(":")[-1] == DIGEST_AGENT


def _report(text: str) -> str:
    text = _normalize(text)
    if len(text) <= REPORT_CHARS:
        return text
    return f"{text[:REPORT_CHARS]} ... {len(text) - REPORT_CHARS} more characters not shown"


def summarize_agent(transcript: Path) -> str:
    """Return the tool-call digest for one sub-agent transcript.

    Raises
    ------
    ValueError
        If a line of the transcript is not valid JSON.
    """
    meta = _meta(transcript)
    models: set[str] = set()
    brief = ""
    calls: list[tuple[int, str, str, str]] = []
    errors: set[str] = set()
    handback = ""
    last_text = ""

    # Collect the brief, models, tool calls, failed call ids, and final report in one pass.
    with transcript.open() as lines:
        for line_number, line in enumerate(lines, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"line {line_number} is not valid JSON: {error}") from error
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if record.get("type") == "user":
                if not brief and isinstance(content, str):
                    brief = content
                if isinstance(content, list):
                    for block in content:
                        if block.get("type") == "tool_result" and block.get("is_error"):
                            errors.add(block.get("tool_use_id", ""))
            elif record.get("type") == "assistant":
                if message.get("model"):
                    models.add(message["model"])
                for block in content if isinstance(content, list) else []:
                    if block.get("type") == "text" and block.get("text", "").strip():
                        last_text = block["text"]
                    elif block.get("type") == "tool_use":
                        name, tool_input = block.get("name", ""), block.get("input") or {}
                        if name == "SubagentHandback":
                            handback = _text(tool_input.get("message", ""))
                        else:
                            calls.append(
                                (line_number, block.get("id", ""), name, _target(name, tool_input))
                            )

    # Render the header, the capped call list with error flags, and the capped report.
    lines_out = [
        f"## {transcript.name}",
        f"type: {meta.get('agentType', '?')} | description: {meta.get('description', '?')}",
        f"model: {', '.join(sorted(models)) or '?'}",
        f"brief: {_clip(brief, BRIEF_CHARS)}",
        f"tool calls ({len(calls)}):",
    ]
    for line_number, call_id, name, target in calls[:MAX_CALLS]:
        flag = " [ERROR]" if call_id in errors else ""
        lines_out.append(f"  L{line_number} {name}: {target}{flag}")
    if len(calls) > MAX_CALLS:
        lines_out.append(f"  ... {len(calls) - MAX_CALLS} more calls not shown")
    report_source = "handback" if handback else "last text (no handback)"
    report = _normalize(handback or last_text)
    if _is_digest(meta):
        report = f"(report omitted: transcript digest, {len(report)} characters)"
    else:
        report = _report(report)
    lines_out.append(f"report ({report_source}): {report}")
    return "\n".join(lines_out)


def _digest(transcript: Path, start: datetime | None) -> str:
    # One unreadable transcript must not cost the listing for every other agent.
    try:
        digest = summarize_agent(transcript)
    except (ValueError, OSError) as error:
        return f"## {transcript.name}\nparse error: {error}"
    if start is None:
        digest += "\nstart time unknown: included regardless of the cutoff"
    return digest


def _is_harness(text: str) -> bool:
    return any(marker in text for marker in HARNESS_MARKERS)


def _prompt_line(line_number: int, kind: str, text: str) -> str:
    return f"L{line_number} {kind}: {_clip(text, PROMPT_CHARS)}"


def _typed(line_number: int, text: str) -> str | None:
    stripped = text.strip()
    if not stripped or _is_harness(stripped) or stripped.startswith("<system-reminder>"):
        return None
    if stripped.startswith(("<local-command-caveat>", "<local-command-stdout>", "<bash-stdout>")):
        return None
    if "<command-name>" in stripped:
        return _prompt_line(line_number, "COMMAND", stripped)
    if stripped.startswith("<bash-input>"):
        return _prompt_line(line_number, "SHELL", stripped)
    if stripped.startswith("[Request interrupted by user"):
        return _prompt_line(line_number, "INTERRUPTED", stripped)
    return _prompt_line(line_number, "TYPED", stripped)


def list_prompts(transcript: Path, cutoff: datetime) -> str:
    """Return the human input recorded in a main transcript before the cutoff.

    Parameters
    ----------
    transcript
        The session's main ``.jsonl`` transcript.
    cutoff
        When ``summarize`` was invoked; the first record at or after it ends the
        listing.

    Returns
    -------
        The session start, working directories, and one line per human input.

    Raises
    ------
    ValueError
        If a line of the transcript is not valid JSON.
    """
    start = ""
    cwds: list[str] = []
    question_ids: set[str] = set()
    entries: list[str] = []

    # Classify each record as human input, harness traffic, or neither.
    with transcript.open() as lines:
        for line_number, line in enumerate(lines, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"line {line_number} is not valid JSON: {error}") from error
            timestamp = record.get("timestamp")
            if timestamp:
                if _parse_timestamp(timestamp) >= cutoff:
                    break
                start = start or timestamp
            if record.get("cwd") and record["cwd"] not in cwds:
                cwds.append(record["cwd"])

            if record.get("type") == "attachment":
                attachment = record.get("attachment") or {}
                prompt = attachment.get("prompt")
                if (
                    attachment.get("type") == "queued_command"
                    and attachment.get("commandMode") == "prompt"
                    and isinstance(prompt, str)
                    and not _is_harness(prompt)
                ):
                    entries.append(_prompt_line(line_number, "MIDTURN", prompt))
                elif attachment.get("type") == "edited_text_file":
                    entries.append(
                        f"L{line_number} EDITED OUTSIDE CLAUDE: {attachment.get('filename', '?')}"
                    )
                continue

            message = record.get("message")
            if not isinstance(message, dict) or record.get("isCompactSummary"):
                continue
            content = message.get("content")
            if record.get("type") == "assistant" and isinstance(content, list):
                question_ids.update(
                    block.get("id", "")
                    for block in content
                    if block.get("type") == "tool_use" and block.get("name") == "AskUserQuestion"
                )
            elif record.get("type") == "user":
                if record.get("toolDenialKind"):
                    reason = record.get("userFeedback") or "(no reason given)"
                    entries.append(_prompt_line(line_number, "REJECTED TOOL CALL", reason))
                    continue
                if isinstance(content, str):
                    entry = _typed(line_number, content)
                    if entry:
                        entries.append(entry)
                    continue
                for block in content if isinstance(content, list) else []:
                    if block.get("type") == "tool_result":
                        if block.get("tool_use_id") in question_ids:
                            entries.append(
                                _prompt_line(line_number, "ANSWER", _text(block.get("content")))
                            )
                    elif block.get("type") == "text":
                        entry = _typed(line_number, block.get("text", ""))
                        if entry:
                            entries.append(entry)

    header = [
        f"session start: {start or '?'}",
        f"working directories: {', '.join(cwds) or '?'}",
        f"inputs ({len(entries)}):",
    ]
    return "\n".join(header + entries)


def config_dir() -> Path:
    """Return Claude Code's configuration directory: ``$CLAUDE_CONFIG_DIR``, else ``~/.claude``."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def find_transcript(session_id: str) -> Path:
    """Return the main transcript of a session.

    Raises
    ------
    FileNotFoundError
        If no transcript for the session exists under the configuration directory.
    """
    matches = sorted((config_dir() / "projects").glob(f"*/{session_id}.jsonl"))
    if not matches:
        raise FileNotFoundError(
            f"no transcript for session {session_id} under {config_dir() / 'projects'}"
        )
    return matches[0]


def _is_invocation(record: dict) -> bool:
    message = record.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if record.get("type") == "user":
        return bool(INVOCATION.search(_text(content)))
    if record.get("type") == "assistant" and isinstance(content, list):
        # A natural-language request reaches the skill through the Skill tool.
        return any(
            block.get("type") == "tool_use"
            and block.get("name") == "Skill"
            and str((block.get("input") or {}).get("skill", "")).split(":")[-1] == "summarize"
            for block in content
        )
    return False


def find_cutoff(transcript: Path) -> tuple[datetime, int]:
    """Return when ``summarize`` was last invoked in a transcript, and on which line.

    Raises
    ------
    ValueError
        If the transcript has no timestamped ``summarize`` invocation, or a line is
        not valid JSON.
    """
    found: tuple[datetime, int] | None = None
    with transcript.open() as lines:
        for line_number, line in enumerate(lines, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"line {line_number} is not valid JSON: {error}") from error
            if record.get("timestamp") and _is_invocation(record):
                found = (_parse_timestamp(record["timestamp"]), line_number)
    if found is None:
        raise ValueError(f"no summarize invocation found in {transcript}")
    return found


def partial_reasons(transcript: Path) -> list[str]:
    """Return why a transcript looks like only part of its session; empty if it looks whole.

    Claude Code starts a new transcript at the same path when the old one is
    renamed, moved, or deleted mid-session, so a leftover copy beside it, or
    session files older than its first record, mean earlier turns are elsewhere.
    """
    reasons = [
        f"another copy of the transcript exists: {sibling}"
        for sibling in sorted(transcript.parent.glob(f"{transcript.name}.*"))
    ]
    first = _started_at(transcript)
    session_dir = transcript.parent / transcript.stem
    if first and session_dir.is_dir():
        for path in sorted(p for p in session_dir.rglob("*") if p.is_file()):
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            # Files written at session start share its first second; a minute of
            # margin keeps them from counting.
            if modified < first - PARTIAL_MARGIN:
                reasons.append(
                    f"{path} was last modified at {modified.isoformat()}, before the"
                    f" transcript's first record at {first.isoformat()}"
                )
    return reasons


def _agents_before(subagents_dir: Path, cutoff: datetime) -> list[tuple[datetime | None, Path]]:
    """Return the sub-agent transcripts started before the cutoff, in start order."""
    agents = []
    for transcript in subagents_dir.glob("agent-*.jsonl"):
        try:
            start = _started_at(transcript)
        except (ValueError, OSError):
            start = None
        if start and start >= cutoff:
            continue
        agents.append((start, transcript))
    # Unknown start times sort last.
    agents.sort(key=lambda agent: (agent[0] is None, agent[0] or datetime.min, agent[1].name))
    return agents


def _print_prompts(session_id: str) -> None:
    transcript = find_transcript(session_id)
    reasons = partial_reasons(transcript)
    if reasons:
        print("PARTIAL TRANSCRIPT: stop, do not summarize")
        print("\n".join(f"- {reason}" for reason in reasons))
        sys.exit(3)
    cutoff, line_number = find_cutoff(transcript)
    subagents_dir = transcript.parent / session_id / "subagents"
    print(f"transcript: {transcript}")
    print(
        f"sub-agents directory: {subagents_dir}"
        f" ({len(_agents_before(subagents_dir, cutoff))} before the cutoff)"
    )
    print(f"cutoff: {cutoff.isoformat()} (line {line_number})")
    print(f"lines before the cutoff: {line_number - 1}")
    print(list_prompts(transcript, cutoff))


def _print_agents(session_id: str) -> None:
    transcript = find_transcript(session_id)
    cutoff, _ = find_cutoff(transcript)
    agents = _agents_before(transcript.parent / session_id / "subagents", cutoff)
    if not agents:
        print("no sub-agent transcripts found")
        return
    print("\n\n".join(_digest(path, start) for start, path in agents))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = parser.add_subparsers(dest="mode", required=True)
    prompts = modes.add_parser("prompts", help="list the human input in the main transcript")
    prompts.add_argument("session_id")
    agents = modes.add_parser("agents", help="list what each sub-agent opened, ran, and reported")
    agents.add_argument("session_id")

    args = parser.parse_args()
    try:
        if args.mode == "prompts":
            _print_prompts(args.session_id)
        else:
            _print_agents(args.session_id)
    except (ValueError, OSError) as error:
        sys.exit(f"cannot read transcript: {error}")


if __name__ == "__main__":
    main()
