"""Bounded independent workers; edits stay in detached worktrees for human integration."""

import asyncio
from typing import Literal

from pydantic import Field

from .authorization import Authority, refuse
from .capabilities import Arguments, Toolbox
from .engine import Agent
from .filesystem import Workspace
from .models import make_model
from .records import Journal
from .repositories import diff, install_git_tools, snapshot


class Job(Arguments):
    task: str = Field(min_length=1, max_length=6000)
    mode: Literal["inspect", "edit"] = "inspect"


class Batch(Arguments):
    jobs: list[Job] = Field(min_length=1, max_length=3)


def install_delegation(tools: Toolbox, model_factory=make_model):
    async def delegate(args):
        jobs = Batch(**args).jobs

        async def worker(job):
            path = tools.workspace.root
            journal = model = None
            try:
                if job.mode == "edit":
                    path = await snapshot(path)
                settings = tools.authority.settings.model_copy(
                    update={
                        "mode": "workspace" if job.mode == "edit" else "read-only",
                        "max_rounds": 8,
                        "max_tools": 20,
                    }
                )
                journal = Journal(path)
                child_tools = Toolbox(Workspace(path), Authority(settings, refuse), journal)
                install_git_tools(child_tools)
                model = model_factory(settings)
                agent = Agent(model, child_tools, settings, journal)
                result = await agent.run(job.task)
                if job.mode == "edit":
                    result.update(
                        worktree=str(path),
                        patch=await diff(path),
                        integration="Review the preserved worktree; no automatic merge",
                    )
                return result
            except Exception as exc:
                return {"status": "failed", "error": str(exc)[:500], "worktree": str(path)}
            finally:
                if journal is not None:
                    journal.close()
                if model is not None and hasattr(model, "close"):
                    await model.close()

        return {"jobs": await asyncio.gather(*(worker(j) for j in jobs))}

    tools.add(
        "delegate",
        "Run up to three bounded workers. Edit jobs start at HEAD in separate worktrees; uncommitted parent edits are not copied. No nested delegation or automatic merge.",
        Batch,
        "external",
        delegate,
    )
