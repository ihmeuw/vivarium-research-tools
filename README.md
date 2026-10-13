# vivarium-research-tools

Tooling for the IHME Simulation Science research team.

## Tools

Tooling that is not a Python package and is not published to PyPI lives under `tools/`.

| Directory | Purpose |
|---|---|
| `tools/ai-tools/` | Claude Code plugin (`simsci-research`): SimSci research team agent workflows |

To install the `simsci-research` plugin in Claude Code:

```text
/plugin marketplace add ihmeuw/vivarium-suite
/plugin install simsci-research@vivarium-ai-tools
```

Setup and usage are in [`tools/ai-tools/README.rst`](tools/ai-tools/README.rst).

## Releasing

The plugin is tagged (`ai-tools-v<X.Y.Z>`) and given a GitHub Release by
`.github/workflows/release-ai-tools.yml` whenever `tools/ai-tools/CHANGELOG.rst` changes on
`main`. A release can also be triggered manually via `workflow_dispatch` (useful for recovery
or retries).
