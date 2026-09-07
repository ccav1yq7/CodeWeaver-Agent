# CodeWeaver Agent

A coding assistant built around explicit capabilities, a bounded tool loop and a local execution journal.
This is the new **1.0 alpha** implementation. Source, tests, prompts and interfaces were written anew;
the legacy implementation is not a dependency or part of this package. See [provenance](PROVENANCE.md)
and [migration](docs/MIGRATION.md).

## Quick start

Python 3.11+ on Linux. File tools require POSIX descriptor-relative APIs; command execution additionally
requires an operational `bwrap` installation and permitted user/network namespaces. No unsandboxed fallback.
The native Tk client also needs your distribution's Python Tk package.
Ubuntu 24.04 additionally restricts capabilities in unprivileged user namespaces. An administrator must
permit the sandbox launcher through an appropriate AppArmor profile; see the
[Ubuntu release notes](https://documentation.ubuntu.com/release-notes/24.04/#unprivileged-user-namespace-restrictions).
CI uses `examples/bwrap.apparmor` for `/usr/bin/bwrap` on its disposable Ubuntu 24.04 runner. The application
does not install that profile or alter host security settings itself.

```bash
uv sync --locked --all-extras
uv run --no-sync codeweaver --provider demo -p "Inspect the workspace"
# Set OPENAI_API_KEY in your shell, then choose your model:
uv run --no-sync codeweaver --model YOUR_OPENAI_MODEL
# Or set ANTHROPIC_API_KEY:
uv run --no-sync codeweaver --provider anthropic --model YOUR_ANTHROPIC_MODEL
```

The offline demo only lists files and returns a fixed explanation; it is not a coding model.
No config file is required. `CODEWEAVER_MODEL`, `CODEWEAVER_PROVIDER` and `CODEWEAVER_BASE_URL` override defaults.
Credentials come from environment variables, never literal config fields. An optional explicitly selected
TOML config is shown in [examples/config.toml](examples/config.toml). Repository config is not auto-loaded.

## Permissions and sessions

`review` reads workspace files and asks before mutations, commands and external tools. `workspace` permits
file edits and memory writes; commands still require approval or an exact user-configured argv entry.
`read-only` denies all mutations, commands and external calls. Explicit `deny_tools` always take precedence.

Writes require the SHA-256 returned by `read_file`, reject stale versions, and replace files atomically.
Symlink components, traversal, credential names and control paths are rejected. Commands are argv arrays,
not implicitly parsed shell scripts. An approved shell executable still runs inside the mandatory networkless
sandbox. Native file tools use descriptor-relative checks, not the subprocess sandbox. See [SECURITY.md](SECURITY.md).

```bash
uv run --no-sync codeweaver --mode workspace -p "Fix the parser and add a regression test"
uv run --no-sync codeweaver --resume SESSION_ID
uv run --no-sync codeweaver --json --provider demo -p "Inspect"
```

Noninteractive mode never reads approval from stdin. Unapproved actions return errors to the model.
A completed model turn is not a passing test score. The private `.codeweaver/` directory stores sessions,
tool receipts and durable notes. Interrupted calls are not automatically replayed. Context reduction archives
whole assistant/tool groups and retains the current request; this is deterministic reduction, not a claimed
semantic summary. Full conversations remain local.

Console commands: `/sessions`, `/memory`, `/remember NAME TEXT`, `/quit`. The model may propose durable
strategies through `remember`, subject to permissions; no background process silently changes prompts or skills.

## Interfaces and extensions

```bash
uv run --no-sync codeweaver --tui
uv run --no-sync codeweaver --desktop
uv run --no-sync codeweaver --skill /path/to/reviewed/SKILL.md
uv run --no-sync codeweaver --config /path/to/user/config.toml --mcp
```

- Console, optional Textual TUI and native Tk desktop use the same runtime and authorization.
- Selected Markdown skills provide context; they cannot grant permissions or install code.
- Optional MCP uses official SDK stdio transport. Starting a configured server and invoking tools require
  separate approvals. Only explicitly named environment variables are forwarded.
- `delegate` runs up to three bounded workers. Inspection is read-only; edit workers start at HEAD in detached
  worktrees. Parent uncommitted edits are not copied. Children cannot redelegate, auto-merge or approve their
  own commands. Returned patches and preserved worktrees require review.
- Worktrees provide version-control separation, not kernel isolation.
- Runtime events and JSON output expose assistant turns, tool starts/results, compaction, failure and cancellation.
  Repository-defined executable hooks are not automatically loaded.

Browser mode is optional and **loopback only**. Set `CODEWEAVER_REMOTE_TOKEN` to a random URL-safe token of
at least 32 characters, generated for example with Python's `secrets.token_urlsafe(32)`, then run
`uv run --no-sync codeweaver --remote`. Open `http://127.0.0.1:18888` and enter that token. Authentication,
exact Origin/Host and connection-scoped approval IDs are enforced. Tokens are not in URLs or embedded pages.
Disconnect cancels pending work. This is not a public multi-user hosting service.

## Evaluation

`codeweaver-eval` accepts trusted local task manifests pinned to full commits. It verifies baseline failure
in a separate hidden-test worktree, runs the Agent without that patch, checks changed paths, and grades a
fresh worktree with the candidate and hidden tests. Grader commands also require bubblewrap. Raw patches,
results and worktrees stay local for inspection.

```bash
# Replace template paths and commit first; choose workspace mode to permit Agent edits.
uv run --no-sync codeweaver-eval examples/task.template.json --config examples/config.toml
```

Included tests use independent synthetic repositories and fake models. No SWE-bench success rate or legacy
621-test result is claimed. Paid-model coding quality requires a new evaluation.

## Development

```bash
uv sync --locked --all-extras
uv run --no-sync pytest
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
uv build
```

Tests cover paths, stale edits, deny precedence, subprocess cleanup, provider payloads, receipts, hidden grading,
worktrees, MCP and browser authentication. Check [verification](docs/VERIFICATION.md) for environmental limits.
Code is MIT; dependencies and provider services retain their own terms. Questions, selected source and tool
output are sent to the chosen provider; journals stay local.
