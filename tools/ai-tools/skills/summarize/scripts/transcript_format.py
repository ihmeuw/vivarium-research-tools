"""The Claude Code transcript format, as read by ``session_facts.py``.

Claude Code's transcripts are internal and undocumented, so a Claude Code release
can change any of the values below. Every time the skill runs, it checks the
user's sessions from the last two weeks and reports a WARNING when a fact has
stopped appearing. When a WARNING is reported, or the digest starts reporting
nonsense, compare a transcript from the newer Claude Code version in
``~/.claude/projects/`` with these values, then update them here and in the test
fixtures in ``tools/ai-tools/tests``.

Keys from Anthropic's public Messages API, such as "message", "content", and
"tool_use", are stable and used inline in ``session_facts.py`` instead.
"""

import re

# Folder layout
CONFIG_DIR_VARIABLE = "CLAUDE_CONFIG_DIR"
DEFAULT_CONFIG_FOLDER = ".claude"
TRANSCRIPTS_FOLDER = "projects"
TRANSCRIPT_SUFFIX = ".jsonl"
SUBAGENTS_FOLDER = "subagents"
SUBAGENT_TRANSCRIPT_PATTERN = "agent-*.jsonl"
SUBAGENT_META_SUFFIX = ".meta.json"
SUBAGENT_TYPE_KEY = "agentType"
SUBAGENT_DESCRIPTION_KEY = "description"
SUBAGENT_TOOL_USE_KEY = "toolUseId"

# Record types and fields
RECORD_TYPE_KEY = "type"
TIMESTAMP_KEY = "timestamp"
VERSION_KEY = "version"
TITLE_RECORD = "custom-title"
TITLE_KEY = "customTitle"
SYSTEM_RECORD = "system"
SUBTYPE_KEY = "subtype"
COMPACTION_SUBTYPE = "compact_boundary"
ASSISTANT_RECORD = "assistant"
USER_RECORD = "user"
COMPACT_SUMMARY_KEY = "isCompactSummary"
ORIGIN_KEY = "origin"
ORIGIN_KIND_KEY = "kind"
HUMAN_ORIGIN = "human"
PERMISSION_MODE_KEY = "permissionMode"
# Separate records that log each permission mode change.
PERMISSION_MODE_RECORD = "permission-mode"
# Placeholder model names such as "<synthetic>" are not real models.
PLACEHOLDER_MODEL_PREFIX = "<"

# Text markers and tool names
DENIAL_MARKER = "The user doesn't want to proceed with this tool use"
INTERRUPT_MARKER = "[Request interrupted by user"
BASH_TOOL = "Bash"
BASH_COMMAND_KEY = "command"
QUESTION_TOOL = "AskUserQuestion"
# Older Claude Code versions called the subagent tool "Task".
SUBAGENT_TOOLS = {"Agent", "Task"}
SUBAGENT_TYPE_INPUT_KEY = "subagent_type"
SUBAGENT_DESCRIPTION_INPUT_KEY = "description"
FILE_EDIT_TOOLS = {"Write", "Edit", "NotebookEdit"}
FILE_PATH_KEY = "file_path"
NOTEBOOK_PATH_KEY = "notebook_path"
COMMAND_NAME_PATTERN = re.compile(r"<command-name>(.*?)</command-name>", re.S)
COMMAND_ARGS_PATTERN = re.compile(r"<command-args>(.*?)</command-args>", re.S)
# Invocations of this skill are not part of the work being summarized.
SKILL_COMMAND_PATTERN = re.compile(r"<command-name>/?(simsci-research:)?summarize</command-name>")
