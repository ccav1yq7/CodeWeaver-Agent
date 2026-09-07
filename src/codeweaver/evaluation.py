"""Trusted local task evaluation with a separate hidden-test worktree.

No dataset, official patch, cloned repository or task trace is shipped in releases.
The manifest and grader programs are explicitly user-trusted inputs.
"""

import argparse
import asyncio
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .configuration import load_settings
from .filesystem import Workspace
from .models import ModelError
from .process import execute
from .repositories import diff, git, snapshot
from .runtime import session


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    repository: Path
    commit: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    prompt: str
    grade_argv: list[str] = Field(min_length=1)
    hidden_patch: Path | None = None
    allowed_paths: list[str] = Field(min_length=1)
    baseline_exit: int = Field(default=1, ge=1, le=125)
    timeout: int = Field(default=60, ge=1, le=600)


async def apply_patch(root, path):
    if path is not None:
        for command in (("apply", "--check", str(path.resolve())), ("apply", str(path.resolve()))):
            result = await git(root, *command)
            if result["exit_code"]:
                raise ValueError("Patch could not be applied")


async def evaluate(task: Task, settings, output: Path, *, model=None):
    output.mkdir(parents=True, exist_ok=True)
    result = {"task": task.id, "commit": task.commit, "status": "setup_failed", "resolved": False}
    paths = []
    try:
        task.repository = task.repository.resolve(strict=True)
        for name in task.allowed_paths:
            Workspace(task.repository).parts(name)
        grader = await snapshot(task.repository, task.commit)
        paths.append(grader)
        await apply_patch(grader, task.hidden_patch)
        baseline = await execute(grader, task.grade_argv, task.timeout)
        result["baseline"] = baseline
        if baseline["exit_code"] != task.baseline_exit:
            result["status"] = "precheck_not_expected"
            return result
        work = await snapshot(task.repository, task.commit)
        paths.append(work)
        result["status"] = "agent_failed"
        async with session(work, settings, model=model) as agent:
            result["agent"] = await agent.run(task.prompt)
        if result["agent"]["status"] != "completed":
            result["status"] = "budget_exhausted"
            return result
        names = await git(work, "diff", "--name-only", "-z", "HEAD")
        new = await git(work, "ls-files", "--others", "--exclude-standard", "-z")
        changed = [
            n for n in (names["output"] + new["output"]).split("\0") if n and not n.startswith(".codeweaver/")
        ]
        if not changed or any(
            not any(n == p or n.startswith(p.rstrip("/") + "/") for p in task.allowed_paths) for n in changed
        ):
            result["status"] = "patch_scope_failed"
            return result
        patch = await diff(work)
        if patch["truncated"]:
            result["status"] = "patch_too_large"
            return result
        candidate = output / f"{task.id}.patch"
        candidate.write_text(patch["output"])
        result["status"] = "grader_failed"
        # Recreate grading state: candidate first, then trusted hidden tests.
        final_grader = await snapshot(task.repository, task.commit)
        paths.append(final_grader)
        await apply_patch(final_grader, candidate)
        await apply_patch(final_grader, task.hidden_patch)
        grade = await execute(final_grader, task.grade_argv, task.timeout)
        result.update(
            grade=grade,
            resolved=grade["exit_code"] == 0,
            status="resolved" if grade["exit_code"] == 0 else "grade_failed",
        )
        return result
    except ModelError as exc:
        result.update(status="provider_failed", error=str(exc))
        return result
    except TimeoutError:
        result["status"] = "timeout"
        return result
    except Exception as exc:
        result["error"] = str(exc)[:1200]
        return result
    finally:
        result["worktrees"] = [str(p) for p in paths]
        # Keep patches, logs and worktrees private for inspection; never silently delete them.
        (output / f"{task.id}.json").write_text(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(prog="codeweaver-eval")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--out", type=Path, default=Path(".eval-results"))
    args = parser.parse_args()
    tasks = [Task(**item) for item in json.loads(args.manifest.read_text())]
    settings = load_settings(args.config)

    async def run():
        return [await evaluate(task, settings, args.out) for task in tasks]

    results = asyncio.run(run())
    print(
        json.dumps(
            {
                "tasks": len(results),
                "resolved": sum(r["resolved"] for r in results),
                "statuses": [r["status"] for r in results],
            },
            indent=2,
        )
    )
    raise SystemExit(0 if all(r["resolved"] for r in results) else 1)
