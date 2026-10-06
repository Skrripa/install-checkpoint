"""Install Checkpoint: understand a shell command before it runs.

Shared with the Install Checkpoint API (same rules). Standard library only: no network, no files, no subprocesses.
parse_command(cmd) returns (targets, notes):
  targets - installs it found (npm / PyPI packages, git repositories, download-and-run URLs);
  notes   - risk signs and parts that were not understood, each {"level", "code", "reason"}.
A command is "fully understood" only when every part is a known install or a known harmless command.
"""
import re
import shlex

REGISTRY_ENV = {"NPM_CONFIG_REGISTRY", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL",
                "UV_DEFAULT_INDEX", "PIP_TRUSTED_HOST", "YARN_REGISTRY"}
REGISTRY_ENV_HINT = re.compile(r"REGISTRY|INDEX|FIND_LINKS|TRUSTED_HOST|USERCONFIG|GLOBALCONFIG|CONFIG_FILE", re.I)
INTERPRETERS = r"(?:sh|bash|zsh|dash|ksh|fish|python3?|node|perl|ruby|pwsh|powershell)"


def finding(level, code, reason, evidence=None):
    reason = re.sub(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@", r"\1***@", reason)  # hide user:password@
    return {"level": level, "code": code, "reason": re.sub(r"[\x00-\x1f\x7f]", " ", reason)[:300]}


# ---------- command parsing ----------
FETCHERS = {"curl", "wget", "fetch", "aria2c", "http", "https", "xh", "httpie", "iwr", "irm", "Invoke-WebRequest",
            "Invoke-RestMethod", "Start-BitsTransfer", "certutil", "bitsadmin", "lynx", "links", "w3m"}
INTERP_PROGS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "csh", "tcsh", "python", "python2", "python3", "node", "nodejs",
                "perl", "ruby", "php", "pwsh", "powershell", "lua", "Rscript", "osascript", "deno", "bun", "tclsh"}
SHELLS = INTERP_PROGS | {"source", ".", "iex", "Invoke-Expression"}
# Wrappers that run the command that follows them. They are unwrapped and the real command is analysed.
WRAPPERS = {"sudo", "doas", "env", "exec", "command", "builtin", "time", "nohup", "nice", "ionice", "stdbuf", "export",
            "timeout", "watch", "caffeinate", "chronic", "unbuffer", "setsid", "firejail"}
WRAPPER_VALUE_FLAGS = {"-u", "-g", "-C", "-h", "-p", "-n", "-s", "-k", "-c", "--signal", "--kill-after", "--interval", "-d"}
REGISTRY_FILES = re.compile(r"(?:^|[\s/'\"=>])(?:\.npmrc|\.yarnrc(?:\.yml)?|pip\.conf|pip\.ini|uv\.toml|\.pypirc|pydistutils\.cfg)\b")
PIPE_TO_INTERPRETER = re.compile(r"(?<!\|)\|&?\s*(?:sudo\s+(?:-\S+\s+)*)?(?:\S*/)?(?:env\s+(?:-\S+\s+)*)?(?:\S*/)?"
                                 r"(?:sh|bash|zsh|dash|ksh|fish|csh|tcsh|python[23]?|node|nodejs|perl|ruby|php|pwsh|powershell|lua|osascript)\b")
REGISTRY_FLAG_PREFIXES = ("--index", "--extra-index", "--trusted", "--find", "--reg", "--default-index", "--userconfig", "--globalconfig")
# Inline code that touches the network or runs other programs.
RISKY_INLINE = re.compile(r"https?://|urllib|requests|socket|subprocess|os\.system|os\.popen|popen|child_process|"
                          r"\bexec\b|\beval\b|__import__|importlib|\bfetch\b|XMLHttpRequest|http\.client|httpx|aiohttp|"
                          r"\bspawn\b|Net::HTTP|open-uri|LWP|IO::Socket|system\s*\(|`|base64|b64decode|atob|Buffer\.from|"
                          r"marshal|pickle|compile\s*\(|ctypes", re.I)
# Commands that are understood and safe on their own (read-only or local housekeeping).
SAFE_PROGRAMS = {"ls", "cd", "pwd", "echo", "cat", "head", "tail", "less", "more", "wc", "grep", "egrep", "fgrep", "rg", "ag",
                 "sort", "uniq", "cut", "diff", "cmp", "which", "whereis", "whoami", "id", "date", "uname", "hostname",
                 "mkdir", "rmdir", "touch", "cp", "mv", "ln", "tree", "du", "df", "ps", "true", "false", "test", "[", "sleep",
                 "clear", "file", "stat", "basename", "dirname", "realpath", "readlink", "jq", "yq", "tr", "rev", "column",
                 "nl", "tac", "fold", "paste", "join", "comm", "md5sum", "shasum", "sha256sum", "cksum", "chmod", "chown",
                 "tar", "unzip", "zip", "gzip", "gunzip", "xz", "printenv", "set", "unset", "type", "history",
                 "pbcopy", "pbpaste", "tee", "cls", "dir", "Get-ChildItem", "Get-Content", "Write-Output", "Set-Location"}
SAFE_GIT = {"status", "log", "diff", "show", "branch", "checkout", "switch", "add", "commit", "push", "pull", "fetch", "remote",
            "rev-parse", "stash", "tag", "init", "merge", "rebase", "reset", "restore", "blame", "describe", "ls-files",
            "shortlog", "reflog", "cherry-pick", "revert", "mv", "rm", "grep", "version", "--version", "help"}
SAFE_PKG_SUBCOMMANDS = {"run", "test", "start", "ls", "list", "outdated", "audit", "view", "info", "show", "version", "-v",
                        "--version", "whoami", "ping", "help", "-h", "--help", "why", "explain", "doctor", "prune", "dedupe",
                        "freeze", "check", "cache", "build", "lint", "format", "pack", "init", "remove", "uninstall", "rm",
                        "un", "unlink", "search", "fund", "venv", "lock", "tree"}
SAFE_PY_MODULES = {"http.server", "venv", "json.tool", "pytest", "unittest", "compileall", "py_compile", "doctest",
                   "timeit", "this", "site", "pip"}
# Environment variables that only change output or app mode. Any other VAR=… can change what runs or loads.
SAFE_ENV = {"CI", "NODE_ENV", "DEBUG", "FORCE_COLOR", "NO_COLOR", "LANG", "TZ", "TERM", "PORT", "HOST"}
# Options that make a "safe" program run another program.
DANGEROUS_ARGS = {
    "tar": re.compile(r"^(--to-command|--checkpoint-action|--use-compress-program|--info-script|--new-volume-script|"
                      r"--rsh-command|-I|-F|-[A-Za-z]*[IF])"),
    "zip": re.compile(r"^(-TT|--unzip-command)"),
    "sort": re.compile(r"^--compress-program"),
}
EXEC_ARG = re.compile(r"(?:exec|command)=", re.I)
# Files and folders whose contents run later: shell startup files, autostart, hooks, PATH folders, package.json.
PERSISTENT_TARGET = re.compile(r"(?:^|/)(?:\.bashrc|\.zshrc|\.zshenv|\.profile|\.bash_profile|\.bash_login|\.zprofile|"
                               r"\.zlogin|config\.fish|package\.json)$|LaunchAgents|LaunchDaemons|^(?:/private)?/etc(?:/|$)|"
                               r"(?:^|/)\.ssh(?:/|$)|\.git/hooks|^/usr/local/bin|\.local/bin")
TRUSTED_GIT_HOSTS = {"github.com", "gitlab.com"}


def _segments(cmd):
    """Split a shell command into simple commands at | || && ; & and newlines, keeping quotes intact."""
    lexer = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars="|&;")
    lexer.whitespace_split = True
    segs, cur = [], []
    try:
        tokens = list(lexer)
    except ValueError:
        tokens = cmd.split()
    for tok in tokens:
        if tok and set(tok) <= set("|&;"):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        segs.append(cur)
    return segs


def _strip_prefix(words, notes):
    """Drop VAR=value / export and unwrap sudo, env, nohup, timeout, watch… so the real command is analysed.
    Record registry overrides set through env vars."""
    out = list(words)
    while out:
        w = out[0]
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", w)
        if m:
            if m.group(1).upper() in REGISTRY_ENV or REGISTRY_ENV_HINT.search(m.group(1)):
                notes.append(finding("CAUTION", "custom_registry", "Uses a custom package registry via %s." % m.group(1), m.group(2)))
            elif m.group(1) not in SAFE_ENV and not m.group(1).startswith("LC_"):
                notes.append(finding("CAUTION", "env_override", "Sets %s — environment variables like this can change what "
                                     "programs run or load." % m.group(1)))
            out.pop(0)
        elif w in WRAPPERS or w.rsplit("/", 1)[-1] in WRAPPERS:
            name = out.pop(0).rsplit("/", 1)[-1]
            while out and out[0].startswith("-"):
                flag = out.pop(0)
                if flag in WRAPPER_VALUE_FLAGS and "=" not in flag and out:
                    out.pop(0)
            if name == "timeout" and out and re.match(r"^\d+(\.\d+)?[smhd]?$", out[0]):
                out.pop(0)
        else:
            break
    if out:
        if out[0].startswith("/") and "$" not in out[0]:
            out[0] = out[0].rsplit("/", 1)[-1]  # /usr/bin/npm -> npm; ./script stays ./script
    return out


def _is_registry_flag(name, attached_short):
    return name.startswith(REGISTRY_FLAG_PREFIXES) or name in attached_short


def _walk(args, value_flags, registry_flags=(), spec_flags=(), other_notes=None, attached_short=()):
    """Return (positionals, flag_values). Values of value-taking flags are never treated as package names.
    Registry flags are matched by prefix (--reg, --extra-index...) and, for pip, attached short forms (-ihttps://...)."""
    positionals, values = [], []
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("-") and len(a) > 1:
            name, eq, inline = a.partition("=")
            short_attached = None
            for s in attached_short:  # -ihttps://x  /  -fhttps://x
                if a.startswith(s) and len(a) > len(s) and not a.startswith("--"):
                    name, short_attached = s, a[len(s):]
            is_registry = name in registry_flags or (registry_flags and _is_registry_flag(name, attached_short))
            takes = name in value_flags or is_registry or name in spec_flags
            val = short_attached or (inline if eq else (args[i + 1] if takes and i + 1 < len(args) else None))
            if takes and not eq and not short_attached:
                i += 1
            if is_registry and other_notes is not None:
                other_notes.append(finding("CAUTION", "custom_registry", "Uses a custom package index or trusted host (%s)." % name, val))
            if name in spec_flags and val:
                values.append(val)
        else:
            positionals.append(a)
        i += 1
    return positionals, values


NPM_VALUE = {"--prefix", "--tag", "--cache", "-w", "--workspace", "--omit", "--include",
             "--install-strategy", "--loglevel", "--location", "-C", "--dir", "--filter", "--cwd"}
PIP_VALUE = {"-r", "--requirement", "-e", "--editable", "-c", "--constraint", "-t", "--target", "--prefix", "--root", "--src",
             "--platform", "--python-version", "--implementation", "--abi", "--only-binary", "--no-binary", "--progress-bar",
             "--log", "--cache-dir", "--upgrade-strategy", "-C", "--config-settings", "--global-option", "--report", "--python", "-p"}
PIP_REGISTRY = {"-i", "--index-url", "--extra-index-url", "--trusted-host", "-f", "--find-links", "--index"}
PIP_SHORT = ("-i", "-f")
NESTED_INSTALL = re.compile(r"^(add|install|i|clone|init|get|fetch|pull|create)$")


def _npm_target(spec, notes):
    spec = spec.strip()
    if re.match(r"^(git\+|git:|https?:|file:|github:|gitlab:|bitbucket:|\.{0,2}/|~/)", spec) or \
            (("/" in spec) and not spec.startswith("@")) or spec.endswith((".tgz", ".tar.gz")):
        notes.append(finding("CAUTION", "unregistered_source", "Installs from a URL, git or local path, not the npm registry — not checked.", spec))
        return None
    m = re.match(r"^(@?[^@\s]+)@npm:(.+)$", spec)  # alias@npm:real@ver -> check the real package
    if m:
        notes.append(finding("CAUTION", "npm_alias", "Installs a package under a different name (%s → %s); the real package is checked." % (m.group(1), m.group(2))))
        spec = m.group(2)
    return {"type": "package", "ecosystem": "npm", "spec": spec}


def _pypi_target(spec, notes):
    if re.match(r"^(git\+|https?:|file:|\.{0,2}/|~/)", spec) or spec.endswith((".whl", ".tar.gz", ".zip")) or "@ " in spec:
        notes.append(finding("CAUTION", "unregistered_source", "Installs from a URL, git or local path, not PyPI — not checked.", spec))
        return None
    return {"type": "package", "ecosystem": "PyPI", "spec": spec}


def _create_package(arg):
    """npm/yarn/pnpm/bun create <x> runs the package create-<x> (@scope -> @scope/create, @scope/x -> @scope/create-x)."""
    name, _, ver = arg.partition("@") if not arg.startswith("@") else (arg, "", "")
    if arg.startswith("@"):
        scope, _, rest = arg.partition("/")
        return scope + "/create" if not rest else scope + "/create-" + rest
    return "create-" + name + ("@" + ver if ver else "")


def _runner(rest, notes, targets, ecosystem="npm", pkg_flags=("-p", "--package"), value_flags=()):
    """npx-style: check the package that is run; flag anything it is told to download or install."""
    pos, pkgs = _walk(rest, set(value_flags) | {"-c", "--call", "--node-options", "--cache", "-p", "--python"},
                      registry_flags={"--registry"} if ecosystem == "npm" else PIP_REGISTRY | {"--default-index"},
                      spec_flags=set(pkg_flags), other_notes=notes, attached_short=() if ecosystem == "npm" else PIP_SHORT)
    calls = [rest[i + 1] for i, a in enumerate(rest[:-1]) if a in ("-c", "--call")] + \
            [a.split("=", 1)[1] for a in rest if a.startswith("--call=")]
    for call in calls:  # npm exec -c '<cmd>': the call is a command of its own
        sub_t, sub_n = parse_command(call)
        targets += sub_t
        notes += sub_n
    specs = pkgs or ([] if calls else pos[:1])
    for s in specs:
        t = (_npm_target if ecosystem == "npm" else _pypi_target)(s, notes)
        if t:
            targets.append(t)
    args_after = pos[0 if (pkgs or calls) else 1:]
    if any(NESTED_INSTALL.match(a) for a in args_after) or any(re.match(r"^(https?://|git@|[\w.-]+/[\w.-]+$)", a) for a in args_after):
        notes.append(finding("CAUTION", "nested_install", "The tool itself was checked, but what it is told to download or install is not."))


def _download_and_run(cmd):
    c = cmd.replace("\n", " ")
    fetch = r"\b(?:curl|wget|iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b"
    patterns = [
        fetch + r"[^;&]*\|\s*(?:[^;&|]*\|\s*)*(?:sudo\s+(?:-\S+\s+)*)?(?:env\s+)?(?:/usr)?(?:/local)?(?:/bin/)?" + INTERPRETERS + r"\b",
        r"\b(?:" + INTERPRETERS[3:-1] + r"|eval)\s+(?:-c\s+)?[\"']?\$\(\s*" + fetch[2:],
        r"\b(?:" + INTERPRETERS[3:-1] + r"|eval)\s+(?:-c\s+)?[\"']?`\s*" + fetch[2:],
        r"(?:\b" + INTERPRETERS + r"|\bsource|(?:^|\s)\.)\s+<\(\s*" + fetch[2:],
        r"\biex\s*[(\$]",
    ]
    if any(re.search(p, c, re.I) for p in patterns):
        return True
    # fetch first, run later: "wget URL ; sh file", "curl -o f URL && chmod +x f && ./f"
    seen_fetch = False
    for words in _segments(cmd):
        w = _strip_prefix(words, [])
        if not w:
            continue
        if w[0] in FETCHERS:
            seen_fetch = True
        elif seen_fetch and (w[0] in SHELLS or w[0].startswith("./") or (w[0] == "chmod" and "+x" in " ".join(w))):
            return True
    return False


def parse_command(cmd):
    """Find what a shell command would do. Returns (targets, notes).
    OK is possible only when EVERY part of the command is understood: a known install from npm / PyPI / github.com
    (then checked), or a known harmless command. Anything else is CAUTION `not_fully_understood`."""
    targets, notes = [], []
    dr = _download_and_run(cmd)
    if dr:
        url = re.search(r"https?://[^\s'\"|)`;]+", cmd) or re.search(r"\b[\w.-]+\.[a-z]{2,}/[^\s'\"|)`;]*", cmd)
        targets.append({"type": "download_and_run", "url": url.group(0) if url else None})
    if not dr and PIPE_TO_INTERPRETER.search(cmd):
        notes.append(finding("CAUTION", "pipe_to_shell", "Pipes data into a shell or interpreter; where it comes from is not recognised — not checked."))
    if re.search(r"\bbase64\s+(?:-\w*[dD]\w*|--decode)\b|\bxxd\s+(?:-\w*r)|\bopenssl\s+(?:enc|base64)\b.*\s-d\b|"
                 r"\bcertutil\b.*-decode|FromBase64String|\bprintf\b[^|;&]*(?:\\x[0-9a-fA-F]{2}|\\[0-7]{3}|%b)", cmd, re.I):
        notes.append(finding("CAUTION", "encoded_payload", "Decodes or assembles hidden text (base64, hex, escapes) — a common way to hide what runs."))
    if re.search(r"\$\(|`", cmd):
        notes.append(finding("CAUTION", "substitution", "Uses command substitution $(…) or backticks — what runs is only known at run time."))
    if re.search(r"[<>]\(", cmd):
        notes.append(finding("CAUTION", "process_substitution", "Uses process substitution <(…) / >(…) — not checked."))
    if re.search(r"(?:^|[;&|\n]\s*)alias\s+[\w.-]+=|\bfunction\s+[\w.-]+|(?:^|[;&|\n]\s*)[\w.-]+\s*\(\)\s*\{", cmd):
        notes.append(finding("CAUTION", "alias_or_function", "Defines an alias or shell function, so later names may run something else."))
    if re.search(r"(?:https?|ftp)://[^\s'\"]*\$|\$\{?\w+\}?/", cmd):
        notes.append(finding("CAUTION", "variable_url", "A URL or path is built from a variable — its real value is not known."))
    if REGISTRY_FILES.search(cmd):
        notes.append(finding("CAUTION", "custom_registry", "Touches a package-manager config file (.npmrc, pip.conf, .yarnrc, uv.toml…) that can redirect installs."))
    heredoc = re.search(r"<<<|<<-?\s*['\"]?[A-Za-z_]", cmd)
    written = re.findall(r"(?:^|[^<>-])>>?\|?\s*['\"]?([^\s;&|'\"<>()]+)", cmd)  # > file, >> file, 2> file
    for words in _segments(cmd):
        w = _strip_prefix(words, notes)
        if not w:
            continue
        files = [a for a in w[1:] if not a.startswith("-")]
        if w[0] == "tee":
            written += files
        elif w[0] in ("cp", "mv", "ln", "install", "rsync", "ditto") and files:
            written.append(files[-1])
        elif w[0] in ("sed", "perl") and any(a.startswith("-i") or a == "--in-place" for a in w[1:]):
            written += files  # edits files in place
        if "$" in w[0] or "`" in w[0]:
            notes.append(finding("CAUTION", "indirect_program", "The program to run comes from a variable or substitution: " + " ".join(words)[:120]))
            continue
        if heredoc and w[0] in INTERP_PROGS and any(t.startswith("<<") for t in w):
            notes.append(finding("CAUTION", "heredoc_to_interpreter", "Feeds an inline script (here-document) to %s — not checked." % w[0]))
            continue
        handled = _parse_segment(w, targets, notes)
        if handled is None and dr and w[0] in FETCHERS | SHELLS | {"eval", "chmod", "tee"}:
            handled = True  # part of the download-and-run already reported
        if handled is None:
            handled = _classify_other(w, notes)
        if handled is None:
            notes.append(finding("CAUTION", "not_fully_understood",
                                 "Part of the command is not understood, so it was not checked: " + " ".join(words)[:120]))
    risky_writes = [p for p in written if PERSISTENT_TARGET.search(re.sub(r"^(~|\$HOME|\$\{HOME\})/", "", p))]
    if risky_writes:
        notes.append(finding("CAUTION", "persistent_write", "Writes to a file or folder whose contents run later (shell startup, "
                             "autostart, git hooks, PATH, package.json): %s." % risky_writes[0][:120]))
    return targets, notes


def _parse_segment(w, targets, notes):
    """Parse one simple command. Returns True when it was understood (even if nothing to check), None otherwise."""
    prog, rest = w[0], w[1:]
    if prog in ("python", "python3") and rest[:2] == ["-m", "pip"]:
        prog, rest = "pip", rest[2:]
    if prog == "uv" and rest[:1] == ["pip"]:
        prog, rest = "pip", rest[1:]

    if prog in INTERP_PROGS and any(a in ("-c", "-e", "-E", "--eval", "-p", "--print", "-r", "eval", "-Command", "-command",
                                          "-EncodedCommand", "-enc", "-e:") for a in rest):
        risky = RISKY_INLINE.search(" ".join(rest))
        notes.append(finding("CAUTION", "inline_code_download" if risky else "inline_code",
                             "Runs inline code%s — not checked." % (" that uses the network or runs other programs" if risky else "")))
        return True

    if prog == "eval":
        notes.append(finding("CAUTION", "eval", "Runs a dynamically built command (eval) — not checked."))
        return True

    if prog in ("npm", "pnpm", "yarn", "bun"):
        pos, _ = _walk(rest, NPM_VALUE, registry_flags={"--registry"}, other_notes=notes)
        sub = pos[0] if pos else ""
        if sub in ("config", "set") and any(p.lower().startswith(("registry", "@", "npmregistryserver", "//")) for p in pos[1:]) \
                and ("set" in pos[:2]):
            notes.append(finding("CAUTION", "custom_registry", "Changes the package registry in the %s config." % prog))
            return True
        if sub in ("exec", "x", "dlx") and not (prog == "pnpm" and sub == "exec"):
            i = rest.index(sub)
            _runner(rest[i + 1:], notes, targets)
            return True
        if prog == "pnpm" and sub == "exec":
            notes.append(finding("CAUTION", "runs_script", "pnpm exec runs a binary from the project — not checked."))
            return True
        if sub in ("create", "init") and len(pos) >= 2:
            t = _npm_target(_create_package(pos[1]) if "/" not in pos[1] or pos[1].startswith("@") else pos[1], notes)
            if t:
                targets.append(t)
            notes.append(finding("CAUTION", "scaffolder", "%s %s runs a project generator that can download templates and run more code; only the generator package is checked." % (prog, sub)))
            return True
        if prog == "yarn" and pos[:2] == ["global", "add"]:
            notes.append(finding("CAUTION", "global_install", "Installs a command system-wide (global install)."))
            pos = ["add"] + pos[2:]
            sub = "add"
        if sub in ("i", "install", "add", "isntall"):
            specs = pos[1:]
            if specs and (re.search(r"(?:^|\s)(?:-g|--global)(?:\s|$)", " ".join(rest)) or "global" in pos[:1]):
                notes.append(finding("CAUTION", "global_install", "Installs a command system-wide (global install)."))
            if not specs:
                notes.append(finding("CAUTION", "project_dependencies", "Installs the project's own dependencies (package.json / lockfile) — not checked."))
            for s in specs:
                t = _npm_target(s, notes)
                if t:
                    targets.append(t)
            return True
        if prog == "yarn" and not pos:
            notes.append(finding("CAUTION", "project_dependencies", "Installs the project's own dependencies — not checked."))
            return True
        if sub == "ci":
            notes.append(finding("CAUTION", "project_dependencies", "Installs dependencies from the lockfile — not checked."))
            return True
        return None
    if prog in ("npx", "bunx", "pnpx"):
        _runner(rest, notes, targets)
        return True
    if prog in ("pip", "pip3"):
        if rest[:1] == ["config"] and "set" in rest:
            notes.append(finding("CAUTION", "custom_registry", "Changes the pip configuration (index or trusted host)."))
            return True
        if rest[:1] == ["install"]:
            joined = " ".join(rest)
            pos, _ = _walk(rest[1:], PIP_VALUE, registry_flags=PIP_REGISTRY, other_notes=notes, attached_short=PIP_SHORT)
            for flag_val in re.findall(r"(?:^|\s)(?:-r|--requirement)(?:=|\s+)(\S+)", joined):
                notes.append(finding("CAUTION", "requirements_file", "Installs from a requirements file — its contents are not checked.", flag_val))
            for flag_val in re.findall(r"(?:^|\s)(?:-e|--editable)(?:=|\s+)(\S+)", joined):
                notes.append(finding("CAUTION", "unregistered_source", "Editable install from a local path or URL — not checked.", flag_val))
            for s in pos:
                t = _pypi_target(s, notes)
                if t:
                    targets.append(t)
            return True
        return None
    if prog == "uv":
        if rest[:1] == ["run"]:
            pos, pkgs = _walk(rest[1:], PIP_VALUE, registry_flags=PIP_REGISTRY | {"--default-index"}, spec_flags={"--with"},
                              other_notes=notes, attached_short=PIP_SHORT)
            for s in pkgs:
                t = _pypi_target(s, notes)
                if t:
                    targets.append(t)
            notes.append(finding("CAUTION", "runs_code", "uv run executes a script; only the packages passed with --with are checked."))
            return True
        if rest[:1] in (["add"], ["tool"]):
            sub = rest[2:] if rest[:2] in (["tool", "install"], ["tool", "run"]) else rest[1:]
            pos, pkgs = _walk(sub, PIP_VALUE, registry_flags=PIP_REGISTRY | {"--default-index"}, spec_flags={"--with", "--from"},
                              other_notes=notes, attached_short=PIP_SHORT)
            for s in pkgs + (pos if rest[:2] != ["tool", "run"] else pos[:1]):
                t = _pypi_target(s, notes)
                if t:
                    targets.append(t)
            return True
        return None
    if prog in ("uvx", "pipx"):
        if prog == "pipx":
            if rest[:1] not in (["install"], ["run"]):
                return None
            rest = rest[1:]
        _runner(rest, notes, targets, ecosystem="PyPI", pkg_flags=("--from", "--with", "--spec"), value_flags=("--pip-args", "--suffix"))
        return True
    if prog == "git" and rest[:1] == ["clone"]:
        joined = " ".join(rest)
        if re.search(r"(?:^|\s)(?:--upload-pack|-u|-c|--config|--template|--separate-git-dir)(?:=|\s|$)", joined):
            notes.append(finding("CAUTION", "git_dangerous_option", "git clone with --upload-pack / -u / -c / --config can run commands or change git behaviour."))
        pos, _ = _walk(rest[1:], {"-b", "--branch", "--depth", "-o", "--origin", "-c", "--config", "--reference", "-j",
                                  "--jobs", "--template", "--separate-git-dir", "--filter", "-u", "--upload-pack"})
        if pos:
            targets.append({"type": "repo", "url": pos[0]})
        return True
    if prog == "gh" and rest[:2] == ["repo", "clone"] and len(rest) >= 3:
        repo = rest[2] if "://" in rest[2] else "https://github.com/" + rest[2]
        targets.append({"type": "repo", "url": repo})
        return True
    if prog in ("claude", "codex") and rest[:2] == ["mcp", "add"]:
        if "--" in rest:
            sub_t, sub_n = parse_command(" ".join(shlex.quote(x) for x in rest[rest.index("--") + 1:]))
            targets += sub_t
            notes += sub_n
        else:
            url = next((x for x in rest if re.match(r"^https?://", x)), None)
            notes.append(finding("CAUTION", "remote_mcp", "Connects a remote MCP server — the server itself is not checked.", url))
        return True
    if "plugin" in w and ("install" in w or "add" in w) or ("marketplace" in w and "add" in w):
        notes.append(finding("CAUTION", "plugin_install", "Installs a plugin or adds a plugin marketplace — not checked."))
        return True
    if prog == "go" and rest[:1] in (["run"], ["install"], ["get"]):
        notes.append(finding("CAUTION", "unsupported_ecosystem", "Go modules are not checked (go %s)." % rest[0]))
        return True
    if prog == "deno" and rest[:1] in (["run"], ["install"], ["add"], ["eval"]):
        notes.append(finding("CAUTION", "unsupported_ecosystem", "Deno runs remote code that is not checked (deno %s)." % rest[0]))
        return True
    return None


def _folder_like(arg):
    """'.', '..', '~', 'src', 'src/' — a folder, not an app, installer, script, file or link."""
    if arg.startswith("-") or ":" in arg:
        return False
    last = arg.rstrip("/").rsplit("/", 1)[-1]
    return last in (".", "..", "~", "") or "." not in last


def _git_host(arg):
    """Host of a git URL (https://host/…, ssh://host/…, git@host:…), or None for anything else."""
    m = re.match(r"^(?:[a-z+]+://(?:[^@/]+@)?|[\w.-]+@)([^/:]+)[:/]", arg, re.I)
    return re.sub(r"^www\.", "", m.group(1).lower()) if m else None


def _classify_other(w, notes):
    """Commands outside the install handlers. True = understood (safe, or reported); None = not understood."""
    prog, rest = w[0], w[1:]
    if any(EXEC_ARG.search(a) for a in rest) or (prog in DANGEROUS_ARGS and any(DANGEROUS_ARGS[prog].match(a) for a in rest)):
        notes.append(finding("CAUTION", "dangerous_option", "%s is given an option that can run another program — not checked." % prog))
        return True
    if prog in ("code", "cursor", "codium"):
        if any(a.startswith(("--install-extension", "--uninstall-extension")) for a in rest):
            notes.append(finding("CAUTION", "extension_install", "Installs an editor extension — not checked."))
            return True
        return True if all(_folder_like(a) for a in rest) else None
    if prog == "open":
        if rest and all(_folder_like(a) for a in rest):
            return True
        notes.append(finding("CAUTION", "opens_app", "open can launch apps, installers, scripts or links — not checked."))
        return True
    if prog in FETCHERS or (prog in ("python", "python3") and rest[:2] in (["-m", "urllib.request"], ["-m", "http.client"])):
        notes.append(finding("CAUTION", "download", "Downloads from the internet — the content is not checked."))
        return True
    if prog == "xargs":
        notes.append(finding("CAUTION", "indirect_program", "xargs builds a command from its input — what runs is not known in advance."))
        return True
    if prog in ("source", ".") or prog.startswith("./") or prog.startswith("../") or (prog.startswith("/") and prog not in SAFE_PROGRAMS):
        notes.append(finding("CAUTION", "runs_script", "Runs a local script or binary (%s) — its contents are not checked." % prog[:60]))
        return True
    if prog in INTERP_PROGS:
        if not rest:
            notes.append(finding("CAUTION", "shell_stdin", "Starts %s reading commands from its input — not checked." % prog))
            return True
        if all(a in ("--version", "-V", "-v", "--help", "-h") for a in rest):
            return True
        if prog.startswith("python") and rest[:1] == ["-m"] and len(rest) >= 2 and rest[1] in SAFE_PY_MODULES:
            return True
        notes.append(finding("CAUTION", "runs_script", "Runs a script or code with %s — its contents are not checked." % prog))
        return True
    if prog in ("eval", "exec", "Invoke-Expression", "iex"):
        notes.append(finding("CAUTION", "eval", "Runs a dynamically built command — not checked."))
        return True
    if prog == "git":
        args = list(rest)
        while args and args[0].startswith("-"):  # global options: -C <dir>, -c <key=value>, --git-dir <dir>
            if args[0] == "-c":
                notes.append(finding("CAUTION", "git_config_exec", "git -c changes git settings for this run; some make git run other programs."))
                return True
            args = args[2:] if args[0] in ("-C", "--git-dir", "--work-tree") else args[1:]
        sub = args[0] if args else ""
        if sub == "config" and re.search(r"\b(alias\.|core\.(sshCommand|pager|editor|hooksPath|fsmonitor)|url\..*insteadOf|"
                                          r"credential\.helper|include\.path)", " ".join(rest), re.I):
            notes.append(finding("CAUTION", "git_config_exec", "git config can make git run other programs — not checked."))
            return True
        if any(a.startswith(("--upload-pack", "--receive-pack", "--exec")) for a in args):
            notes.append(finding("CAUTION", "git_dangerous_option", "git option that runs another program — not checked."))
            return True
        hosts = [_git_host(a) for a in args[1:]]
        foreign = [h for h in hosts if h and h not in TRUSTED_GIT_HOSTS]
        if foreign and sub in SAFE_GIT:
            notes.append(finding("CAUTION", "unknown_git_remote", "Points git at a server other than github.com or gitlab.com (%s)." % foreign[0]))
            return True
        if sub in SAFE_GIT or sub == "config":
            return True
        return None
    if prog in ("npm", "pnpm", "yarn", "bun", "pip", "pip3", "uv", "poetry", "pipenv"):
        pos = [a for a in rest if not a.startswith("-")]
        sub = pos[0] if pos else ""
        if sub in ("config", "set", "get"):
            action = sub if sub != "config" else (pos[1] if len(pos) > 1 else "")
            reading = "--list" in rest and len(pos) == 1 if prog == "poetry" else action in ("get", "list", "ls", "")
            if reading:
                return True
            notes.append(finding("CAUTION", "config_change", "Changes %s settings — they can redirect installs or run other "
                                 "programs — not checked." % prog))
            return True
        if sub in SAFE_PKG_SUBCOMMANDS or not sub:
            return True
        return None
    if prog == "find":
        if any(a in ("-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint") for a in rest):
            notes.append(finding("CAUTION", "runs_script", "find -exec runs other programs — not checked."))
            return True
        return True
    if prog in ("awk", "gawk", "sed"):
        if re.search(r"system\s*\(|\|\s*getline|\be\b\s*$|/e\b", " ".join(rest)):
            notes.append(finding("CAUTION", "runs_script", "%s can run other programs here — not checked." % prog))
            return True
        return True
    if prog in SAFE_PROGRAMS:
        return True
    return None
