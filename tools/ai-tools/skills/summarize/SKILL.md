---
name: summarize
description: "Summarize the current Claude Code session: which prompts the human gave, how much the human directed, challenged, and checked, and above all what has NOT been verified. Reads the session transcript rather than relying on memory, and compresses the result to a short, reviewer-first summary. Use when the user asks to \"summarize this session\", \"summarize my AI use\", \"write the AI summary\", or \"how much of this did I review\"."
argument-hint: "Optional: a word limit (default 250)."
allowed-tools: Read, Grep, Glob, Bash(wc -w:*), Bash(grep:*), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/tool_calls.py *), Agent(simsci:_trace_extractor)
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

**Scope ends at this skill's invocation.** Everything from the record that
invoked `summarize` onward is out of scope. Anything before a `/clear` is in a
different session's file and also out of scope; if the user expects it, say so.
`/btw` side questions never enter the transcript, so review the author did
through them is not visible; if the author mentions one, say it was not included.

## 2. Extract

**Human prompts: extract these yourself.** Grep the main transcript, with line
numbers, for every human prompt up to the `summarize` invocation, and read the
full text of each match rather than a truncated line:

- **Harness messages look like prompts.** The harness also delivers messages as
  `user` records and as the `queued_command` attachments below: task
  notifications, and sub-agent reports (`<agent-message`, often after "Another
  Claude session sent a message:"). Skip any text that contains
  `<task-notification>` or `<agent-message` wherever it appears; the person did
  not type it.
- **Typed prompts** are `user` records whose content is the person's own text
  (for example, `"role":"user","content":"`). Skip `tool_result` blocks,
  `isCompactSummary` records, and text that is only `<system-reminder>`
  content.
- **Mid-turn prompts** are never `user` records. A prompt typed while Claude was
  working is an `attachment` record with `attachment.type` `queued_command` and
  `commandMode` `prompt`, text in `attachment.prompt` (grep `"queued_command"`).
- **Answers to Claude's questions** arrive as `tool_result` blocks, not typed
  prompts, so the skip rule above would drop them. Find each `tool_use` block
  named `AskUserQuestion` and keep the `tool_result` whose `tool_use_id` matches
  its `id`; match by id, not by the result's wording, which Claude Code changes
  between releases. Also keep each rejected tool call where the user said how
  to proceed (a `tool_result` with `is_error` set whose text quotes what the
  user said). Both are decisions the author made.
- **Direct edits** by the author, outside Claude, are not prompts. Claude Code
  records a file that changed on disk after Claude read it as an `attachment`
  record with `attachment.type` `edited_text_file`, the path in `attachment.filename`,
  and the new content in `attachment.snippet` (grep `"edited_text_file"`). Keep
  each as a one-line note of the file and what changed. A formatter or another
  tool can also trigger one, so call them "edited outside Claude" unless a prompt
  says the author made the change. Claude Code only tracks files Claude opened
  with the Read tool, so a file Claude only saw through Bash (`cat`, `sed`) leaves
  no record when someone else edits it. If the main extractor shows Claude
  committing or diffing changes it never made with Edit or Write, those changes
  came from outside Claude too; note them the same way.

Keep each prompt, in order, as a one-line paraphrase with its line ref, plus a
short verbatim quote where the wording matters (a challenge, a correction, a
stated check).

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
python3 ${CLAUDE_SKILL_DIR}/scripts/tool_calls.py <subagents-dir> <cutoff>
```

Run it exactly as shown, without piping the output through `head`, `grep`, or
another filter: the script already caps what it prints and says what it cut, and
a filter would drop agents or reports silently.

`<cutoff>` is the `timestamp` field of the record in the main transcript that
invoked `summarize` (step 1), copied exactly, so sub-agents started by this
skill are excluded. The script rejects a cutoff it cannot parse. For each
sub-agent, in the order they started, it prints:

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
- **What the human directed:** the arc of the work in a few steps, including
  the files the author edited directly.
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
- Report the model from the transcript, never from memory.
- Refer to the human as "the author". Do not guess pronouns.

## 4. Compress (pass 2)

Rewrite pass 1 under the word limit given above, or **250 words** if none was
given. Keep the not-verified items first and complete - cut everything
else before cutting one of them. Count the words with `wc -w` (pass the draft on
a quoted heredoc, `wc -w <<'EOF'`) rather than estimating. The limit is hard:
while the count is over, cut and count again, and print only a draft whose last
count is at or under the limit. If the word limit is too small to hold even the
not-verified items, ask permission to exceed it.

```
**AI use:** <one sentence: tool, model(s), roughly N prompts, sub-agents if any>

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
