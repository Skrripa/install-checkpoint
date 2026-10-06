# Changelog

## 0.3.0 — 2026-10-07
- **No pause only when the whole command is understood.** A new parser (`scripts/understand.py`, standard library
  only, no network) reads every part of a command. Anything not understood asks you first.
- Hidden installs are now caught: a program from a variable or `$(…)`, `eval` / `exec` / `source` / `xargs`,
  wrappers (`env`, `command`, `builtin`, `nohup`, `time`, `timeout`, `watch`), `|&`, "write a file, then run it",
  here-docs and here-strings, `<(…)`, decoding (`base64`, `xxd`, `printf '\x…'`, `rev`, `tr`), inline code with or
  without a URL (`python -c`, `node -e`, `perl -e`, `ruby -e`, `php -r`, `pwsh -Command`), aliases and functions,
  more downloaders (`aria2c`, `httpie`, `fetch`, `iwr` / `irm`, `certutil`, `bitsadmin`, `python -m urllib`),
  `find -exec`, `awk system()`, `git config` that sets a command.
- Installs found by the parser (npm / PyPI packages, runners, git clones, custom registries, MCP servers, plugins)
  go through the review flow, in addition to the earlier patterns.
- New option `pause_unknown` (on by default). Turn it off to stop questions about local scripts and unknown programs;
  hidden commands, downloads and installs are still paused.
- Stricter by design: `python3 script.py`, `bash x.sh`, `make`, `cargo`, `docker`, a plain `curl` and any `$(…)`
  now ask you. `npm test` / `npm run` and read-only `git` do not.
- Harmless commands pass only with safe arguments: options that run another program (`tar --to-command`, `zip -TT`,
  `exec=` / `command=`), `open` on apps, installers or links, `code --install-extension`, environment variables outside
  a short list, `config set`, writes to shell startup files / autostart / `.git/hooks` / `package.json` / PATH folders,
  and git remotes outside github.com / gitlab.com ask you first.
- Tests: `tests/test_masking.py` (128 hidden commands, 0 run without a pause) and `tests/test_redteam.py`
  (independent set: 97 hidden commands, 0 run without a pause; 46 ordinary commands as expected).

## 0.2.0 — 2026-10-05
- Read-only reviewer agent, the hook writes nothing, clearer permissions.
