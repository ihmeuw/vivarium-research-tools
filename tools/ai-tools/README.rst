==========================================================
Simulation Science Research AI Tools (``simsci-research``)
==========================================================

Simulation Science Research AI Tools (``simsci-research``) is a Claude Code plugin
providing agent workflows for the IHME Simulation Science research team. The plugin
lives under ``tools/ai-tools/`` in the ``vivarium-research-tools`` repository and is
published through the ``vivarium-ai-tools`` marketplace, whose catalog lives in the
`vivarium-suite <https://github.com/ihmeuw/vivarium-suite>`_ repository.

It includes:

**Skills**

- ``/simsci-research:summarize [word limit] [session ID]``: a short, reviewer-first
  summary of a Claude Code session (what was asked, how much the human steered and
  reviewed, and what was and was not verified). Facts such as the prompts, models,
  and commands run are read from the session transcript by
  ``skills/summarize/scripts/session_facts.py``; the word limit defaults to 400.
- ``/simsci-research:jira-ticket [request]``: files one or more Story tickets in the
  SSCI Jira project from a short request or pasted meeting notes. It proposes the
  epic, drafts Description and Acceptance Criteria sections from the user's words,
  and files nothing until the user approves. It does not set the sprint or the
  assignee. It needs the ``mcp-jira`` plugin (see below).

Layout
======

- ``.claude-plugin/plugin.json`` (at the repository root): plugin manifest. It sits
  at the root so that the marketplace can use a plain ``github`` source. Its
  ``skills`` field points at ``tools/ai-tools/skills/``.
- ``tools/ai-tools/skills/``: Claude Code skills
- ``tools/ai-tools/tests/``: tests for scripts bundled with the skills
  (run ``python3 -m pytest tools/ai-tools/tests``; CI runs them on every PR that
  touches ``tools/ai-tools/`` or ``.claude-plugin/``)
- ``tools/ai-tools/CHANGELOG.rst``: history of plugin changes

Installing in Claude Code
=========================

Inside a Claude Code session:

.. code-block:: text

   /plugin marketplace add ihmeuw/vivarium-suite
   /plugin install simsci-research@vivarium-ai-tools

If you already have ``simsci`` or ``simsci-internal`` installed, the marketplace is
already added and only the second command is needed. Restart Claude Code or run
``/reload-plugins`` afterwards.

The ``jira-ticket`` skill also needs the ``mcp-jira`` plugin:

.. code-block:: text

   /plugin marketplace add ihme-internal/ihme-claude-marketplace
   /plugin install mcp-jira@ihme-claude-marketplace

The first Jira call asks you to sign in. If a later call says you need to sign in
again, run ``/mcp`` and sign in to ``mcp-jira``.
