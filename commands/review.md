---
description: Vet an install command, package, MCP server, plugin or skill before it runs
argument-hint: <command, package name or link>
---

Ask the `install-checkpoint:install-reviewer` agent to review this before anything is installed:

$ARGUMENTS

If Install Checkpoint already paused a command, pass the agent the exact command and the review id from the
checkpoint message so it can save its verdict. Show the human the agent's verdict table. Do not run the install
yourself until the human says so; when they do, run the same command unchanged and the checkpoint will ask them to approve.
