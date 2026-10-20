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

This skill files tickets through the `mcp-jira` plugin. If the
`mcp__plugin_mcp-jira_mcp-jira__create_issue` tool is not available, stop and
give the user these commands to run in Claude Code:

```text
/plugin marketplace add ihme-internal/ihme-claude-marketplace
/plugin install mcp-jira@ihme-claude-marketplace
```

They need to restart Claude Code or run `/reload-plugins` afterwards. If a Jira
call fails because the user needs to sign in, tell them to run `/mcp` and sign
in to `mcp-jira`, then continue from where you stopped.

## 2. Collect the request

Request: `$ARGUMENTS`

If the request is empty, ask what the tickets are about. The user can describe
the work in their own words or paste notes.

## 3. Decide how many tickets

Split the request into tickets. A good ticket is one piece of work that one
person can finish and close.

If you find more than one ticket, list the proposed titles and ask whether the
user wants that many tickets or one ticket that covers all of them. Ask before
you draft anything. A bulleted list in meeting notes often describes the steps
of one piece of work, not separate tickets, and drafting a batch the user did
not want wastes their time.

## 4. Choose the epic

Every SSCI ticket belongs to an epic, which is how the team groups work by
project. Fetch the open epics:

```text
mcp__plugin_mcp-jira_mcp-jira__search(
    jql="project = SSCI AND issuetype = Epic AND statusCategory != Done ORDER BY updated DESC",
    limit=50,
)
```

Propose the epic that best matches the request, with its key and title, and ask
the user to confirm it. If several epics fit equally well, show them and ask. If
none fit, show the full list and ask the user to pick one or give an epic key.
If the user says the tickets need no epic, file them without one and say so in
the final report.

In a batch, use the same epic for every ticket unless the user says otherwise.

## 5. Draft the tickets

These fields are fixed. Do not ask about them:

- Project: `SSCI`
- Issue type: `Story`
- Priority: `Minor`
- Assignee: none. The team assigns tickets manually in Jira.

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

## 6. Get approval

Show the user everything you will file:

- The fixed fields and the epic, once at the top.
- For each ticket: the title and the full description as it will be sent.

Then ask the user to approve. File nothing until the user says yes. If they ask
for changes, make them and show the changed tickets again.

## 7. File the tickets

File the tickets one at a time:

```text
mcp__plugin_mcp-jira_mcp-jira__create_issue(
    project="SSCI",
    issue_type="Story",
    priority="Minor",
    summary="<title>",
    description="<wiki markup description>",
    epic="<epic key>",
)
```

After each one, report its key and URL. If a call fails, stop, report the error
and which tickets were already filed, and ask the user how to continue. Do not
retry the failed call without asking, because a retry after a partial failure
can create a duplicate ticket.

End with: "Set the sprint and the assignee in Jira."
