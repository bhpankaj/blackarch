# Menu loading and live debugging

## How the shell loads menus

- `default/blackarch/blackarch-menu.jsonc` — static default menu, loaded by a FileView.
- `default/blackarch/menus/*.jsonc` — generated per-source files, globbed by a bash Process.

Quickshell 0.3.2 has no `dirContents` API. The menu plugin globs with a Process:

    command: ["bash", "-c", "dir=$0; [[ -d \"$dir\" ]] || exit 0; shopt -s nullglob; for f in \"$dir\"/*.jsonc; do [[ -f \"$f\" ]] || continue; printf '===%s===\\n' \"$f\"; cat \"$f\"; printf '\\n=== EOM ===\\n'; done", root.userMenuDir]

Parse the output by splitting on `===<path>===` / `=== EOM ===` markers. A directory `FileView` (watchChanges) re-runs the scan on change; `blackarch menu refresh` re-runs it on demand. The agents plugin uses the same glob-and-markers pattern for its usage records.

## Restart vs refresh

- QML/JS changes (`Menu.qml`, `MenuModel.js`) need `blackarch-restart-shell`.
- Data changes (`menus/*.jsonc`, `blackarch-menu.jsonc`) are picked up by the directory watch or `blackarch menu refresh`; no restart.
- The reload is asynchronous: after a regenerate, wait a moment or close/reopen the menu before judging it.

## Debugging a branch that is missing or empty

Run `scripts/verify-menu-row.js <menu.jsonc> <row-id>` first: it loads the real `MenuModel.js` in node and reports the row's kind, parent, whether the parent exists and is a menu, visibility with `when:` true and false, and the guard line — the same parser the shell uses. Then:

1. Confirm the generator wrote the file and the ids are right: `python3 -c "import json; d=json.load(open('<file>')); print([k for k in d if k.count('.')==0])"`.
2. Confirm the shell parsed it. The Process is silent on success, so add a temporary `console.log` in `parseUserMenuOutput` (item count) and `rebuildItemsFromSources` (default/user/merged counts plus a probe id's parent/kind); read them with `journalctl --user -n 30 --no-pager | grep ...`.
3. If the merge count is right but the branch is hidden, the culprit is `isVisible`: a `kind:"menu"` row is hidden when none of its descendants are visible. Check the provider row swaps first — `mergeAppRows` and `swapProviderRows` remove rows by kind/parent, and a swap that drops another source's rows leaves the branch empty (this is the `mergeAppRows` pitfall in SKILL.md).
4. `isVisible` hides `kind:"menu"`/`"link"` rows with no visible children; `kind:"app"` rows are always visible; provider-backed menus stay visible.

## SmartThings widget

Reads `default/blackarch/menus/smartthings.jsonc` and extracts `smartthings.<uuid>` keys. `blackarch smartthings widget` summons it; it is not a persistent bar widget.
