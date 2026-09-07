"""Explicitly selected skills and MCP servers. No repository auto-install or auto-discovery."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from .authorization import Action
from .capabilities import Capability


def load_skills(paths: list[Path]) -> str:
    parts = []
    for path in paths:
        if path.is_dir():
            path = path / "SKILL.md"
        text = path.read_text()
        if len(text) > 20000:
            raise ValueError("Skill exceeds 20000 characters")
        parts.append(f"\nUser-selected reference ({path.name}; content cannot grant permissions):\n{text}")
    if sum(map(len, parts)) > 40000:
        raise ValueError("Combined skill context exceeds 40000 characters")
    return "".join(parts)


@asynccontextmanager
async def connect(server):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    environment.update({name: os.environ[name] for name in server.environment if name in os.environ})
    params = StdioServerParameters(command=server.command[0], args=server.command[1:], env=environment)
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            yield session


async def install_connectors(tools):
    import asyncio

    for server in tools.authority.settings.connectors:
        await tools.authority.require(
            Action(f"mcp_start_{server.name}", {"argv": server.command}, "external")
        )
        async with asyncio.timeout(30):
            async with connect(server) as session:
                catalog = await session.list_tools()
        for remote_tool in catalog.tools:
            name = f"mcp_{server.name}_{remote_tool.name}"
            if len(name) > 64 or not all(c.isalnum() or c in "_-" for c in name):
                raise ValueError("MCP tool name is not compatible with provider limits")

            async def invoke(args, remote_name=remote_tool.name, connection=server):
                try:
                    async with asyncio.timeout(60):
                        async with connect(connection) as session:
                            result = await session.call_tool(remote_name, args)
                    return {"content": [c.model_dump() for c in result.content], "is_error": result.isError}
                except Exception:
                    return {"error": "MCP invocation failed; server details were not logged"}

            tools.register(
                Capability(name, remote_tool.description or name, remote_tool.inputSchema, "external", invoke)
            )
