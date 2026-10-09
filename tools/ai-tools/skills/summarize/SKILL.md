---
name: summarize
description: Write a short, reviewer-first summary of a Claude Code session, including what the human asked for, how much the human steered and reviewed, and what was and was not verified. Use whenever the user asks to summarize this session or conversation, document AI involvement or provenance, describe how much human review went into AI-generated work, or write the "how this was made" section of a PR, even if they don't say "summarize". Takes an optional word limit (default 400) and an optional session ID to summarize a different session.
argument-hint: "[word limit] [session ID]"
---

# Summarize a session

Reviewers of AI-assisted work need to know where to point their attention. A
long, thorough provenance write-up defeats that purpose because nobody reads it,
so this summary is short on purpose: say what matters, then stop.

## 1. Read the arguments

Arguments: `$ARGUMENTS`

- A bare number is the **word limit** for the summary. Default: 400. The
  Session section and the prompt list do not count toward it.
- Anything else (a UUID or a path to a `.jsonl` file) is a **session to
  summarize** instead of this one. Default: this session, `${CLAUDE_SESSION_ID}`.

## 2. Get the facts from the transcript

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/session_facts.py" <session>
```

This prints a *digest*: a short summary of the facts recorded in the session
transcript (the `.jsonl` file Claude Code writes for every session), such as the
prompts, models, commands run, and files edited.

If the arguments name a session other than this one (step 1), add
`--include-replies` to the `session_facts.py` command above. It adds Claude's
last message before each prompt so you can see what happened. Note that the
script adds these messages on its own if the session was compacted, since the
earlier details are no longer in your context either. If the digest warns that
those messages were truncated, the session was very large and details may be
missing; say so in the note at the end.

The digest is the source of truth for counts, models, prompts, and which
commands ran. Your memory of the session is not: models misremember which model
they are, how many prompts there were, and whether a check actually ran. Use the
digest for facts and your context for judgment.

## 3. Write the summary

Use this structure. Draft to fit the word limit; step 4 checks it. The limit
covers everything except the Session section and the prompt list.

```markdown
**Session**
- Title and ID: <title, if any> (`<session ID>`)
- Models: <model(s)>
- Prompts: <N> between <first and last date, as in the digest's Span line>
- Compaction: <K times (dates) / none>
- Subagents: <M / none>

**Summary**
- <what was produced and for what purpose: one short sentence per outcome; only the outcomes a reviewer needs>

**Not verified**
- <claims, numbers, code paths, or sources nobody checked - the reviewer's to-do list>

**Verified**
- <what was checked, and how: human read it / test or script ran / Claude re-checked its own work>

**Human involvement**
- <one bullet per substantive correction, rejection, or decision, e.g. caught that the effect size came from Table 4 instead of Table 3>
- <permission mode, denied tool calls, and interruptions, in one bullet>

<details><summary>Prompts (N)</summary>

1. <prompt, as in the digest>
...
</details>
```

Guidance for each part:

- **Session**: facts straight from the digest. Use the model names as the
  digest gives them. Compaction matters because Claude lost the detail of
  everything before it, so give the dates.
- **Summary**: orient the reviewer in a few seconds. Give one short sentence
  per outcome (a PR, a document, a ticket, a decision), naming PRs and tickets
  so the reviewer can find them. Unrelated outcomes never share a bullet, even
  to save words. Leave caveats and checks to the sections below rather than
  repeating them here.
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
  correction or rejection specifically; "the human rejected two suggestions"
  tells a reviewer nothing, "the human rejected adding a setter and a new
  protocol" does. List every substantive one, one bullet each. The only exception
  is several small items of the same kind, which can share a bullet, e.g.
  "questioned 6 rewritten methods line by line (`initialize_state`, ...)".
  Unrelated items never share a bullet, even to save words. Other useful
  evidence: questions they answered, tool calls they denied or interrupted, and
  the permission mode (in `auto` or `bypassPermissions`, Claude acted without
  per-action approval; in `default` or `acceptEdits` the human approved some
  actions). Don't guess at review that happened outside the session; say it is
  unknown.
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
Not verified or Verified item is worse than a long summary. Count the words
rather than estimating; estimates are often off by 20% or more. The script below
counts only the words that count toward the limit.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/count_words.py" <draft file>
```

1. Write the draft to a temporary file and count it.
2. If it is within the limit, you are done.
3. If it is over, revise once: tighten wording and drop minor detail. Never
   drop an item a reviewer would need to act on, and when you are unsure
   whether an item matters, keep it. Then count again.
4. Stop there. If it is still over, keep it as is and give the second count in
   the note below. More rounds cost time without making the summary better.

## 5. Present it

Print the summary in the terminal as markdown so the user can copy it. After the
prompt list, add a short note for the user (not part of the summary, and not
counted toward the limit):

- If you went over the limit, give the counted number and why, e.g. "This is
  520 words, over the 400 limit, to keep all 9 unverified items."
- If the digest warned that Claude's messages were truncated, say the summary
  may be incomplete.
- If the digest has any other WARNING line, quote it, say the counts in the
  summary may be wrong, and ask the user to send the warning to the maintainers
  of the `simsci-research` plugin.
- If you went over the limit or your revision in step 4 dropped detail, say how
  to get more: rerun with a higher limit, e.g. "For more detail, run
  `/simsci-research:summarize <word_count>`", where `<word_count>` is twice the
  final count from step 4. If you summarized a different session, include the
  session ID in the command.

If none of these apply, leave the note out.
