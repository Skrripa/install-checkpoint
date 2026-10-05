---
description: Vet an install command, package, MCP server, plugin or skill before it runs
argument-hint: <command, package name or link>
---

Ask the `install-checkpoint:install-reviewer` agent to review this before anything is installed:

$ARGUMENTS

Show the human the agent's verdict table.

If Install Checkpoint already paused a command, it gave a review id and a file path. Save the agent's
`VERDICT / COMMAND / SUMMARY` block, followed by its table, to that file (`${CLAUDE_PLUGIN_DATA}/reviews/<review id>.md`).
Do not run the install until the human says so; then run the same command unchanged and the checkpoint will
ask them to approve it.
