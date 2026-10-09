"""Detect when Claude Code changes how it records the facts a summary needs.

Claude Code's transcript format is internal and undocumented. Two kinds of check
catch changes to it:

- ``format_warnings`` looks inside one session for facts every session has, and
  for facts that always come in pairs.
- ``stale_facts`` looks across many sessions for a fact that appeared in older
  Claude Code versions but has stopped appearing, more often than chance would
  explain. Every digest runs it over the user's sessions from the last
  ``RECENT_DAYS`` days.

When either reports a problem, see ``transcript_format.py``.
"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

from transcript_format import (
    TRANSCRIPT_SUFFIX,
    RECORD_TYPE_KEY,
    ASSISTANT_RECORD,
    USER_RECORD,
    ORIGIN_KEY,
)
from transcript_parser import (
    transcripts_folder,
    read_records,
    timestamp_of,
    version_tuple,
    summarize_records,
    describe_subagents,
)

# The format check flags a fact only when its absence from later sessions would
# happen by chance less often than this.
CHANCE_THRESHOLD = 0.05
# Every digest runs the format check over the user's sessions from this many days.
RECENT_DAYS = 14


def recent_transcripts(days: int = RECENT_DAYS) -> list[Path]:
    """Return every main session transcript written in the last ``days`` days."""
    cutoff = time.time() - days * 24 * 60 * 60
    return sorted(
        path for path in transcripts_folder().glob(f"*/*{TRANSCRIPT_SUFFIX}") if path.stat().st_mtime >= cutoff
    )


def format_warnings(records: list[dict], facts: dict, subagent_transcripts: int = 0) -> list[str]:
    """Flag signs that Claude Code changed its transcript format.

    The tests only check the parser against hand-written records, so they cannot
    catch a format change. These checks run against the real transcript every time
    and look for facts that every real session has but the parser failed to find.

    Parameters
    ----------
    records
        All records of the main transcript.
    facts
        The facts extracted from those records by ``summarize_records``.
    subagent_transcripts
        How many subagent transcripts were found next to the main transcript.

    Returns
    -------
        One warning line per problem found; empty if the transcript looks normal.
    """
    record_types = Counter(record.get(RECORD_TYPE_KEY) for record in records)
    problems = []
    if not record_types[USER_RECORD] and not record_types[ASSISTANT_RECORD]:
        problems.append("no user or assistant records were found")
    assistant_records = [record for record in records if record.get(RECORD_TYPE_KEY) == ASSISTANT_RECORD]
    if assistant_records and not any("model" in record.get("message", {}) for record in assistant_records):
        problems.append("assistant records were found but none has a model field")
    if record_types[USER_RECORD] and not any(ORIGIN_KEY in record for record in records):
        # Non-interactive sessions (`claude -p`) never mark human prompts.
        problems.append(
            "no record marks which messages the human typed, so human prompts cannot be "
            "identified. This is expected for a non-interactive (claude -p) session"
        )
    if records and not any(timestamp_of(record) for record in records):
        problems.append("no record has a timestamp")
    # The checks below are for facts a session may legitimately lack. Each compares
    # two signals that always appear together, so a mismatch points to a rename.
    if facts["compact_summaries"] != len(facts["compactions"]):
        problems.append(
            f"found {len(facts['compactions'])} compaction records but "
            f"{facts['compact_summaries']} compaction summaries; they always come in pairs"
        )
    if facts["prompts"] and facts["permission_mode_records"] and not facts["permission_modes"]:
        problems.append("permission mode changes were recorded but no human prompt records a permission mode")
    if subagent_transcripts and not facts["subagent_calls"]:
        problems.append("subagent transcripts exist but no subagent dispatch was found")
    return [
        f"FORMAT WARNING: {problem}. If that is unexpected, the Claude Code transcript format "
        "may have changed; see transcript_format.py."
        for problem in problems
    ]


def fact_counts(transcript: Path) -> tuple[dict, list[tuple[str, int]]]:
    """Count the optional transcript facts in one session, for the format check.

    Parameters
    ----------
    transcript
        Path to the session transcript.

    Returns
    -------
        The session's extracted facts, and each optional fact's label and count.
    """
    facts = summarize_records(read_records(transcript))
    subagents = describe_subagents(transcript)
    counts = [
        ("human prompts", len(facts["prompts"])),
        ("models", len(facts["models"])),
        ("permission mode on prompts", sum(facts["permission_modes"].values())),
        ("permission mode change records", facts["permission_mode_records"]),
        ("session title (/rename)", 1 if facts["title"] else 0),
        ("skill commands (e.g. /simsci-research:summarize)", facts["slash_commands"]),
        ("files edited", len(facts["edited_files"])),
        ("shell commands", len(facts["commands"])),
        ("denied tool calls", len(facts["denials"])),
        ("interruptions (Esc)", facts["interruptions"]),
        ("answers to Claude's questions", len(facts["answers"])),
        ("subagent dispatches", len(facts["subagent_calls"])),
        ("subagent transcripts", len(subagents)),
        ("subagent types in metadata", sum(1 for subagent in subagents if subagent["has_type"])),
        ("compaction records (/compact)", len(facts["compactions"])),
        ("compaction summaries", facts["compact_summaries"]),
    ]
    return facts, counts


def stale_facts(transcripts: list[Path]) -> list[str]:
    """Find optional transcript facts that have stopped appearing across many sessions.

    A fact a session may legitimately lack (an interruption, a compaction) cannot
    show a rename in any single session. Across many sessions it can: if a fact
    appears in sessions from older Claude Code versions but in none since, the
    newer versions may record it differently. How many later sessions that takes
    depends on how common the fact is, so a fact is flagged only when its absence
    would happen by chance less than ``CHANCE_THRESHOLD`` of the time.

    Parameters
    ----------
    transcripts
        Paths to session transcripts, typically every session from recent weeks.
        Sessions without human prompts are skipped; that includes every
        non-interactive (``claude -p``) session, since those never mark them.

    Returns
    -------
        A description of each fact that has stopped appearing; empty if none has.
    """
    sessions = []
    for transcript in transcripts:
        facts, counts = fact_counts(transcript)
        if facts["prompts"]:
            sessions.append((transcript.stem, facts["version"], counts))
    flagged = []
    labels = [label for label, _ in sessions[0][2]] if sessions else []
    for index, label in enumerate(labels):
        seen_in = [(stem, version) for stem, version, counts in sessions if counts[index][1]]
        last_seen = max((version for _, version in seen_in if version), key=version_tuple, default=None)
        if not last_seen:
            continue
        later = [stem for stem, version, _ in sessions if version and version_tuple(version) > version_tuple(last_seen)]
        if not later:
            continue
        # Share of the sessions up to the last sighting that had the fact.
        earlier = [stem for stem, version, _ in sessions if version and version_tuple(version) <= version_tuple(last_seen)]
        share = sum(1 for stem, _ in seen_in if stem in earlier) / len(earlier)
        chance = (1 - share) ** len(later)
        if chance < CHANCE_THRESHOLD:
            flagged.append(
                f"{label}: last seen in {last_seen}, absent from {len(later)} later sessions "
                f"(in {share:.0%} of earlier sessions, so {chance:.0%} likely by chance)"
            )
    return flagged
