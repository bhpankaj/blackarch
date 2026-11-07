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
- Wrapper argument convention must match the module's `main()` signature: if the module inspects `sys.argv` internally, call `main(sys.argv)`; if it takes an explicit argv list, call `main(sys.argv[1:])`. A mismatch silently disables flags such as `--shell`.
- When a Python port replaces a bash script that runs an interactive selector and then acts on its selection, capture the selector's stdout and invoke the follow-up command (e.g. `blackarch-theme-bg-set`) instead of `os.execvp`ing the selector.
- `blackarch-powerprofiles-list` must emit the active profile as `name\t1` (and others as bare names) so the QML `parseProfiles` can mark the active button; a bare list leaves no active selection.
- When a shared helper module (e.g. `blackarch_helpers`) already provides the logic, remove the corresponding bash helper files and rely on the Python module; leave the empty directory in place unless asked.
