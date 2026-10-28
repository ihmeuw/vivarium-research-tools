---
name: jira-ticket
description: File one or more Jira tickets in the SSCI project for the Simulation Science research team, from a short request or from pasted notes. Picks the epic, drafts each ticket with Description and Acceptance Criteria sections, and files them after the user approves. Use whenever the user asks to make, open, create, write, or file a ticket, story, or Jira issue, wants to turn meeting notes or a to-do list into tickets, or wants to add work to SSCI or to the research team's board, even if they do not say "Jira".
argument-hint: "[what the ticket or tickets are about]"
---

# File SSCI tickets

Researchers typically file tickets in the SSCI project after a Zoom call or
sometimes after a Slack discussion. They know what the work is. Your job is the
structure and the filing. The content belongs to the researcher, because you
were not in the meeting and you do not know the project details they know.

## 1. Check the Jira tools

This skill files tickets through the `jira` MCP server of the `simsci` plugin,
which this plugin depends on. If the `mcp__plugin_simsci_jira__create_issue`
tool is not available, stop and give the user these steps:

1. Run `/mcp`. If `plugin:simsci:jira` shows
   `Executable not found in $PATH: "uv"`, install `uv`
   (`curl -LsSf https://astral.sh/uv/install.sh | sh`) and restart Claude Code.
   If it then says that a recent failure is cached, Claude Code waits up to 15
   minutes before it tries again. Tell the user to restart after that time.
2. If `plugin:simsci:jira` is not listed, run
   `/plugin install simsci@vivarium-ai-tools` and restart Claude Code.

If a Jira call fails with "No Jira token is set", tell the user to create a
personal access token in Jira (avatar > **Profile** > **Personal Access
Tokens** > **Create token**), enter it in `/plugin` > **Installed** >
**simsci** > **Configure options**, and restart Claude Code. Warn the user not to
paste the token into the conversation, because the token gives access to their
Jira account.

## 2. Collect the request

Request: `$ARGUMENTS`

If the request is empty, ask what the tickets are about. The user can describe
the work in their own words or paste notes.

## 3. Decide how many tickets

Assume the request is one ticket. A bulleted list in meeting notes often
describes the steps of one piece of work, not separate tickets, so do not split
a request on your own judgement.

Make more than one ticket only when the user explicitly asks for more than one,
for example "make tickets for these", "one ticket for each location", or "file
data updates, runs, and V&V tickets for Ethiopia". In that case, list the
proposed titles and ask the user to confirm them before you draft anything.

## 4. Choose the assignee and sprint

Ask who to assign the tickets to, unless the user already said. In a batch, ask
once for the whole batch. The answer can be:

- "Me": use `me`. The Jira tools assign the ticket to the owner of the Jira
  token.
- A person's name: look up their Jira username in the table below.
- A Jira username, for example `lutzes`.
- Nobody: leave the tickets unassigned.

Jira needs the username, not the person's name, and the Jira tools cannot look
up a username from a name. These are the research team's usernames:

| Name      | Jira username |
|-----------|---------------|
| Abie      | `abie`        |
| Ali       | `alibow`      |
| Alix      | `pletale`     |
| Juhi      | `juhit`       |
| Nathaniel | `ndbs`        |
| Syl       | `lutzes`      |
| Tyler     | `tylerdy`     |
| Zeb       | `zmbc`        |

If the name is not in the table, ask the user for that person's Jira username.
Do not guess it, because a wrong guess assigns the ticket to someone else or
fails.

In the same question, ask whether to add the tickets to the active SSCI sprint,
unless the user already said. If they say yes, pass `sprint="active"` when you
file them (step 8). Otherwise, leave the tickets in the backlog.

## 5. Choose the epic

Every SSCI ticket belongs to an epic, which is how the team groups work by
project. Fetch the open epics:

```text
mcp__plugin_simsci_jira__search(
    jql="project = SSCI AND issuetype = Epic AND statusCategory != Done ORDER BY updated DESC",
    limit=50,
)
```

If an epic title clearly matches the request, propose it.

Epic titles are often too vague to match. If no title clearly matches, look at
where similar tickets went. Search results do not show a ticket's epic, so do
it in two searches:

1. Find similar tickets from the last six months. Older tickets often sit in
   epics for finished phases of a project. Search for tickets with words from
   the request in the summary, and for the user's own recent tickets:

   ```text
   project = SSCI AND summary ~ "<key word>" AND updated >= -180d ORDER BY updated DESC
   project = SSCI AND (reporter = currentUser() OR assignee = currentUser()) AND updated >= -180d ORDER BY updated DESC
   ```

   If the tickets have an assignee (step 4), also search for that person's
   recent tickets.
2. For each open epic, count how many of those tickets it holds:

   ```text
   "Epic Link" = <epic key> AND key in (<similar ticket keys>)
   ```

   Run these searches with `limit=1`, because only the total matters.

Propose the epic with the most similar tickets, and say why, for example "3 of
the 5 recent hemoglobin tickets are in SSCI-2185".

Always ask the user to confirm the epic you propose, with its key and title. If
several epics fit equally well, show them and ask. If nothing points to an epic,
show the full list and ask the user to pick one or give an epic key. If the user
says the tickets need no epic, file them without one and say so in the final
report.

In a batch, use the same epic for every ticket unless the user says otherwise.

## 6. Draft the tickets

These fields are fixed. Do not ask about them:

- Project: `SSCI`
- Issue type: `Story`
- Priority: `Minor`

Each ticket has a title and a description. Keep the title short and specific,
for example "V&V for India, Folic Acid". Write the description in Jira wiki
markup, not Markdown, with exactly these two sections:

```text
h3. Description
<what the work is and why, in the user's words>

h3. Acceptance Criteria
* <what must be true for the ticket to be closed>
```

Use the user's words. You may sort what they said into the two sections, fix
spelling, and turn a run-on list into bullets. Do not add facts, steps, file
names, or criteria that the user did not give you. A plausible detail that you
made up is worse than a short ticket, because the person who picks up the
ticket cannot tell your guess from the researcher's intent.

If either section would be empty, ask the user for it. For Acceptance Criteria,
ask "What are the acceptance criteria for this ticket?".

In a batch, some requests give you nothing for the Description except the title.
In this case, ask once: "Is there a description these tickets share?". Put the
answer in the Description of every ticket in the batch. If the user has nothing
to add, use the title as the Description and do not ask again.

In a batch with no acceptance criteria, the criteria may be the same for every
ticket, or each ticket may have its own. Ask the user: "Do these tickets share
acceptance criteria, or does each ticket have its own?". If they share, put the
answer in every ticket. If each ticket has its own, ask for all of them in one
message that lists the ticket titles.

If the user says there are no acceptance criteria yet, do not suggest any. Put
this line in the Acceptance Criteria section instead, so the section still
exists and the gap is visible to whoever picks up the ticket:

```text
_To be defined._
```

Say which tickets have this placeholder when you show them for approval.

## 7. Get approval

Show the user everything you will file:

- The fixed fields, the epic, the assignee, and the sprint (active sprint or
  backlog), once at the top.
- For each ticket: the title and the full description as it will be sent.

Then ask the user to approve. File nothing until the user says yes. If they ask
for changes, make them and show the changed tickets again.

## 8. File the tickets

File the tickets one at a time:

```text
mcp__plugin_simsci_jira__create_issue(
    project="SSCI",
    issue_type="Story",
    priority="Minor",
    summary="<title>",
    description="<wiki markup description>",
    epic="<epic key>",
    assignee="<Jira username or me, or leave this out for no assignee>",
    sprint="active",  # only if the user chose the active sprint in step 4
)
```

After each one, report its key and URL. The ticket is filed even if adding it to
the sprint fails. In that case the result has a `sprint_failure` message: report
it and tell the user to set the sprint in Jira.

If a call fails, stop, report the error and which tickets were already filed,
and ask the user how to continue. Do not retry the failed call without asking,
because a retry after a partial failure can create a duplicate ticket.

If the first ticket fails because the assignee does not exist, the username is
wrong. Ask the user for the correct one.
