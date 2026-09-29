==========================================================
Simulation Science Research AI Tools (``simsci-research``)
==========================================================

Simulation Science Research AI Tools (``simsci-research``) is a Claude Code plugin
providing agent workflows for the IHME Simulation Science research team. The plugin
lives under ``tools/ai-tools/`` in the ``vivarium-research-tools`` repository and is
published through the ``vivarium-ai-tools`` marketplace, whose catalog lives in the
`vivarium-suite <https://github.com/ihmeuw/vivarium-suite>`_ repository.

``simsci-research`` declares the ``simsci`` plugin as a dependency and reuses its
sub-agents; installing ``simsci-research`` installs ``simsci`` too.

It includes:

**Skills**

- ``/simsci-research:summarize [word limit]`` - summarize the current session for
  reviewers. Reads the session and sub-agent transcripts rather than relying on memory,
  drafts a full account of the human prompts, what the human directed and checked,
  and what remains unverified, then compresses it to a short summary (250 words
  by default) that leads with the unverified items.

  ``summarize`` relies on where and how Claude Code stores session transcripts
  (``~/.claude/projects/<project>/<session-id>.jsonl`` plus a ``subagents/``
  directory), which Claude Code does not document and may change between releases.
  If a Claude Code update breaks transcript discovery, the skill reports that it
  cannot find the transcript rather than summarizing from memory; update step 1 of
  its ``SKILL.md`` to the new layout. ``/btw`` side questions are never written to
  the transcript, so any review done through them is not reflected in the summary.

Layout
======

- ``tools/ai-tools/.claude-plugin/plugin.json``: plugin manifest
- ``tools/ai-tools/skills/``: Claude Code skills
- ``tools/ai-tools/tests/``: pytest tests for scripts bundled with the skills
  (run ``python3 -m pytest tools/ai-tools/tests``; CI runs them on every PR that
  touches ``tools/ai-tools/``)
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
