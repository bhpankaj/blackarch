---
name: gemini-cli
description: "Drive Gemini CLI headless; locate mise-installed tools."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Gemini, CLI, Delegation, mise, Headless]
    related_skills: [codex, claude-code, opencode]
---

# gemini-cli — Google Gemini CLI

Peer of `codex`, `claude-code` and `opencode`: an external agent CLI to delegate
work to or script from the terminal. `gemini -p` is the headless entry point.

## When to Use

Use when asked to run, script, or delegate work to Google's Gemini CLI, when asked
whether gemini-cli is available on this machine, or when a `command -v` check
suggests a mise-managed tool is missing — resolving that is rule 1 below.

## Always-On Rules

1. **`command -v <tool>` returning nothing does NOT mean the tool is uninstalled.**
   On a mise-managed box the binary is installed but the shims directory is often
   absent from `PATH` — mise is configured in `~/.config/mise/config.toml` and the
   shims are never wired into the shell rc. Never report a tool as missing on the
   strength of `command -v` alone; resolve it first with `mise which <tool>`. This
   applies to every mise tool, not just gemini (e.g. `copilot`).
2. **Invoke by absolute path when the shim is not on `PATH`** rather than editing
   the user's shell rc unasked. Report the missing `PATH` entry as a suggestion.
3. **Never take a credential through chat.** For API-key auth, have the user write
   the key to `~/.gemini/.env` or export it in their own shell; for OAuth, the user
   must complete the browser consent flow interactively. Do not ask for, echo, or
   accept a key in the conversation.
4. **Check auth state AND the account tier before promising a delegation.** An
   unauthenticated gemini exits 0 while printing an auth error, so a zero exit
   code proves nothing; an *authenticated* consumer account also exits 0 while
   printing `IneligibleTierError`. Only a successful real call (`gemini -p ...`)
   proves gemini is usable. Never propose `oauth-personal` sign-in for a
   consumer Google account — that route is shut down (see Authentication).

## Locating the Binary

```bash
mise which gemini
# ~/.local/share/mise/installs/gemini/latest/node_modules/.bin/gemini
```

Mise layout: `~/.local/share/mise/installs/<tool>/latest/node_modules/.bin/<tool>`,
with shims at `~/.local/share/mise/shims/<tool>` pointing at `mise` itself.

To put shims on `PATH` permanently (offer this, don't impose it). **Check
whether the shell rc is a real file or a symlink into the distro tree before
appending anything** — on this class of machine `~/.zshrc`, `~/.bashrc` and
`~/.bash_profile` are commonly symlinks into the distribution's `defaults/`
directory, so `>>` writes into a package-owned file that the next system update
can overwrite, silently dropping your line:

```bash
ls -la ~/.zshrc    # symlink -> /opt/<distro>/.../defaults/.zshrc  => do NOT append
```

If it is a symlink, replace it with a real file that sources the distro
default, then append:

```bash
# ~/.zshrc  (real file, replacing the symlink)
source /opt/<distro>/defaults/.zshrc
eval "$(mise activate zsh)"
```

The distro file then keeps updating independently and your addition survives.
Put the line in the shell's *interactive* rc (`.zshrc`), not `.zprofile` —
`.zprofile` is read only by login shells, and terminal emulators frequently
launch non-login shells, so a line there may never execute.

## Headless Invocation

```bash
gemini -p "prompt" --skip-trust              # text out
gemini -p "prompt" --skip-trust -o json      # parseable out
```

- `-p` / `--prompt` — non-interactive (headless). Without it you get the TUI.
- `--skip-trust` — trust the workspace for the session; without it a new directory
  triggers a trust prompt that stalls a non-interactive call.
- `-o` / `--output-format` — `text`, `json`, or `stream-json`.
- `--approval-mode` — `default`, `auto_edit`, `yolo`, `plan`. **Use `plan` for
  read-only reconnaissance** and `default` when the user should approve actions;
  `yolo` auto-approves everything including writes.
- `-m` / `--model` — pin a model. `-r` / `--resume latest` — continue a session.

## Authentication (Required)

Unauthenticated, any call prints and exits 0:

```
Please set an Auth method in your ~/.gemini/settings.json or specify one of the
following environment variables before running: GEMINI_API_KEY,
GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_GENAI_USE_GCA
```

Auth methods: `oauth-personal` (Google account sign-in), `gemini-api-key`,
`vertex-ai`, `cloud-shell`.

**Consumer access is shut down.** Google stopped serving Gemini CLI for its
consumer tiers — Gemini Code Assist for individuals (free), Google AI Pro and
Google AI Ultra. The sign-in itself still succeeds and writes
`~/.gemini/oauth_creds.json`, but the first model call is rejected at the
entitlement check with:

```
IneligibleTierError: This client is no longer supported for Gemini Code Assist
for individuals. To continue using Gemini, please migrate to the Antigravity
suite of products: https://antigravity.google
```

Do **not** diagnose this as a broken install, a stale cache, or a wrong
account — reinstalling, clearing `~/.gemini`, and signing in with a different
personal Google account all reproduce it. Read the tier the error reports
(`free-tier` / "Gemini Code Assist for individuals") before proposing any fix.

| Route | How | Status |
|-------|-----|--------|
| `oauth-personal` | run `gemini` once interactively, complete browser consent | **dead for consumer accounts — do not propose it** |
| `gemini-api-key` (paid) | `GEMINI_API_KEY` in env, or in `~/.gemini/.env` | works |
| `vertex-ai` | `GOOGLE_GENAI_USE_VERTEXAI` + `GOOGLE_CLOUD_PROJECT` | works |
| Code Assist Standard/Enterprise org account | org-managed sign-in | works |

The consumer replacement is **Antigravity CLI**, a closed-source Go binary
invoked as `agy` (`curl -fsSL https://antigravity.google/cli/install.sh | bash`).
Its free tier is far tighter than the old Gemini CLI free tier (roughly 20
requests/day vs ~1000), so price that in before recommending a migration.

**Presence of `~/.gemini/oauth_creds.json` is NOT proof that gemini works.** A
consumer sign-in writes that file and then fails every call. The only reliable
auth check is a real call:

```bash
gemini -p "reply with exactly: PONG" --skip-trust
```

For a `free-tier` account that check fails — say so plainly instead of
presenting gemini as available. The API-key free tier (~250 requests/day,
Flash models only) is a separate quota from the Code Assist tier and may or may
not satisfy the CLI's entitlement check; treat it as unverified until a real
call succeeds.

## Beyond Headless Prompts

`gemini` also exposes `mcp` (MCP server management), `extensions`, `skills`,
`hooks`, and `gemma` (local model routing) subcommands — relevant when wiring it
into a larger agent setup.

## Pitfalls

- **Concluding "not installed" from `command -v`.** The mise case above is the
  common trap on this class of machine; it costs a wrong answer to the user.
- **Treating exit code 0 as success.** The auth error exits 0. Assert on the
  output, not the status.
- **Launching the TUI in a non-TTY context.** Omitting `-p` starts interactive
  mode, which cannot run in a background/non-TTY tool call.
- **Offering a fix for a shutdown that is not a bug.** The consumer
  `IneligibleTierError` is policy, not misconfiguration. Retrying OAuth,
  clearing `~/.gemini`, or switching accounts is wasted effort and reads as not
  knowing the product — check the reported tier first.
- **Appending to a symlinked shell rc.** On this class of machine the rc files
  point into the distro tree; a `>>` there is lost on the next system update.
  See Locating the Binary.
