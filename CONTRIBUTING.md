# Contributing

Use Python 3.11+ and `uv sync --locked --all-extras`. Run pytest, Ruff and `uv build` before submitting.
Add behavioral regressions for changes to authorization, persistence or provider protocols.

Do not copy code with uncertain provenance. Record source and notices for any future vendored material.
Keep credentials, provider traces, evaluation repositories and runtime data out of Git.

Test rejection paths as well as successful calls. Browser changes must exercise missing authentication,
Host/Origin rejection, cancellation and approval isolation. Fake-model tests are not benchmark scores.
