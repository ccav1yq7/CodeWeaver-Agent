"""Fixed Git operations on user-trusted local repositories; never execute model shell text."""

import re
import tempfile
from pathlib import Path

from .process import capture


async def git(root: Path, *arguments: str, timeout: int = 30) -> dict:
    prefix = ["git", "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"]
    environment = {
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
    }
    location = await capture(
        [*prefix, "rev-parse", "--show-toplevel"], root, timeout, environment=environment
    )
    if location["exit_code"] or Path(location["output"].strip()).resolve() != root.resolve():
        raise ValueError("Git tools require the workspace itself to be the repository root")
    return await capture([*prefix, *arguments], root, timeout, environment=environment)


async def snapshot(root: Path, commit: str = "HEAD") -> Path:
    if commit != "HEAD" and not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise ValueError("A full commit SHA is required")
    # Checkout can execute filter drivers configured in a local repository.
    filters = await git(root, "config", "--local", "--get-regexp", r"^filter\..*\.(smudge|process)$")
    if filters["exit_code"] not in {0, 1} or filters["output"].strip():
        raise ValueError("Repositories with checkout filter programs are not supported")
    path = Path(tempfile.mkdtemp(prefix="codeweaver-worktree-"))
    result = await git(root, "worktree", "add", "--detach", str(path), commit)
    if result["exit_code"]:
        path.rmdir()
        raise ValueError("Could not create isolated worktree: " + result["output"][:500])
    return path


async def diff(root: Path) -> dict:
    # Include new text files without mutating the index.
    import difflib

    from .filesystem import Workspace

    scope = Workspace(root)
    changed = await git(root, "diff", "--name-only", "-z", "HEAD")
    safe = []
    for name in changed["output"].split("\0"):
        try:
            scope.parts(name)
        except ValueError:
            continue
        safe.append(":(literal)" + name)
    result = (
        await git(root, "diff", "--no-ext-diff", "--no-textconv", "HEAD", "--", *safe)
        if safe
        else {"output": "", "exit_code": 0, "truncated": False}
    )
    untracked = await git(root, "ls-files", "--others", "--exclude-standard", "-z")
    additions = []
    for name in untracked["output"].split("\0"):
        if not name:
            continue
        try:
            text = scope.read(name)["content"]
        except (ValueError, OSError):
            continue
        if not text:
            additions.append(f"diff --git a/{name} b/{name}\nnew file mode 100644\nindex 0000000..e69de29\n")
        else:
            for line in difflib.unified_diff(
                [], text.splitlines(True), fromfile="/dev/null", tofile="b/" + name
            ):
                additions.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    result["output"] += "".join(additions)
    if len(result["output"]) > 64000:
        result["output"] = result["output"][:64000]
        result["truncated"] = True
    return result


def install_git_tools(tools):
    from .capabilities import Empty

    async def status(args):
        return await git(tools.workspace.root, "status", "--short", "--untracked-files=normal")

    async def patch(args):
        return await diff(tools.workspace.root)

    tools.add("git_status", "Show working tree changes in a trusted local repository", Empty, "read", status)
    tools.add(
        "git_diff", "Show tracked and new text-file changes without modifying the index", Empty, "read", patch
    )
