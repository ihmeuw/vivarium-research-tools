"""List what each sub-agent in a Claude Code session opened, ran, and reported.

Usage: python3 tool_calls.py <subagents-dir> [<cutoff-timestamp>]

Reads every ``agent-<id>.jsonl`` (plus its ``.meta.json``) in the directory,
skipping any whose first record is at or after the optional ISO cutoff, and
prints, per sub-agent: its type and description, model, brief, every tool call
with its target, errored calls, and its final report. No model is involved, so
this is the cheap evidence for "what did this sub-agent actually check".
"""

import json
import sys
from pathlib import Path

BRIEF_CHARS = 400
REPORT_CHARS = 800
TARGET_CHARS = 160

# The input field that names what a tool call touched, per tool.
TARGET_KEYS = {
    "Read": ("file_path",),
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "NotebookEdit": ("notebook_path",),
    "Grep": ("pattern", "path"),
    "Glob": ("pattern", "path"),
    "Bash": ("command",),
    "WebFetch": ("url",),
    "WebSearch": ("query",),
    "Agent": ("subagent_type", "description"),
    "Skill": ("skill",),
}


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


def _clip_middle(text: str, limit: int) -> str:
    # Paths and commands carry the useful part at both ends.
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    half = (limit - 3) // 2
    return text[:half] + "..." + text[-half:]


def _target(name: str, tool_input: dict) -> str:
    keys = TARGET_KEYS.get(name)
    if keys is None:
        # MCP and other tools: show every scalar argument.
        parts = [f"{k}={v}" for k, v in tool_input.items() if isinstance(v, (str, int, float))]
    else:
        parts = [str(tool_input[k]) for k in keys if tool_input.get(k)]
    return _clip_middle(" | ".join(parts), TARGET_CHARS)


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def _started_at(transcript: Path) -> str:
    with transcript.open() as lines:
        return json.loads(next(lines, "{}")).get("timestamp", "")


def summarize_agent(transcript: Path) -> str:
    """Return the tool-call digest for one sub-agent transcript."""
    meta_path = transcript.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    models: set[str] = set()
    brief = ""
    calls: list[tuple[int, str, str, str]] = []
    errors: set[str] = set()
    handback = ""
    last_text = ""

    for line_number, line in enumerate(transcript.open(), 1):
        record = json.loads(line)
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
                        calls.append((line_number, block.get("id", ""), name, _target(name, tool_input)))

    lines = [
        f"## {transcript.name}",
        f"type: {meta.get('agentType', '?')} | description: {meta.get('description', '?')}",
        f"model: {', '.join(sorted(models)) or '?'}",
        f"brief: {_clip(brief, BRIEF_CHARS)}",
        f"tool calls ({len(calls)}):",
    ]
    for line_number, call_id, name, target in calls:
        flag = " [ERROR]" if call_id in errors else ""
        lines.append(f"  L{line_number} {name}: {target}{flag}")
    report_source = "handback" if handback else "last text (no handback)"
    lines.append(f"report ({report_source}): {_clip(handback or last_text, REPORT_CHARS)}")
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) not in (2, 3):
        sys.exit("usage: tool_calls.py <subagents-dir> [<cutoff-timestamp>]")
    cutoff = sys.argv[2] if len(sys.argv) == 3 else None
    transcripts = sorted(Path(sys.argv[1]).glob("agent-*.jsonl"))
    if cutoff:
        # ISO-8601 UTC timestamps compare correctly as strings.
        transcripts = [t for t in transcripts if _started_at(t) < cutoff]
    if not transcripts:
        print("no sub-agent transcripts found")
        return
    print("\n\n".join(summarize_agent(t) for t in transcripts))


if __name__ == "__main__":
    main()
