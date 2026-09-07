"""Assemble one session consistently for console, TUI, desktop and browser clients."""

from contextlib import asynccontextmanager
from pathlib import Path

from .authorization import Authority, refuse
from .capabilities import Toolbox
from .delegation import install_delegation
from .engine import Agent, silent
from .extensions import install_connectors, load_skills
from .filesystem import Workspace
from .models import make_model
from .records import Journal
from .repositories import install_git_tools


@asynccontextmanager
async def session(
    root: Path, settings, *, resume=None, approve=refuse, emit=silent, skills=(), mcp=False, model=None
):
    workspace = Workspace(root)
    journal = Journal(workspace.root)
    provider = None
    try:
        provider = model or make_model(settings)
        tools = Toolbox(workspace, Authority(settings, approve), journal)
        install_git_tools(tools)
        install_delegation(tools)
        if mcp:
            await install_connectors(tools)
        yield Agent(
            provider, tools, settings, journal, session=resume, emit=emit, skills=load_skills(list(skills))
        )
    finally:
        journal.close()
        if provider is not None and hasattr(provider, "close"):
            await provider.close()
