"""List what each sub-agent in a Claude Code session opened, ran, and reported.

Usage: python3 tool_calls.py <subagents-dir> [<cutoff-timestamp>]

Reads every ``agent-<id>.jsonl`` (plus its ``.meta.json``) in the directory and
prints, per sub-agent in start order: its type and description, model, brief,
every tool call with its target, errored calls, and its final report. No model
is involved, so this is the cheap evidence for "what did this sub-agent
actually check". ``_trace_extractor`` sub-agents are listed like any other, but
their reports are omitted: each is a digest of another transcript, often long,
and says nothing the transcripts themselves do not.

The optional cutoff is an ISO-8601 timestamp with a timezone. Sub-agents whose
first record is at or after it are skipped, so that ``summarize`` can pass the
time it was invoked and leave out the sub-agents it spawns itself.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

BRIEF_CHARS = 400
TARGET_CHARS = 160
MAX_CALLS = 40
REPORT_CHARS = 5000
DIGEST_AGENT = "_trace_extractor"

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


def main() -> None:
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: tool_calls.py <subagents-dir> [<cutoff-timestamp>]")
    try:
        cutoff = _parse_timestamp(sys.argv[2]) if len(sys.argv) == 3 else None
    except ValueError as error:
        sys.exit(f"invalid cutoff: {error}")

    agents = []
    for transcript in Path(sys.argv[1]).glob("agent-*.jsonl"):
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


if __name__ == "__main__":
    main()
