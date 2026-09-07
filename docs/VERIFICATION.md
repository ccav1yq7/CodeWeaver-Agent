# Verification — 2026-09-07

The new implementation's independent suite passes **52 tests** on Linux with Python 3.11 and 3.13.
It covers file/path protection, stale edits, permission precedence, missing-sandbox rejection, subprocess
output/timeout cleanup, bounded turns, recovery, provider payloads, context pairing, isolated grading,
worktree separation, MCP SDK stdio handshake/calls, authenticated browser approvals and Textual input.

The grading test uses a trusted synthetic repository and a fake model. Its subprocess runner is injected
to test hidden-test separation independently of kernel namespace availability. It is not a model benchmark.

The host's real bubblewrap probe failed while configuring its network namespace (`Operation not permitted`).
The application fails closed in this case. A successful real sandbox command on this host is **not claimed**.
Real provider calls, paid-model task quality, the native Tk display, macOS and Windows were not exercised.

Ruff checks/formatting and wheel/sdist builds are release checks. Package/source inventories and redacted
secret scan logs are retained by the release owner outside the source package. Comparison with the legacy
tree found at most two contiguous normalized nontrivial matching lines per new source file; this heuristic
does not prove independent provenance or constitute a legal clean-room certification.

No legacy 621-test or SWE-bench result applies to this release. All new performance/success claims require
a fresh evaluation tied to its source commit, model configuration and environment.
