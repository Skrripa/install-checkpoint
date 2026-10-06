#!/usr/bin/env python3
"""Independent red-team set (97 hidden download-and-run / foreign-source / code-execution commands and
46 ordinary agent commands) run through the hook. Run: python3 tests/test_redteam.py

  HOSTILE - must be paused: "deny" (review first) or "ask" (human approves). "none" is a failure.
  BENIGN  - installs are paused for review as usual ("deny"); everything else must run without a pause ("none").
The commands only go to the hook as text; nothing is executed. Example hosts are reserved placeholders.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "checkpoint.py")
sys.path.insert(0, HERE)
from redteam_cases import HOSTILE, BENIGN  # noqa: E402

INSTALL = re.compile(r"\b(npm|pnpm|yarn|bun|pip3?|uv)\b.*\b(install|i|add)\b|\b(npx|uvx|dlx)\b|\bgit clone\b|\bmcp add\b")


def decision(cmd, data_dir):
    env = dict(PATH=os.environ.get("PATH", "/usr/bin:/bin"), HOME=os.path.expanduser("~"), CLAUDE_PLUGIN_DATA=data_dir,
               CLAUDE_PLUGIN_ROOT=os.path.join(HERE, ".."))
    event = {"session_id": "test", "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}}
    out = subprocess.run([sys.executable, SCRIPT], input=json.dumps(event), capture_output=True, text=True, env=env)
    return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] if out.stdout.strip() else "none"


def main():
    missed, wrong = [], []
    with tempfile.TemporaryDirectory() as data:
        print("== HOSTILE (must be paused): %d" % len(HOSTILE))
        for c in HOSTILE:
            got = decision(c, data)
            print("%-5s %s" % (got, c.replace("\n", "\\n").replace("\t", "\\t")[:110]))
            if got == "none":
                missed.append(c)
        print("\n== BENIGN: %d" % len(BENIGN))
        for c in BENIGN:
            got = decision(c, data)
            want = "deny" if INSTALL.search(c) else "none"
            print("%-5s %-5s %s" % (got, want, c))
            if got != want:
                wrong.append((want, got, c))
    print("\nHOSTILE %d total, %d without a pause (acceptance 0). BENIGN %d total, %d not as expected." %
          (len(HOSTILE), len(missed), len(BENIGN), len(wrong)))
    for c in missed:
        print("  MISS:", c[:120])
    for want, got, c in wrong:
        print("  BENIGN %s (expected %s): %s" % (got, want, c))
    sys.exit(1 if missed or wrong else 0)


if __name__ == "__main__":
    main()
