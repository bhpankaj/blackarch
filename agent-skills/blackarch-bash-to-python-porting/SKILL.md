---
name: blackarch-bash-to-python-porting
description: Port blackarch bash scripts to Python modules.
---

## When to Use
Porting a `blackarch-*` bash script to Python while preserving dispatcher compatibility and Hyprland/Quickshell configs.

## Procedure
1. Copy the bash script to `/opt/blackarch/blackarch_modules/blackarch_<name>.py` (hyphens to underscores), replacing `#!/bin/bash` with `#!/usr/bin/env python3`.
2. Implement equivalent logic in Python using subprocess for external commands; keep all functions in the module.
3. Create a thin wrapper in `/opt/blackarch/bin/blackarch-<name>` that inserts `/opt/blackarch` into sys.path and calls `blackarch_modules.<name>.main(sys.argv[1:])`.
4. Make the wrapper executable; leave the original bash script in place (or move to bash_scripts only when explicitly asked).
5. For commands with subcommands, use the generic runner in `blackarch` that imports `blackarch_modules.blackarch_<joined_args>` and calls main with remaining args.
6. Verify with `python3 -m py_compile` and a `--help`/smoke run.

## Pitfalls
- When the script already lives in `/opt/blackarch/bin` (not `old_repo/bin`), port it in place: overwrite the file with a Python shebang and keep the same basename; do not create a separate module+wrapper.
- Module main signatures vary (some take argv, some take none); wrappers should try `main(argv)`, then `main()`.
- Bash scripts that are thin launchers should delegate to the real Python module rather than reimplement logic.
- Do not remove exec bits from Python wrappers if Hyprland/Quickshell configs invoke them by name on PATH.
- Keep bash scripts untouched unless the user explicitly asks to port them.
- When porting a bash script that delegates to another module, set `sys.argv` to the intended arguments before calling that module's no-arg `main()`; do not pass a list to a `main()` that reads `sys.argv`.
- When porting environment-sensitive scripts (display/monitor rotation, autorotate), read and preserve the current GTK text-scaling-factor and monitor scale instead of overwriting them, and print them after each transformation.
- When a script is a thin launcher to another module, create a thin Python module that delegates instead of reimplementing logic.
- When unported bash scripts remain in `bin/`, add a dispatcher fallback that runs them with `bash <script>` and prints the script name after exit.
- When a command is renamed, add a thin module alias that re-exports the original module's `main()` so the generic runner resolves the new name.
- After editing module files by heredoc, check for stray terminator lines (`PY`) and compile every touched file before declaring success.
- System commands invoked from a Python port (e.g. `powerprofilesctl`) must be called by absolute path (`/usr/bin/powerprofilesctl`) and their shebangs must point at `/usr/bin/python3`, not `#!/usr/bin/env python3`, because the ambient PATH may put a venv's Python first and that venv may lack system modules such as `gi`.
- Thin bash launchers for a ported command family must exec the actual dispatcher (`blackarch-<family>`), never a nonexistent `<family>.py` file.
- When a ported command is a subcommand of a group (e.g. `setup post`), expose it as an executable in `bin/` so the dispatcher discovers it; the dispatcher routes the group (`setup`) to `execute_core.main`, which dispatches the subcommand. Do not delete the bin entry expecting the module alone to register it.
- A ported command needs BOTH a `blackarch_modules/blackarch_<name>.py` module exposing `main()` and an executable `bin/blackarch-<name>` wrapper; the dispatcher imports the module first and only falls back to bash, which would mis-execute Python as shell if the module is missing.
- When porting a script that is driven by a systemd user timer/service, keep the unit files pointing at the new Python executable, deploy them from defaults into `~/.config/systemd/user/` during setup-post, and enable the timer; removing the user symlink without redeploying the units breaks the timer.
- Wrapper argument convention must match the module's `main()` signature: if the module inspects `sys.argv` internally, call `main(sys.argv)`; if it takes an explicit argv list, call `main(sys.argv[1:])`. A mismatch silently disables flags such as `--shell`.
- When merging several related scripts into one Python module, expose each former script's behavior as a flag (e.g. `--shell`, `--low <arg>`) on that module's `main()` and turn the original per-script entry points into thin wrappers that prepend the flag to `sys.argv` and `execv` the merged module. This keeps dispatcher compatibility and avoids duplicated logic.
- When merging, alias common alternate spellings of a flag (e.g. `--status` for `--shell`, `--remaning` for `--remaining`) so existing callers and typos keep working, and print a `--help`/`-h` usage listing every flag.
- When a Python port replaces a bash script that runs an interactive selector and then acts on its selection, capture the selector's stdout and invoke the follow-up command (e.g. `blackarch-theme-bg-set`) instead of `os.execvp`ing the selector.
- `blackarch-powerprofiles-list` must emit the active profile as `name\t1` (and others as bare names) so the QML `parseProfiles` can mark the active button; a bare list leaves no active selection.
- When a shared helper module (e.g. `blackarch_helpers`) already provides the logic, remove the corresponding bash helper files and rely on the Python module; leave the empty directory in place unless asked.
- A shell pipeline (`curl ... | bash`) must NOT be ported as separate argv items: `sudo_run(["curl", url, "|", "bash"])` execs argv directly with no shell, so curl downloads the script to stdout and then fails on `|` and `bash` as URLs (`curl: (3) URL rejected: Bad hostname`). Use `sudo_run(["bash", "-c", "curl -fsSL <url> | bash"])` (mirror the existing `setup_ollama` idiom), and add `-f` + `set -o pipefail` so a failed download aborts instead of running empty input.
