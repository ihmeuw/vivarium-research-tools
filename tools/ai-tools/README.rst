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

- ``/simsci-research:summarize`` TBD

Layout
======

- ``tools/ai-tools/.claude-plugin/plugin.json``: plugin manifest
- ``tools/ai-tools/skills/``: Claude Code skills
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
