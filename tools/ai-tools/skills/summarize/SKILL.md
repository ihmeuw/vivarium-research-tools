---
name: summarize
description: "Summarize the current Claude Code session: which prompts the human gave, how much the human directed, challenged, and checked, and above all what has NOT been verified. Reads the session transcript rather than relying on memory, and compresses the result to a short, reviewer-first summary. Use when the user asks to \"summarize this session\", \"summarize my AI use\", \"write the AI summary\", or \"how much of this did I review\"."
argument-hint: "Optional: a word limit (default 250)."
allowed-tools: Read, Grep, Glob, Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/tool_calls.py *), Agent(simsci:_trace_extractor)
---

# Summarize

Produce a short, honest account of this session for reviewers: what the human
asked for, what the human actually checked, and what nobody has checked. The
reader's question is "how much should I trust this, and where should I look?"

Word limit: $ARGUMENTS

## 1. Locate the transcript

Claude Code does not document where it stores transcripts; expect the session's
transcript at `<config-dir>/projects/*/${CLAUDE_SESSION_ID}.jsonl`, where
`<config-dir>` is `$CLAUDE_CONFIG_DIR` if set, else `~/.claude`, and search for
it. Use the Glob and Grep tools where they exist; some sessions lack them, so
fall back to `find` and `grep` in Bash.
Sub-agent transcripts, if any sub-agents ran, are expected in the sibling
`${CLAUDE_SESSION_ID}/subagents/` directory, one `agent-<id>.jsonl` plus
`agent-<id>.meta.json` each.

The transcript is the source of truth, not your memory of the conversation:
compaction drops early turns from context but never from the file, and the file
records the actual model on every assistant message. If the file is missing, say
so and stop - do not summarize from memory.

The file can also exist but hold only part of the session: if it is renamed,
moved, or deleted mid-session, Claude Code starts a new one at the same path
with only the records written after that. Before summarizing, treat the
transcript as partial if either is true:

- Another file named `${CLAUDE_SESSION_ID}.jsonl` plus a suffix (such as
  `.jsonl.bak`) sits beside it.
- Something in the sibling `${CLAUDE_SESSION_ID}/` directory, a sub-agent
  transcript or any other file, was last modified more than a minute before the
  transcript's first timestamped record. Compare with `stat`, whose times are
  local and whole seconds, while the transcript's are UTC; files written at
  session start (such as `custom-title.json`) can share its first second, which
  is why the margin is a minute.

If it looks partial, say which check fired and where the rest of the session
may be, and stop. Do not summarize the part that is there as if it were the
whole session.

**Scope ends at this skill's invocation.** Everything from the record that
invoked `summarize` onward is out of scope. Anything before a `/clear` is in a
different session's file and also out of scope; if the user expects it, say so.
`/btw` side questions never enter the transcript, so review the author did
through them is not visible; if the author mentions one, say it was not included.

## 2. Extract

`<cutoff>` below is always the `timestamp` field of the record in the main
transcript that invoked `summarize`, copied exactly. The script rejects a
cutoff it cannot parse. Run every script command exactly as shown, without
piping its output through `head`, `grep`, or another filter: the script already
caps what it prints and says what it cut, and a filter would drop lines
silently.

**Human input: script it.** Run:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/tool_calls.py prompts <main-transcript> <cutoff>
```

It prints the session start and the working directories, then one line per
human input up to the invocation, with its transcript line:

- `TYPED` and `MIDTURN`: prompts, including ones typed while Claude was working.
- `COMMAND`: slash commands. `SHELL`: commands the author ran with `!`.
  `INTERRUPTED`: the author stopped Claude mid-action.
- `ANSWER`: the author's answer to a question Claude asked, matched to the
  question by id rather than wording.
- `REJECTED TOOL CALL`: a tool call the author refused, with the reason they
  gave.
- `EDITED OUTSIDE CLAUDE`: a file that changed on disk after Claude read it.

It already leaves out what the harness delivers in the same records (sub-agent
reports, task notifications), system reminders, and compaction summaries. Long
inputs are clipped; where the wording matters, read the full text at that line
of the transcript. If the script fails, say so, and extract the same kinds of
input with Read and Grep.

Keep each input, in order, as a one-line paraphrase with its line ref, plus a
short verbatim quote where the wording matters (a challenge, a correction, a
stated check).

Two cautions about `EDITED OUTSIDE CLAUDE`. First, it is not always the author:
a formatter, or Claude itself writing the file through Bash (`sed -i`,
`echo >>`) rather than Edit or Write, triggers it too. Check the transcript for
a Bash command by Claude that wrote that file before counting it as the
author's. Second, Claude Code only tracks files Claude opened with the Read
tool, so an edit to a file Claude only saw through Bash (`cat`, `sed`) leaves no
record. The repository check below catches those.

**Repository state: check it on every run, short sessions included.** Work done
outside Claude, such as an edit to a file Claude never opened with Read, or a
commit and push from the author's own terminal, leaves no trace in any
transcript. The repository is the only place it shows. For each working
directory in the script's header that is inside a git repository, run these
exactly as written. Use `-C` rather than `cd`, since the session's directory may
not be the one you are in now:

```
git -C <cwd> status --short
git -C <cwd> log --since=<session start> --format='%h %an %aI %s'
```

where `<session start>` is the session start from the script's header, copied
exactly. Do not round it or widen the window: an earlier start pulls in commits
from before the session. Then compare with what the transcript shows Claude
doing:

- An uncommitted change to a file Claude never changed with Edit or Write, or
  wrote through Bash, was made outside Claude.
- A commit in the log with no matching `git commit` by Claude in the transcript
  was made outside Claude. One made after the `summarize` invocation is out of
  scope. Git prints local time with an offset (`14:28:39-06:00`) while the
  transcript uses UTC (`20:28:49.036Z`); convert before comparing.
- Only commits inside that window count. A commit from before the session that
  a push in the session dropped or overwrote (a force-push, a rebase) is not
  work found in the repository; report it as part of that push, for example
  "the force-push dropped `6d37e707c`".

This shows the repository as it is now, which may include work unrelated to the
session, so report these as "found in the repository, not made by Claude"
rather than attributing them to the author, unless a prompt says the author did
it.

**Short sessions: read directly.** If the main transcript is under 300 lines up
to the `summarize` invocation and no sub-agents ran, skip the extractor and the
sub-agent listing below: read the transcript yourself, covering the same focus
the extractor would. The two steps above still apply.

**Main-session activity: delegate it.** Dispatch one `simsci:_trace_extractor`
on the main transcript. Its brief carries the absolute path, the role hint "the
main session", the `subagents/` directory, and this focus: the distinct
`message.model` values; web fetches and searches (URL or query); files read that
are sources or data rather than code; each sub-agent dispatch's description and
one-line result; and each command run to check behavior (tests, validators,
the program itself) with what it reported.

**Sub-agent activity: script it.** While the extractor runs, list every
sub-agent's tool calls without a model:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/tool_calls.py agents <subagents-dir> <cutoff>
```

The cutoff excludes the sub-agents this skill starts. For each sub-agent, in the
order they started, it prints:

- its type and description, model, and the start of its brief;
- every tool call with its target (the file, command, URL, search query, or
  dispatched agent, and every argument of Grep, Glob, and MCP calls) and
  whether it errored, up to a call limit with a count of the rest;
- its final report, up to a character limit with a count of the rest.

"no sub-agent transcripts found" means none ran. An agent marked "parse error"
could not be read, and one marked "start time unknown" was included without
checking the cutoff. `_trace_extractor` sub-agents, such as those of an earlier
`summarize` run, are listed with their tool calls but with the report omitted:
each report is a long digest of another transcript, which you read directly
instead.

Compare each report against its tool calls. The listing shows which tools and
targets a sub-agent used, never what those calls returned. So it settles one
kind of claim on its own: a claim that the sub-agent looked at something, which
the listing either shows (it read the file, ran the command) or contradicts (it
says "verified" but opened nothing that could verify it; record that as not
verified). A claim that rests on what a call returned, such as a
value, a count, or a quoted passage, is not settled even when the right file was
opened, unless the main session checked it independently afterwards (it ran a
test or command that exercised the claim, or read the file itself; the main
extractor's verification commands show this). For the claims left, and for
agents with calls or report not shown in full or a parse error, dispatch
`simsci:_trace_extractor` on that sub-agent's transcript, with its role
hint (`agentType` and description) and the focus: what it was asked to check,
what it actually opened or recomputed, and what it reported finding.
Dispatch these in one message, at most 20 at a time (Claude Code's default
limit on concurrent sub-agents). If a dispatch is refused for the concurrency
limit, wait for earlier extractors to finish and dispatch the rest then; do not
retry refused calls immediately.

If `python3` is unavailable or the script fails outright, say so and fall back to
one extractor per sub-agent, batched the same way.

## 3. Draft the full account (pass 1)

From the digests, build the full account for yourself - not for output:

- **Setup:** model(s) as recorded, number of human prompts, sub-agents used.
- **What Claude changed outside its working copy:** every commit, push, and
  other write to shared state (a PR, an issue, a message) that Claude made, with
  its hash or link. Name force-pushes and history rewrites as such, with what
  they dropped.
- **What the human directed:** the arc of the work in a few steps, including
  the files edited and the commits made outside Claude (from the transcript and
  the repository check).
- **What the human caught:** each challenge or correction that changed a number
  or a conclusion, with its severity.
- **What automated checks caught:** sub-agent findings that changed the work.
- **What is not verified:** anything computed or asserted without a human or an
  independent check; sources cited but never opened (no read or fetch in any
  transcript); claims derived by reading rather than running; single-source
  conclusions.

Evidence rules - the account is only useful if it does not flatter the work:

- A human "verified" something only if a prompt says they did ("I checked X",
  "ran it, matches"). Reading and challenging is direction, not verification;
  say which it was.
- A sub-agent "checked" something only if its transcript shows it opened or
  recomputed it, not merely that its report says so.
- Confirm every absence before relying on it. When a not-verified item rests on
  a digest saying something did not happen (never ran, never pushed, never
  opened), grep the main transcript for it yourself: a digest can miss a step
  bundled into a larger command. If it did happen, cite the line and drop or
  correct the item.
- Confirm who acted before attributing an action. Before saying the author or
  something "outside the session" made a change, commit, or push, grep the main
  transcript for Claude doing it (for example, the `git commit` inside a longer
  Bash command). If Claude did it, say so, and keep separate what the author
  changed from what Claude then committed or pushed.
- Work from before the session start, such as an earlier commit Claude only
  looked at, is out of scope: do not list it as not verified. Mention it only
  where something in the session acted on it, such as a push that dropped it or
  a rebase onto it.
- Report the model from the transcript, never from memory.
- Refer to the human as "the author". Do not guess pronouns.

## 4. Compress (pass 2)

Rewrite pass 1 under the word limit given above, or **250 words** if none was
given. Keep the not-verified items first and complete, and keep what Claude
changed outside its working copy - cut everything else before cutting one of
them. Count the words with `wc -w` (pass the draft on
a quoted heredoc, `wc -w <<'EOF'`) rather than estimating. The limit is hard:
while the count is over, cut and count again, and print only a draft whose last
count is at or under the limit. If the word limit is too small to hold even the
not-verified items and Claude's changes, ask permission to exceed it.

```
**AI use:** <one sentence: tool, model(s), roughly N prompts, sub-agents if any>

**Claude changed:** <each commit, push, or other shared write, with hash or
link; force-pushes named as such with what they dropped; omit if none>

**Not verified**
- <most consequential first>

**Human direction and review**
- <what the author steered, caught, or checked, and how (read vs. recomputed)>

**Automated checks**
- <what sub-agents re-checked and the consequential finds; omit if none ran>
```

Output only the compressed summary, ready to paste. After it (not in it), list
any content cut to fit the word limit, then offer the full pass-1 account if the
user wants it attached; do not print it unasked.
