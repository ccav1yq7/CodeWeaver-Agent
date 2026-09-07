# Security boundary

Model output and repository text are untrusted. The workspace owner, selected provider, explicitly chosen
MCP programs, installed software and user-supplied evaluation manifests are trusted.

- Explicit denies precede modes and approval. No shell-prefix whitelist or bypass mode exists.
- File tools reject traversal, symlinks and control/credential paths; edits compare hashes before atomic replacement.
- Commands require Linux bubblewrap, a new network namespace, a minimal environment, read-only system
  mounts and the writable workspace. Personal home directories are not mounted. Known credential/control
  paths in the workspace are overlaid. Isolation startup failure prevents command execution.
- Known credential filenames are not a general secret classifier: do not put secrets in ordinary source files
  exposed to a model. Selected code and tool output can be sent to the chosen provider.
- The owner must not concurrently replace the workspace root/mount. Hash checks are optimistic, not
  transactional locks against unrelated host programs. Such edits require rereads.
- Fixed Git operations disable hooks/fsmonitor/external diff and reject local checkout filter programs.
  Worktrees support trusted local repositories and are not kernel boundaries.
- MCP programs are explicitly approved host processes with environment allowlists; they are not claimed to
  run inside the command sandbox. Read-only mode denies external calls.
- Browser mode binds only 127.0.0.1, requires a token, checks Host/Origin and binds approvals to one connection.
  The token holder is trusted as the local user. Do not expose it through a public reverse proxy.
- Local journals contain private source/results. Do not publish `.codeweaver/`, configs or raw evaluations.
  Interrupted side effects are never automatically replayed.

Use private vulnerability reporting when enabled on the repository. Otherwise ask for a private contact in
an issue without posting credentials or exploit details. Unsupported command platforms fail closed.
