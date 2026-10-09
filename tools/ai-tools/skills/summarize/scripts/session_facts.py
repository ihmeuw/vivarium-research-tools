"""Print a compact digest of the facts recorded in a Claude Code session transcript.

The ``summarize`` skill runs this so that verifiable facts (what the human typed,
which models ran, what commands were executed) come from the transcript itself
rather than from the model's memory of the session.

Usage::

    python3 session_facts.py <session-id or path to .jsonl> [--include-replies]

The facts are extracted by ``transcript_parser.py``. ``format_check.py`` adds a
WARNING to the digest when Claude Code appears to have changed its transcript
format. The format values themselves are in ``transcript_format.py``.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from transcript_parser import (
    COMMAND_CHARACTER_LIMIT,
    find_transcript,
    read_records_and_skips,
    shorten,
    timestamp_of,
    summarize_records,
    describe_subagents,
)
from format_check import (
    RECENT_DAYS,
    recent_transcripts,
    format_warnings,
    stale_facts,
)

PROMPT_CHARACTER_LIMIT = 300
# Large Claude replies are truncated to keep the digest affordable (roughly 65k tokens).
REPLY_WORD_BUDGET = 50_000
MAX_COMMANDS_LISTED = 60


def format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


def build_digest(transcript: Path, include_replies: bool) -> str:
    """Build the markdown digest printed for the model.

    Parameters
    ----------
    transcript
        Path to the main session transcript.
    include_replies
        Also include Claude's last message before each human prompt, for
        summarizing a session whose details are not in the current context.
        This happens automatically if the session was compacted, since the
        details before a compaction are no longer in context either. Messages
        are truncated only if together they exceed ``REPLY_WORD_BUDGET``.

    Returns
    -------
        The digest as markdown text.
    """
    records, unreadable = read_records_and_skips(transcript)
    facts = summarize_records(records)
    timestamps = [t for t in (timestamp_of(r) for r in records) if t]
    prompts = facts["prompts"]
    failed = sum(1 for _, status in facts["commands"] if status == "failed")
    denial_counts = Counter(facts["denials"])
    subagents = describe_subagents(transcript)
    call_ids = {call["id"] for call in facts["subagent_calls"]}
    transcript_ids = {subagent["tool_use_id"] for subagent in subagents}
    # Subagents can be dispatched without a transcript here (for example, before this
    # session continued from an earlier one), or have a transcript whose dispatch is
    # not in this file. Count both.
    subagent_count = len(facts["subagent_calls"]) + sum(1 for s in subagents if s["tool_use_id"] not in call_ids)
    without_transcript = [call for call in facts["subagent_calls"] if call["id"] not in transcript_ids]

    # WARNING lines mean Claude Code may have changed its transcript format; NOTE
    # lines mean part of this session's input is missing. SKILL.md handles each.
    lines = [f"# Session facts: {transcript.stem}", *format_warnings(records, facts, len(subagents))]
    # Checks the user's recent sessions; prints nothing unless a fact has stopped appearing.
    flagged = stale_facts(recent_transcripts())
    lines += [
        f"WARNING: across your sessions from the last {RECENT_DAYS} days, {description}. The Claude Code "
        "transcript format may have changed; see transcript_format.py."
        for description in flagged
    ]
    if unreadable:
        lines.append(f"NOTE: {unreadable} transcript lines could not be read, so counts may be low.")
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
        f"Subagents: {subagent_count}"
        + (f" ({len(without_transcript)} without a transcript in this session's folder)" if without_transcript else ""),
        f"Claude Code version: {facts['version'] or 'not recorded'}",
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
    if subagents or without_transcript:
        lines += ["", "## Subagents"] + [line for subagent in subagents for line in subagent["lines"]]
        lines += [
            f"- {call['type']}: {call['description']} (no transcript in this session's folder)"
            for call in without_transcript
        ]
    if include_replies or facts["compactions"]:
        lines += ["", *reply_lines([text for text in facts["replies"] if text])]
    return "\n".join(lines)


def reply_lines(replies: list[str]) -> list[str]:
    """List Claude's replies in full, or truncated evenly if they exceed the budget."""
    total_words = sum(len(reply.split()) for reply in replies)
    if total_words <= REPLY_WORD_BUDGET:
        lines = ["## Claude's last message before each prompt, and at the end"]
        return lines + [f"- {' '.join(reply.split())}" for reply in replies]
    # Assume about 6 characters per word, including the space.
    character_limit = REPLY_WORD_BUDGET * 6 // len(replies)
    lines = [
        "## Claude's last message before each prompt, and at the end",
        f"NOTE: these {total_words} words of replies were truncated to about "
        f"{character_limit} characters each. Details may be missing; tell the user "
        "the summary may be incomplete.",
    ]
    return lines + [f"- {shorten(reply, character_limit)}" for reply in replies]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("session", help="session ID or path to a transcript .jsonl file")
    parser.add_argument(
        "--include-replies",
        action="store_true",
        help="also print Claude's replies (automatic if the session was compacted)",
    )
    arguments = parser.parse_args()
    try:
        transcript = find_transcript(arguments.session)
    except (FileNotFoundError, ValueError) as error:
        sys.exit(str(error))
    print(build_digest(transcript, arguments.include_replies))

if __name__ == "__main__":
    main()
