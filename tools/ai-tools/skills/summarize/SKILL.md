---
name: summarize
description: "Summarize the current Claude Code session: which prompts the human gave, how much the human directed, challenged, and checked, and above all what has NOT been verified. Reads the session transcript rather than relying on memory, and compresses the result to a short, reviewer-first summary. Use when the user asks to \"summarize this session\", \"summarize my AI use\", \"write the AI summary\", or \"how much of this did I review\"."
argument-hint: "Optional: a word limit (default 250)."
allowed-tools: Read, Grep, Glob, Bash(wc -w:*), Agent(simsci:_trace_extractor)
---

# Summarize

Produce a short, honest account of this session for reviewers: what the human
asked for, what the human actually checked, and what nobody has checked. The
reader's question is "how much should I trust this, and where should I look?"

Word limit: $ARGUMENTS

## 1. Locate the transcript

Claude Code does not document where it stores transcripts; expect the session's
transcript at `<config-dir>/projects/*/${CLAUDE_SESSION_ID}.jsonl`, where
`<config-dir>` is `$CLAUDE_CONFIG_DIR` if set, else `~/.claude`, and glob for it.
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

- **Typed prompts** are `user` records whose content is the person's own text
  (for example, `"role":"user","content":"`). Skip `tool_result` blocks,
  `isCompactSummary` records, and text that is only `<system-reminder>` or
  `<task-notification>` content.
- **Mid-turn prompts** are never `user` records. A prompt typed while Claude was
  working is an `attachment` record with `attachment.type` `queued_command` and
  `commandMode` `prompt`, text in `attachment.prompt` (grep `"queued_command"`;
  skip those whose text is a `<task-notification>`).

Keep each prompt, in order, as a one-line paraphrase with its line ref, plus a
short verbatim quote where the wording matters (a challenge, a correction, a
stated check).

**Agent activity: delegate it.** Enumerate the sub-agent transcripts yourself
(Glob `subagents/*.meta.json`; none means no sub-agents ran). Then dispatch
`simsci:_trace_extractor` **in a single message**, one per transcript (the main transcript plus each sub-agent).
Each brief carries the absolute path; a role hint (the sub-agent's `meta.json`
`agentType` and description, or "the main session" for the main transcript);
for the main transcript only, the `subagents/` directory; and this focus:

- **Main transcript:** the distinct `message.model` values; web fetches and
  searches (URL or query); files read that are sources or data rather than code;
  and each sub-agent dispatch's description and one-line result.
- **Each sub-agent:** what it was asked to check, what it actually opened or
  recomputed, and what it reported finding.

## 3. Draft the full account (pass 1)

From the digests, build the full account for yourself - not for output:

- **Setup:** model(s) as recorded, number of human prompts, sub-agents used.
- **What the human directed:** the arc of the work in a few steps.
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
- Report the model from the transcript, never from memory.
- Refer to the human as "the author". Do not guess pronouns.

## 4. Compress (pass 2)

Rewrite pass 1 under the word limit given above, or **250 words** if none was
given. Keep the not-verified items first and complete - cut everything
else before cutting one of them. Count the words with `wc -w` (pass the draft on
a quoted heredoc, `wc -w <<'EOF'`) rather than estimating, and cut again if
over. If the
word limit is too small to hold even the not-verified items, ask permission to
exceed it.

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
