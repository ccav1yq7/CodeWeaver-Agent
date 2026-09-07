# Implementation provenance

This tree was authored anew on 2026-09-07 from coding-agent feature requirements and the behavioral failures
recorded in the publication review. Legacy implementation files, tests, prompts, UI assets, course materials
and bundled third-party repositories are not copied or imported here. The new architecture uses typed
capabilities, descriptor-relative access, mandatory argv sandboxing and a SQLite operation journal.

The implementing assistant previously inspected legacy code during review. This is **not a claim of a formal
clean-room process**, nor a legal opinion about that source. Deleting notices alone would not establish a new
implementation; this directory replaces the implementation and documents its scope. The old source must not
be included in the new repository's history or packages.

MIT applies to this tree's own code. Standard language idioms, API field names and the MIT license text are
not claimed as novel inventions. Libraries are consumed as packages, not vendored; versions/hashes are in `uv.lock`.

Primary references:

- OpenAI: https://developers.openai.com/api/docs/guides/function-calling
- Anthropic: https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
- MCP SDK: https://github.com/modelcontextprotocol/python-sdk
- bubblewrap: https://github.com/containers/bubblewrap
- Textual: https://textual.textualize.io/
- Python: https://docs.python.org/3/library/os.html · https://docs.python.org/3/library/sqlite3.html

The release must begin with new Git history. Leaving the legacy tree in an earlier public commit would defeat
the intended separation even if the default branch's latest files contained only this implementation.
