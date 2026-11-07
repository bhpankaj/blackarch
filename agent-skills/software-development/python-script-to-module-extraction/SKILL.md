---
name: python-script-to-module-extraction
description: Use when extracting a Python script into module and wrapper.
---

# Python Script to Module Extraction

## When to Use
Use this when a user asks to pull every function out of an existing Python script into a module and expose the same behavior through a new entry point, while leaving the original file untouched.

## Procedure
1. Copy the original script to a module file (same directory, `.py` suffix) and compile it to catch syntax errors.
2. Create a new executable wrapper that inserts its own directory into `sys.path`.
3. Import the module with `from <module> import *` for public names.
4. Explicitly import private names that the entry point needs, such as `_entry` or `main`, because star imports omit underscore-prefixed names.
5. Invoke the original entry point in the wrapper's `__main__` guard, preserving argument handling and cleanup.
6. Compile the wrapper and run `--help` to verify it starts and exits successfully.
7. When merging multiple extracted modules, import each under an alias and call the original `parse_args`/`main` flow instead of passing raw argv lists to `main`.

## Pitfalls
- `from module import *` does not import names beginning with `_`; import those explicitly.
- Do not edit the original script; create copies and wrappers beside it.
- Keep the module in the same directory as the wrapper so the relative import path works when invoked by absolute path.
- Call the original `parse_args` before `main` if `main` expects an argparse namespace, not a raw argv list.
- Verify with `python3 -m py_compile` and a real `--help` run before declaring success.
- When integrating extracted modules into a dispatcher that globs executable wrappers, keep the import/call logic in the dispatcher entry point (or its core module) so commands still work after wrapper files are removed; insert the module directory into `sys.path` before importing.
- Extracted modules' `main()` signatures vary (no args, argv list, or argparse namespace); a generic runner should try `main()`, `main(argv)`, and `parse_args`+`main(args=...)` in that order.
- Removing exec bits from original wrappers makes the dispatcher stop listing them; restore exec bits or add module-backed command handling before removing them if discovery must be preserved.
- If modules are moved into a package directory, update every internal `import`/`from ... import` in those modules to the new package path, and update the dispatcher's `sys.path`/import statements accordingly. Run a real command (`--help` or a subcommand) after the move, not just `py_compile`.
- When a generic runner joins command words into a module name, try progressively shorter prefixes (`restart shell --help` → `restart_shell` → `restart`) so subcommand groups resolve to their base module; pass only the remaining words to `main()`.
- Modules whose `main()` takes no arguments must be called as `main()`; passing `[]` or argv raises `TypeError`. A generic runner should try `main(rest)`, `main(argv)`, then `main()` in that order.
- When a function is only available as a no-arg entry point (e.g. `main()`), create thin per-subcommand modules (e.g. `blackarch_restart_shell.py`) that delegate to it rather than forcing the base module to accept arguments.
- When copying a directory of scripts into a module package, skip files whose shebang is `bash`/`sh`; keep them in a separate `bash_scripts/` directory so the package stays importable and Python-only.
- When a module is moved into a package directory, rewrite all its internal imports to the package path (`blackarch_modules.<name>`) and update every dispatcher/importer that references the old top-level module name.
- When a dispatcher's `BLACKARCH_BIN_DIR` points at the module package instead of `bin/`, commands disappear; set it to the directory containing the executable wrappers.
- When unported bash scripts remain in `bin/`, add a dispatcher fallback that runs them with `bash <script>` and prints the script name after exit.
- When unported bash scripts are left in `bin/`, add a dispatcher fallback that invokes them with `bash <script>` and prints the script name after exit, so users see completion status.
- A new blackarch command needs BOTH a module in `blackarch_modules/` (so importlib resolves `blackarch_modules.blackarch_<name>`) AND a python-shebang entry in `bin/` (for direct invocation); a bin-only Python file is not discovered by the dispatcher because its fallback runs bin files with `bash`.
- When porting a bash script that delegates to another module, set `sys.argv` to the intended arguments before calling that module's no-arg `main()`; do not pass a list to a `main()` that reads `sys.argv`.
- When porting environment-sensitive scripts (display/monitor rotation, autorotate), read and preserve the current GTK text-scaling-factor and monitor scale instead of overwriting them, and print them after each transformation.
- When a command is renamed (e.g. `blackarch-commander` → `blackarch execute`, `blackarch-installer` → `blackarch install`), add a thin module alias (`blackarch_execute`, `blackarch_install`) that re-exports the original module's `main()` so the generic runner resolves the new command name without code changes elsewhere.
- When a module alias wraps a no-arg `main()` that reads `sys.argv`, set `sys.argv` to the intended arguments before calling it; do not pass a list.
- After editing module files by heredoc, check for stray terminator lines (`PY`) and compile every touched file before declaring success.
