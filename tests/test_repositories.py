import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from codeweaver.configuration import Settings
from codeweaver.evaluation import Task, evaluate
from codeweaver.process import capture
from codeweaver.repositories import diff, git, snapshot


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "answer.py").write_text("ANSWER = 1\n")
    (root / ".gitignore").write_text(".codeweaver/\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    return root


async def test_worktree_does_not_change_original(repository):
    work = await snapshot(repository)
    try:
        (work / "answer.py").write_text("ANSWER = 2\n")
        assert (repository / "answer.py").read_text() == "ANSWER = 1\n"
        assert "+ANSWER = 2" in (await diff(work))["output"]
    finally:
        await git(repository, "worktree", "remove", "--force", str(work))


async def test_git_diff_omits_tracked_credentials(repository):
    (repository / ".env").write_text("placeholder-old")
    subprocess.run(["git", "-C", str(repository), "add", ".env"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "sensitive fixture",
        ],
        check=True,
    )
    (repository / ".env").write_text("placeholder-new")
    assert "placeholder" not in (await diff(repository))["output"]


async def test_nested_workspace_cannot_read_parent_repository(repository):
    nested = repository / "nested"
    nested.mkdir()
    with pytest.raises(ValueError, match="repository root"):
        await diff(nested)


async def test_new_files_without_final_newline_produce_applicable_patches(repository, tmp_path):
    (repository / "new.txt").write_text("no final newline")
    patch_file = tmp_path / "candidate.patch"
    patch_file.write_text((await diff(repository))["output"])
    work = await snapshot(repository)
    try:
        result = await git(work, "apply", str(patch_file))
        assert result["exit_code"] == 0, result
        assert (work / "new.txt").read_text() == "no final newline"
    finally:
        await git(repository, "worktree", "remove", "--force", str(work))


class Repair:
    def __init__(self):
        self.turn = 0

    async def reply(self, instructions, messages, tools):
        from codeweaver.filesystem import digest

        self.turn += 1
        if self.turn == 1:
            return {
                "role": "assistant",
                "text": "",
                "calls": [
                    {
                        "id": "fix",
                        "name": "write_file",
                        "arguments": {
                            "path": "answer.py",
                            "content": "ANSWER = 2\n",
                            "expected_sha256": digest(b"ANSWER = 1\n"),
                        },
                    }
                ],
            }
        return {"role": "assistant", "text": "fixed", "calls": []}


async def test_hidden_grader_is_separate_and_baseline_failure_required(repository, tmp_path):
    sha = (await git(repository, "rev-parse", "HEAD"))["output"].strip()
    hidden = tmp_path / "hidden.patch"
    hidden.write_text(
        "diff --git a/check.py b/check.py\nnew file mode 100644\n--- /dev/null\n+++ b/check.py\n@@ -0,0 +1,2 @@\n+from answer import ANSWER\n+assert ANSWER == 2\n"
    )
    task = Task(
        id="repair",
        repository=repository,
        commit=sha,
        prompt="Set ANSWER to two",
        grade_argv=["/usr/bin/python3", "check.py"],
        hidden_patch=hidden,
        allowed_paths=["answer.py"],
    )

    async def trusted_fixture_runner(root, argv, timeout):
        return await capture(argv, root, timeout)

    # This tests grading separation, not kernel isolation; trusted local test programs only.
    with patch("codeweaver.evaluation.execute", trusted_fixture_runner):
        result = await evaluate(
            task, Settings(provider="demo", mode="workspace"), tmp_path / "results", model=Repair()
        )
    try:
        assert result["resolved"], result
        assert result["baseline"]["exit_code"] == 1
        assert not (Path(result["worktrees"][1]) / "check.py").exists()
        assert (repository / "answer.py").read_text() == "ANSWER = 1\n"
    finally:
        for path in result["worktrees"]:
            await git(repository, "worktree", "remove", "--force", path)
