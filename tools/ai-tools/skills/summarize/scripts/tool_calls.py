"""List what a Claude Code session's human and sub-agents did, from its transcripts.

Usage:
    python3 tool_calls.py prompts <transcript> <cutoff-timestamp>
    python3 tool_calls.py agents <subagents-dir> [<cutoff-timestamp>]

``prompts`` prints from the main transcript, in order and up to the cutoff: the
session start and working directories, then every typed prompt, mid-turn
prompt, answer to a question, rejected tool call with the user's reason, slash
command, shell command the user ran, and file edited outside Claude. Messages
the harness delivers in the same records (task notifications, sub-agent reports)
are left out.

``agents`` reads every ``agent-<id>.jsonl`` (plus its ``.meta.json``) in the
directory and prints, per sub-agent in start order: its type and description, model, brief,
every tool call with its target, errored calls, and its final report. No model
is involved, so this is the cheap evidence for "what did this sub-agent
actually check". ``_trace_extractor`` sub-agents are listed like any other, but
their reports are omitted: each is a digest of another transcript, often long,
and says nothing the transcripts themselves do not.

The optional cutoff is an ISO-8601 timestamp with a timezone. Sub-agents whose
first record is at or after it are skipped, so that ``summarize`` can pass the
time it was invoked and leave out the sub-agents it spawns itself.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BRIEF_CHARS = 400
TARGET_CHARS = 160
MAX_CALLS = 40
REPORT_CHARS = 5000
PROMPT_CHARS = 1500
DIGEST_AGENT = "_trace_extractor"
# Text the harness puts in user records and queued commands; the person did not type it.
HARNESS_MARKERS = ("<task-notification>", "<agent-message")

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
    """Return when a transcript's first record was written, or None if unrecorded."""
    with transcript.open() as lines:
        timestamp = json.loads(next(lines, "{}")).get("timestamp")
    return _parse_timestamp(timestamp) if timestamp else None


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


def _cutoff(value: str) -> datetime:
    try:
        return _parse_timestamp(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid cutoff: {error}") from error


def _print_prompts(transcript: Path, cutoff: datetime) -> None:
    try:
        print(list_prompts(transcript, cutoff))
    except (ValueError, OSError) as error:
        sys.exit(f"cannot read transcript: {error}")


def _print_agents(subagents_dir: Path, cutoff: datetime | None) -> None:
    agents = []
    for transcript in subagents_dir.glob("agent-*.jsonl"):
        try:
            start = _started_at(transcript)
        except (ValueError, OSError):
            start = None
        if cutoff and start and start >= cutoff:
            continue
        agents.append((start, transcript))
    if not agents:
        print("no sub-agent transcripts found")
        return
    # Unknown start times sort last.
    agents.sort(key=lambda agent: (agent[0] is None, agent[0] or datetime.min, agent[1].name))
    print("\n\n".join(_digest(transcript, start) for start, transcript in agents))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = parser.add_subparsers(dest="mode", required=True)
    prompts = modes.add_parser("prompts", help="list the human input in the main transcript")
    prompts.add_argument("transcript", type=Path)
    prompts.add_argument("cutoff", type=_cutoff)
    agents = modes.add_parser("agents", help="list what each sub-agent opened, ran, and reported")
    agents.add_argument("subagents_dir", type=Path)
    agents.add_argument("cutoff", type=_cutoff, nargs="?")

    args = parser.parse_args()
    if args.mode == "prompts":
        _print_prompts(args.transcript, args.cutoff)
    else:
        _print_agents(args.subagents_dir, args.cutoff)


if __name__ == "__main__":
    main()
