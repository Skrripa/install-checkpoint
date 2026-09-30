# Install Checkpoint

Coding agents with wide access to your computer can install packages, run scripts from the internet, add MCP servers
or change Claude's own settings in a single step. Install Checkpoint puts a pause in front of those steps:
**first a reviewer agent vets it, then you approve it.**

## What it does

- **Pauses installs.** A `PreToolUse` hook watches Bash commands. Package installs (`brew`, `apt`, `npm`, `pnpm`,
  `yarn`, `pip`, `uv`, `poetry`, `conda`, `gem`, `cargo`, `go install`), package runners (`npx`, `uvx`, `pipx run`),
  download-and-run (`curl … | sh`), `git clone`, `claude mcp add`, `claude plugin install`, editor extensions,
  `sudo`, and autostart (`crontab`, `launchctl load`, `systemctl --user enable`) are denied until they are reviewed.
- **Reviews.** The bundled `install-reviewer` agent checks the source, author, install scripts and permissions in two
  passes (what is it / how could it hurt me) and saves a verdict: `OK`, `CAUTION` or `BLOCK`.
- **Asks you.** When the same command runs again, you get Claude Code's permission prompt with the reviewer's verdict.
  The prompt appears even in auto and bypass-permissions modes. A `BLOCK` verdict keeps the command denied.
  In non-interactive runs (`claude -p`) the prompt cannot be shown, so the install stays blocked.
- **Protects settings.** Edits to `~/.claude/settings.json`, `~/.claude.json`, `~/.claude/{skills,agents,commands,hooks,plugins}`,
  any `.mcp.json`, project `.claude/settings*.json`, `~/.codex`, and autostart folders always ask you first.

## Install

In Claude Code:

```
/plugin marketplace add Skrripa/install-checkpoint
/plugin install install-checkpoint@install-checkpoint
```

Restart Claude Code after installing. To try it without installing: `claude --plugin-dir ./install-checkpoint`.

## How to use

1. Enable the plugin. Nothing else to configure.
2. Work as usual. When Claude tries to install something, the checkpoint pauses it and tells Claude the review id.
3. Claude runs the reviewer (or you type `/install-checkpoint:review <command or link>`).
4. Claude repeats the exact command. You see the verdict in the permission prompt and choose.

Option `require_review` (on by default): turn it off to skip the reviewer and just be asked for every install.

## Data and privacy

Everything stays on your computer. The hook makes **no network requests**. It stores verdicts in
`${CLAUDE_PLUGIN_DATA}/reviews/` (valid for 24 hours) and a short local log in `${CLAUDE_PLUGIN_DATA}/log.tsv`.
The reviewer agent uses Claude's normal web search and fetch tools to research what is being installed.

## Limits

This is a guardrail, not a sandbox. It matches command text, so a command hidden inside a script is not caught.
The human approval prompt is the real checkpoint — read it before you approve.

Requires Python 3.8+ available as `python3`.

## Tests

`python3 tests/test_checkpoint.py` runs 23 cases (blocked, allowed, asked, review flow).

---

## По-русски

**Install Checkpoint** — «сначала проверка, потом установка». Плагин останавливает установку программ и пакетов,
скачивание и запуск скриптов из интернета, подключение MCP-серверов и плагинов, `sudo`, автозапуск и правки настроек Claude.

Установка в Claude Code:

```
/plugin marketplace add Skrripa/install-checkpoint
/plugin install install-checkpoint@install-checkpoint
```

После установки перезапустите Claude Code.

Как это работает:
1. Хук видит команду установки и приостанавливает её.
2. Агент `install-reviewer` проверяет источник, автора, скрипты установки и права в два прохода и пишет вердикт:
   OK / CAUTION / BLOCK.
3. Claude повторяет ту же команду — и вы видите окно разрешения с вердиктом. Решаете вы. При BLOCK установка запрещена.

Данные никуда не отправляются: вердикты и журнал лежат локально в папке данных плагина. Ограничение: это страховка,
а не песочница — команду, спрятанную внутри скрипта, хук не увидит. Главная защита — ваше «да» в окне разрешения.

## License

MIT © 2026 Olga Skrypchenko
