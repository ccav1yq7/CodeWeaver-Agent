"""Capability checks, independent of prompts, command prefixes and UI implementations."""

import fnmatch
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from .configuration import Settings


@dataclass(frozen=True)
class Action:
    tool: str
    arguments: dict
    capability: Literal["read", "write", "execute", "external"]
    preview: str = ""


Approver = Callable[[Action], Awaitable[bool]]


async def refuse(_: Action) -> bool:
    return False


class Authority:
    def __init__(self, settings: Settings, approve: Approver = refuse):
        self.settings, self.approve = settings, approve

    async def require(self, action: Action):
        if any(fnmatch.fnmatchcase(action.tool, pattern) for pattern in self.settings.deny_tools):
            raise PermissionError("Explicit deny rule")
        if action.capability == "read":
            return
        if self.settings.mode == "read-only":
            raise PermissionError("Read-only mode")
        if action.capability == "write" and self.settings.mode == "workspace":
            return
        if action.tool == "run" and action.arguments.get("argv") in self.settings.allow_commands:
            return
        if not await self.approve(action):
            raise PermissionError("Action was not approved")
