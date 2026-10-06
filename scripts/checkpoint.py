#!/usr/bin/env python3
"""Install Checkpoint: a PreToolUse hook for Claude Code.

What it does
  1. Bash commands that install or download-and-run software (brew, npm, pip, npx,
     curl | sh, git clone, claude mcp add, sudo, ...) are stopped until the
     install-reviewer agent has vetted that exact command and its verdict is saved. After that,
     Claude Code asks the human to approve (a permission prompt that shows even in
     auto and bypass modes). A BLOCK verdict keeps the command denied.
  2. Any other command that is not understood in full (variables or $(…) in place of a program,
     eval, decoded text, inline code, here-docs, local scripts, downloads, unknown programs)
     asks the human first. Commands made only of known harmless parts (ls, git status, echo…)
     run without a pause.
  3. Writes to places that change how Claude or the computer behaves (Claude settings,
     skills, agents, plugins, MCP config, autostart) always ask the human first.

The hook only reads: it never writes files, never runs other programs and makes no network
requests. Review verdicts are saved by Claude (not by this hook) in the plugin's data
directory (CLAUDE_PLUGIN_DATA/reviews) and read from there.

This is a guardrail, not a sandbox: a command hidden inside a file that was written earlier
is not seen. The human approval prompt is the real checkpoint.
"""
import datetime
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import understand  # noqa: E402  (same folder; command parsing, no network)

HOME = os.path.expanduser("~")
DATA = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.join(HOME, ".claude", "install-checkpoint")
ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
REVIEWS = os.path.join(DATA, "reviews")
REVIEW_TTL = datetime.timedelta(hours=24)

INSTALL_PATTERNS = [
    ("Homebrew", r"\bbrew\s+(install|reinstall|upgrade|tap|bundle)\b"),
    ("system package manager", r"\b(apt|apt-get|dnf|yum|zypper|snap|port)\s+install\b|\bpacman\s+-S|\bapk\s+add\b"),
    ("JavaScript package", r"\b(npm|pnpm|yarn|bun)\s+(i|install|add|ci)\b|\bnpm\s+.*\s(-g|--global)\b"),
    ("package runner", r"\b(npx|bunx|pnpx|uvx)\s|\b(pnpm|yarn)\s+dlx\b|\bpipx\s+(install|run)\b"),
    ("Python package", r"\bpip3?\s+install\b|\bpython3?\s+-m\s+pip\s+install\b|\buv\s+(pip\s+install|tool\s+install|add)\b|\bpoetry\s+add\b|\b(conda|mamba)\s+install\b"),
    ("language package", r"\b(gem|cargo|go)\s+install\b"),
    ("app installer", r"\bmas\s+install\b|\binstaller\s+-pkg\b|\b(code|cursor)\s+--install-extension\b"),
    ("MCP server or plugin", r"\b(claude|codex)\s+(mcp\s+add|plugin\s+(install|add)|plugin\s+marketplace\s+add)|\bgemini\s+extensions\s+install\b"),
    ("repository clone", r"\bgit\s+clone\b|\bgh\s+repo\s+clone\b"),
    ("download and run", r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh|python3?|node)\b|\b(sh|bash|zsh)\s+<\(\s*(curl|wget)|\biex\s*\(\s*(irm|iwr)\b"),
    ("administrator rights", r"\bsudo\s"),
    ("autostart", r"\bcrontab\s|\blaunchctl\s+(load|bootstrap|enable)\b|\bsystemctl\s+--user\s+enable\b"),
]

# Signs from the parser that mean "this installs something": they go through the review flow.
INSTALL_CODES = {"custom_registry", "unregistered_source", "npm_alias", "requirements_file", "project_dependencies",
                 "scaffolder", "global_install", "nested_install", "runs_code", "unsupported_ecosystem",
                 "plugin_install", "git_dangerous_option", "remote_mcp", "extension_install"}
# Signs that only mean "not understood / runs local code"; with pause_unknown off they do not pause.
SOFT_CODES = {"not_fully_understood", "runs_script"}
# Local housekeeping that neither installs nor runs other code (on top of the parser's harmless list).
LOCAL_PROGRAMS = {"rm", "kill", "pkill", "killall", "lsof", "man", "sw_vers", "pgrep", "top", "uptime"}
understand.SAFE_PROGRAMS = understand.SAFE_PROGRAMS | LOCAL_PROGRAMS
TARGET_LABELS = {"package": "package install", "repo": "repository download", "download_and_run": "download and run"}

PROTECTED = [
    os.path.join(HOME, ".claude", "settings.json"),
    os.path.join(HOME, ".claude", "settings.local.json"),
    os.path.join(HOME, ".claude.json"),
    os.path.join(HOME, ".claude", "skills"),
    os.path.join(HOME, ".claude", "agents"),
    os.path.join(HOME, ".claude", "commands"),
    os.path.join(HOME, ".claude", "hooks"),
    os.path.join(HOME, ".claude", "plugins"),
    os.path.join(HOME, ".codex"),
    os.path.join(HOME, "Library", "LaunchAgents"),
    os.path.join(HOME, ".config", "autostart"),
    os.path.join(HOME, ".config", "systemd", "user"),
]
PROTECTED_SUFFIXES = ("/.mcp.json", "/.claude/settings.json", "/.claude/settings.local.json")

# A redirect that is not just `2>/dev/null`, or a command that changes files.
WRITE_HINTS = (r"(?<![0-9&])>(?!\s*/dev/null)|\btee\b|\bcp\b|\bmv\b|\brm\b|\bln\b|\bsed\s+-i|"
               r"\bchmod\b|\bchown\b|\btouch\b|\bmkdir\b|\bunzip\b|\btar\s+-?\w*x|\brsync\b|\bditto\b|"
               r"\bpython3?\s+-c\b|\bperl\s+-\w*[pie]")


def decide(decision, reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


def normalize(cmd):
    return " ".join(cmd.split())


def review_id(cmd):
    return hashlib.sha256(normalize(cmd).encode("utf-8")).hexdigest()[:16]


def read_review(rid):
    """Return (verdict, summary) of a fresh review, or None."""
    path = os.path.join(REVIEWS, rid + ".md")
    try:
        age = datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(path))
        if age > REVIEW_TTL:
            return None
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None
    verdict = re.search(r"^VERDICT:\s*(OK|CAUTION|BLOCK)\b", text, re.M | re.I)
    summary = re.search(r"^SUMMARY:\s*(.+)$", text, re.M)
    if not verdict:
        return None
    return verdict.group(1).upper(), (summary.group(1).strip() if summary else "")


def _option(name):
    return os.environ.get("CLAUDE_PLUGIN_OPTION_" + name, "true").strip().lower() not in ("false", "0", "no", "off")


def require_review():
    return _option("REQUIRE_REVIEW")


def pause_unknown():
    return _option("PAUSE_UNKNOWN")


def understand_command(cmd):
    """Return (install kinds, other notes) found by the parser. A parser error counts as not understood."""
    try:
        targets, notes = understand.parse_command(cmd)
    except Exception:
        return [], [{"code": "not_fully_understood", "reason": "The command could not be parsed."}]
    kinds = [TARGET_LABELS.get(t.get("type"), "install") for t in targets]
    kinds += [n["code"].replace("_", " ") for n in notes if n["code"] in INSTALL_CODES]
    others = [n for n in notes if n["code"] not in INSTALL_CODES]
    return kinds, others


def inside(path, base):
    return bool(base) and (path == base or path.startswith(base.rstrip(os.sep) + os.sep))


def protected_path(path):
    if inside(path, os.path.realpath(REVIEWS)):
        return False  # the reviewer's own verdict files
    if ROOT and inside(path, os.path.realpath(ROOT)):
        return True  # do not let the checkpoint edit itself
    return path.endswith(PROTECTED_SUFFIXES) or any(inside(path, p) for p in PROTECTED)


def check_write(tool, inp, sid):
    raw = inp.get("file_path") or inp.get("notebook_path") or ""
    if not raw:
        return
    path = os.path.realpath(os.path.expanduser(raw))
    if protected_path(path):
        decide("ask", "Install Checkpoint: this edit changes how Claude or your computer behaves (" + path +
               "). Approve only if you asked for this change.")


def check_bash(cmd, sid):
    expanded = cmd.replace("~", HOME).replace("$HOME", HOME).replace("${HOME}", HOME)
    touched = [p for p in PROTECTED if p in expanded]
    touched += [s for s in PROTECTED_SUFFIXES if s.lstrip("/") in expanded]
    if ROOT and ROOT in expanded:
        touched.append(ROOT)
    if touched and re.search(WRITE_HINTS, cmd):
        decide("ask", "Install Checkpoint: this command may change a protected place (" + touched[0] +
               "): Claude settings, skills, agents, plugins, MCP config or autostart. Approve only if you asked for it.")

    kinds = [label for label, rx in INSTALL_PATTERNS if re.search(rx, cmd)]
    parsed_kinds, others = understand_command(cmd)
    kinds += [k for k in parsed_kinds if k not in kinds]
    if not pause_unknown():
        others = [n for n in others if n["code"] not in SOFT_CODES]
    unclear = (" Not fully understood: " + others[0]["reason"]) if others else ""

    if not kinds:
        if others:
            decide("ask", "Install Checkpoint: this command is not fully understood, so it may download, install or "
                   "run code that was not checked. " + others[0]["reason"] + " Approve only if you know what it does.")
        return
    rid = review_id(cmd)
    what = ", ".join(kinds[:4])

    if not require_review():
        decide("ask", "Install Checkpoint: " + what + "." + unclear +
               " Approve only if you know what this installs and trust the source.")

    review = read_review(rid)
    if review is None:
        decide("deny", "Install Checkpoint: " + what + " is paused until it is reviewed. Do not try another way "
               "to install it. Ask the install-checkpoint:install-reviewer agent to vet this exact command, then save "
               "the verdict block it returns to " + os.path.join(REVIEWS, rid + ".md") + " (review id " + rid +
               "). Then run the same command again, unchanged: the human will be asked to approve it.")

    verdict, summary = review
    if verdict == "BLOCK":
        decide("deny", "Install Checkpoint: the reviewer's verdict is BLOCK (" + summary + "). Do not install. "
               "Tell the human why and suggest a safer option.")
    decide("ask", "Install Checkpoint: " + what + ". Reviewer verdict: " + verdict +
           (" — " + summary if summary else "") + "." + unclear + " Full review: " + os.path.join(REVIEWS, rid + ".md") +
           ". Approve only if you agree.")


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    sid = data.get("session_id", "")
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        check_write(tool, inp, sid)
    elif tool == "Bash":
        check_bash(inp.get("command") or "", sid)
    sys.exit(0)


if __name__ == "__main__":
    main()
