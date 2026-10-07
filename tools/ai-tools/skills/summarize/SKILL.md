---
name: summarize
description: Write a short, reviewer-first summary of a Claude Code session - what the human asked for, how much the human steered and reviewed, and what was and was not verified - for pasting into a PR or sharing with reviewers. Use whenever the user asks to summarize this session or conversation, document AI involvement or provenance, describe how much human review went into AI-generated work, or write the "how this was made" section of a PR, even if they don't say "summarize". Takes an optional word limit (default 250) and an optional session ID to summarize a different session.
argument-hint: "[word limit] [session ID]"
---

# Summarize a session

Reviewers of AI-assisted work need to know where to point their attention. A
long, thorough provenance write-up defeats that purpose because nobody reads it,
so this summary is short on purpose: say what matters, then stop.

## 1. Read the arguments

Arguments: `$ARGUMENTS`

- A bare number is the **word limit** for the summary. Default: 250. The
  session line and the prompt list do not count toward it.
- Anything else (a UUID or a path to a `.jsonl` file) is a **session to
  summarize** instead of this one. Default: this session, `${CLAUDE_SESSION_ID}`.

## 2. Get the facts from the transcript

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/session_facts.py" <session>
```

Add `--conversation` when summarizing a different session, or when the digest
reports compactions (earlier parts of this session are no longer in your
context). It adds Claude's last message before each prompt so you can see what
happened. If the digest warns that those messages were truncated, the session
was very large and details may be missing; say so in the note at the end.

The digest is the source of truth for counts, models, prompts, and which
commands ran. Your memory of the session is not: models misremember which model
they are, how many prompts there were, and whether a check actually ran. Use the
digest for facts and your context for judgment.

## 3. Write the summary

Use this structure. The word limit covers everything except the session line and
the prompt list.

```markdown
**Session:** <title, if any> (`<session ID>`) - <model(s)> - <N> prompts over <span> - <compacted K times (dates) / not compacted> - <M subagents / no subagents>

**Summary**
- <what was produced and for what purpose: only the outcomes a reviewer needs, often one item>

**Not verified**
- <claims, numbers, code paths, or sources nobody checked - the reviewer's to-do list>

**Verified**
- <what was checked, and how: human read it / test or script ran / Claude re-checked its own work>

**Human involvement:** <a few sentences of evidence, e.g. caught that the effect size came from Table 4 instead of Table 3; rejected Claude's proposed refactor of the observer; approved each edit (manual permission mode)>

<details><summary>Prompts (N)</summary>

1. <prompt, as in the digest>
...
</details>
```

Guidance for each part:

- **Session line**: facts straight from the digest. Use the model names as the
  digest gives them. Compaction matters because Claude lost the detail of
  everything before it, so give the dates.
- **Not verified** comes right after the summary because it is what a reviewer
  most needs. Be specific ("the 4.57 intercept was never checked against
  Crider 2014 Table F"), not generic ("some numbers may be wrong"). Be thorough:
  go through the whole session for claims, numbers, and changes that no test or
  human checked, checks that passed but prove little (a test suite with no real
  tests), known breakages, open decisions, and work deferred to tickets.
- **Verified**: always say *how*. "Claude re-checked" is much weaker evidence
  than "the human recomputed it" or "pytest passed", and the reader needs to
  tell them apart. A command that ran is not the same as a claim that was
  verified; only list what the command actually tested. A subagent's report that
  it checked something counts as Claude checking itself. Things that were *not*
  checked (for example "no tests ran") belong under Not verified, not here.
- **Human involvement**: report evidence, not a rating. Name each substantive
  correction or rejection specifically; "the human rejected two suggestions" tells
  a reviewer nothing, "the human rejected adding a setter and a new protocol" does.
  Other useful evidence: questions they answered, tool calls they denied or
  interrupted, and the permission mode (in `auto` or `bypassPermissions`, Claude
  acted without per-action approval; in `default` or `acceptEdits` the human
  approved some actions). Don't guess at review that happened outside the
  session; say it is unknown.
- **Prompt list**: copy every prompt from the digest as written; it already
  truncates long ones. The `<details>` tag makes the list collapsed when pasted
  into GitHub. Replace anything that looks like a credential (tokens, passwords,
  API keys, OAuth codes) with `[redacted]` and mention it in the note, since the
  summary is meant to be pasted somewhere shared.

Write plainly. No headers beyond the bold labels, no preamble, no closing
remarks. If the session was trivial, the summary can be much shorter than the
limit.

## 4. Fit the word limit without losing anything important

Reviewers rely on this summary to know what to check, so a missing
Not verified or Verified item is worse than a long summary. To fit the limit,
tighten wording and drop minor detail first. Never drop an item a reviewer would
need to act on, and when you are unsure whether an item matters, keep it. If the
important items still don't fit, go over the limit and say so in the note below.

Count the words rather than estimating; estimates are often off by 20% or more.
Write the draft to a temporary file and run:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/count_words.py" <draft file>
```

It counts only the words that count toward the limit.

## 5. Present it

Print the summary in the terminal as markdown so the user can copy it. After the
prompt list, add a short note for the user (not part of the summary, and not
counted toward the limit):

- If you went over the limit, give the counted number and why, e.g. "This is
  340 words, over the 250 limit, to keep all 9 unverified items."
- If the digest warned that Claude's messages were truncated, say the summary
  may be incomplete.
- Offer a longer version with more detail. Only write it if the user asks.
