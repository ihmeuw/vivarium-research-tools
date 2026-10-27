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
  epic, asks who to assign the tickets to and whether to add them to the active
  sprint, drafts Description and Acceptance Criteria sections from the user's
  words, and files nothing until the user approves. It uses the Jira MCP server
  of the ``simsci`` plugin (see below).

A ``SessionStart`` hook adds a short plain-English writing text
(``tools/ai-tools/hooks/writing-style.txt``), based on ASD-STE100 Simplified
Technical English, to the start of each session. It is the same text that the
``simsci-internal`` plugin adds. The text does not name the standard, because in
evals, naming it made the output less clear and less complete. Replies, PR text,
tickets, and commit messages from the main session then follow it. The hook runs
again after ``/clear`` and after compaction. Subagents do not get the text. The
hook runs through ``bash``, which on Windows means Git Bash. To disable the hook,
set ``SIMSCI_WRITING_STYLE=off`` in the environment that starts Claude Code, or
under ``env`` in ``~/.claude/settings.json``. This setting also disables the
``simsci-internal`` hook.

Layout
======

- ``.claude-plugin/plugin.json`` (at the repository root): plugin manifest,
  including the ``simsci`` dependency. It sits at the root so that the
  marketplace can use a plain ``github`` source. Its
  ``skills`` field points at ``tools/ai-tools/skills/`` and its ``hooks`` field
  points at ``tools/ai-tools/hooks/hooks.json``.
- ``tools/ai-tools/skills/``: Claude Code skills
- ``tools/ai-tools/hooks/``: the ``SessionStart`` hook that adds the writing-style
  text to each session
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

``simsci-research`` depends on the ``simsci`` plugin, so the install also
installs ``simsci`` and its ``github`` plugin dependency. ``simsci`` provides the
Jira MCP server that the ``jira-ticket`` skill uses, plus generic developer
workflows such as ``/simsci:pr-prep`` and ``/simsci:git-rescue``.

The Jira MCP server needs this setup once. The ``simsci`` README has the full
steps.

1. Install `uv <https://docs.astral.sh/uv/>`_ and check that ``uv --version``
   works.
2. Create a Jira personal access token: in Jira, click your avatar, then
   **Profile** > **Personal Access Tokens** > **Create token**.
3. Enter the token in ``/plugin`` > **Installed** > **simsci** >
   **Configure options**. Claude Code also asks for it when ``simsci`` is first
   enabled. You can leave **Default Jira project** empty, because the
   ``jira-ticket`` skill always files in SSCI.
4. Restart Claude Code and confirm in ``/mcp`` that ``plugin:simsci:jira`` is
   connected.
5. If you have the ``mcp-jira`` plugin from ``ihme-claude-marketplace``
   installed, disable it: ``/plugin disable mcp-jira@ihme-claude-marketplace``.
