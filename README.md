# Install Checkpoint

**A read-only safety check. It changes nothing on your computer and sends no data — it only pauses installs and asks you.**

Coding agents with wide access to your computer can install packages, run scripts from the internet, add MCP servers
or change Claude's own settings in a single step. Install Checkpoint puts a pause in front of those steps:
**first a reviewer agent vets it, then you approve it.**

## What it needs, and why

Claude shows a notice when you install any plugin that includes a hook, because a hook runs a small script on your
computer. Here is exactly what this plugin does with that:

| Part | What it can do | What it cannot do |
|---|---|---|
| Hook (`scripts/checkpoint.py` + `scripts/understand.py`, ~700 lines of Python, no dependencies) | Looks at a command or file path **before** Claude runs it and answers "go ahead", "ask the human" or "wait for a review" | Write or delete files, run other programs, read your files' contents, connect to the internet |
| `install-reviewer` agent | Read files and search the web to research what is about to be installed | Run commands, install anything, change files |
| `/install-checkpoint:review` command | A short instruction for Claude | — |

The only files involved are review verdicts, which Claude saves in the plugin's own data folder. Read the script
yourself: it is short on purpose.

## What it does

- **Pauses installs.** A `PreToolUse` hook watches Bash commands. Package installs (`brew`, `apt`, `npm`, `pnpm`,
  `yarn`, `pip`, `uv`, `poetry`, `conda`, `gem`, `cargo`, `go install`), package runners (`npx`, `uvx`, `pipx run`),
  download-and-run (`curl … | sh`), `git clone`, `claude mcp add`, `claude plugin install`, editor extensions,
  `sudo`, and autostart (`crontab`, `launchctl load`, `systemctl --user enable`) are denied until they are reviewed.
- **No pause only when the whole command is understood.** Every part of a command (split at `;`, `&&`, `||`, `|`,
  new lines) is read. If any part is not understood, you are asked first. That covers hidden installs: a program taken
  from a variable or `$(…)`, `eval`, `source`, `xargs`, decoded text (`base64 -d`, `xxd -r`, `printf '\x…'`), inline
  code (`python -c`, `node -e`, `perl -e`…), here-docs, `<(…)`, aliases and functions, downloads (`curl`, `wget`,
  `aria2c`, `iwr`…), "write a file, then run it", local scripts and unknown programs. Wrappers such as `sudo`, `env`,
  `nohup`, `timeout` are unwrapped and the real command is checked. Commands made only of known harmless parts
  (`ls`, `cat`, `grep`, `git status`, `git commit`, `npm test`, `--version`…) run without a pause — only with safe
  arguments: options that run another program (`tar --to-command`, `zip -TT`, `exec=`), `open` on apps or installers,
  environment variables outside a short list (`PATH`, `NODE_OPTIONS`, `GIT_SSH_COMMAND`, `DYLD_*`…), `config set`,
  writes to shell startup files, autostart, `.git/hooks`, `package.json` or PATH folders, and git remotes outside
  github.com / gitlab.com all ask you first.
  Unusual shell syntax and some options of common tools can still slip through; the approval prompt is the real checkpoint.
- **Reviews.** The bundled read-only `install-reviewer` agent checks the source, author, install scripts and permissions
  in two passes (what is it / how could it hurt me) and returns a verdict: `OK`, `CAUTION` or `BLOCK`. Claude saves it
  for the checkpoint.
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

Options (both on by default):
- `require_review` — turn it off to skip the reviewer and just be asked for every install.
- `pause_unknown` — turn it off if questions about local scripts (`python3 script.py`, `make`, `cargo build`…) get in
  the way. Hidden commands, downloads and installs are still paused.

## Data and privacy

Everything stays on your computer. The hook makes **no network requests and writes nothing**. Verdicts are saved by
Claude in `${CLAUDE_PLUGIN_DATA}/reviews/` (valid for 24 hours); the hook only reads them. There is no log.
The reviewer agent uses Claude's normal web search and fetch tools to research what is being installed.

## Limits

This is a guardrail, not a sandbox. It reads command text, so code hidden inside a file that was written earlier
(for example by Claude's file editor) is not seen. That is why running local scripts asks you by default.
The human approval prompt is the real checkpoint — read it before you approve.

Requires Python 3.8+ available as `python3`.

## Tests

- `python3 tests/test_checkpoint.py` — 29 cases: blocked, allowed, asked, review flow, options, and a check that the
  hook writes no files.
- `python3 tests/test_masking.py` — 165 hidden or indirect commands (none may run without a pause), 14 ordinary
  installs (paused for review) and 40 harmless commands (no pause).
- `python3 tests/test_redteam.py` — an independent red-team set: 97 hidden commands (none may run without a pause)
  and 46 ordinary agent commands (installs paused for review, everything else without a pause).

---

## По-русски

**Install Checkpoint** — «сначала проверка, потом установка». Плагин только смотрит и спрашивает: он ничего не меняет
на компьютере и никуда не отправляет данные. Он приостанавливает установку программ и пакетов, скачивание и запуск
скриптов из интернета, подключение MCP-серверов и плагинов, `sudo`, автозапуск и правки настроек Claude.
Правило с версии 0.3.0: команда проходит без паузы, только если понятна целиком. Всё замаскированное или непонятное
(переменная вместо программы, `$(…)`, `eval`, расшифровка base64, код в одну строку, локальные скрипты, скачивание) —
сначала вопрос вам. Необычный синтаксис оболочки и некоторые параметры обычных программ всё ещё могут проскочить;
настоящая защита — окно разрешения.

Почему при установке Claude показывает предупреждение: в плагине есть хук — маленький скрипт, который смотрит на команду
до её запуска. Он не пишет и не удаляет файлы, не запускает другие программы и не выходит в интернет. Агент-проверяющий
умеет только читать и искать в интернете.

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

Данные никуда не отправляются: вердикты лежат локально в папке данных плагина, журнала нет. Ограничение: это страховка,
а не песочница — код внутри файла, записанного раньше, хук не увидит; поэтому запуск локальных скриптов по умолчанию
спрашивает (настройка `pause_unknown`). Главная защита — ваше «да» в окне разрешения.

## License

MIT © 2026 Olga Skrypchenko
