# Migrating from the private legacy tree

This new 1.0 alpha is not import-compatible with the legacy package.

| Legacy area | New implementation |
| --- | --- |
| Agent/providers | `engine.py`, `models.py`: bounded serializable turns |
| Permission layers | `authorization.py`: deny first, explicit capabilities |
| File tools | `filesystem.py`, `capabilities.py`: previews, descriptor-relative paths, hashes |
| Sandbox | `process.py`: mandatory Linux bubblewrap |
| Recovery | `records.py`: SQLite journal and operation receipts |
| Context/memory | Whole-group reduction and permission-controlled durable notes |
| Teams | Up to three bounded inspect/edit workers, detached worktrees |
| Interfaces | Newly written Textual, Tk and authenticated loopback browser clients |
| MCP/skills | Explicit stdio servers and selected Markdown references |
| Evaluation | New manifest and separate hidden grader |

Do not copy legacy Python modules, YAML config, runtime directories, prompt templates or skill bundles here.
Select your provider through environment variables or the explicit TOML format. Migrate only your own notes
after review. Old `default/acceptEdits/plan/bypassPermissions` modes become `review/workspace/read-only`.

The basename plan exemption, shell prefix grants, unauthenticated server, automatic skill installation and
background prompt mutation are intentionally absent. MacOS Seatbelt, tmux/iTerm2 workers and the former Qt
desktop are not carried over; the new desktop uses Tk and the current command backend is Linux-only.
This is not full legacy platform parity. Old test counts and benchmark results do not apply.

The legacy directory stays private for traceability. The new release must not inherit its Git history.
