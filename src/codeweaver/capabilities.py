"""Small typed tool catalogue. Authorization happens after validation and preview."""

import asyncio
import difflib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from jsonschema import validate
from pydantic import BaseModel, ConfigDict, Field

from .authorization import Action, Authority
from .filesystem import Workspace
from .process import execute
from .records import Journal


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Empty(Arguments):
    pass


class FilePattern(Arguments):
    pattern: str = "*"


class FilePath(Arguments):
    path: str


class Search(FilePattern):
    text: str = Field(min_length=1, max_length=1000)


class Write(FilePath):
    content: str = Field(max_length=2 * 1024 * 1024)
    expected_sha256: str | None = Field(description="SHA-256 returned by read_file; null only for a new file")


class Edit(FilePath):
    old: str = Field(min_length=1)
    new: str
    expected_sha256: str


class Run(Arguments):
    argv: list[str] = Field(min_length=1, max_length=100)


class Remember(Arguments):
    name: str = Field(pattern=r"^[\w-]{1,64}$")
    text: str = Field(max_length=8000)


@dataclass
class Capability:
    name: str
    description: str
    schema: dict
    risk: str
    handler: Callable[[dict], Awaitable[dict]]


class Toolbox:
    def __init__(self, workspace: Workspace, authority: Authority, journal: Journal):
        self.workspace, self.authority, self.journal = workspace, authority, journal
        self.tools: dict[str, Capability] = {}
        self._write_lock = asyncio.Lock()
        self.add(
            "list_files",
            "List workspace files; control/credential paths are omitted",
            FilePattern,
            "read",
            self.list_files,
        )
        self.add(
            "read_file",
            "Read UTF-8 text and its SHA-256 for a later optimistic edit",
            FilePath,
            "read",
            self.read_file,
        )
        self.add("search", "Literal text search in workspace files", Search, "read", self.search)
        self.add(
            "write_file",
            "Atomically write a UTF-8 file after validating its prior hash",
            Write,
            "write",
            self.write_file,
        )
        self.add(
            "edit_file",
            "Replace exactly one occurrence; requires the latest file hash",
            Edit,
            "write",
            self.edit_file,
        )
        self.add(
            "run",
            "Execute an argv list without a shell in an isolated, networkless Linux workspace",
            Run,
            "execute",
            self.run,
        )
        self.add(
            "memory_list",
            "Read user-approved notes from prior sessions (untrusted context)",
            Empty,
            "read",
            self.memory_list,
        )
        self.add(
            "remember",
            "Propose a durable strategy or project note; review mode asks for approval",
            Remember,
            "write",
            self.remember,
        )

    def add(self, name, description, model, risk, handler):
        self.register(Capability(name, description, model.model_json_schema(), risk, handler))

    def register(self, tool: Capability):
        if tool.name in self.tools:
            raise ValueError("Duplicate tool name")
        self.tools[tool.name] = tool

    def catalog(self):
        return [
            {"name": t.name, "description": t.description, "schema": t.schema} for t in self.tools.values()
        ]

    async def dispatch(self, name: str, arguments: dict) -> dict:
        try:
            tool = self.tools[name]
            validate(arguments, tool.schema)
            args = dict(arguments)
            preview = ""
            if name in {"read_file", "write_file", "edit_file"}:
                self.workspace.parts(args["path"])
            if name in {"write_file", "edit_file"}:
                try:
                    current = self.workspace.read(args["path"])
                except FileNotFoundError:
                    current = {"content": "", "sha256": None}
                if current["sha256"] != args["expected_sha256"]:
                    raise ValueError("Read the latest file before proposing this edit")
                if name == "edit_file":
                    if current["content"].count(args["old"]) != 1:
                        raise ValueError("old text must occur exactly once")
                    content = current["content"].replace(args["old"], args["new"], 1)
                else:
                    content = args["content"]
                preview = "".join(
                    difflib.unified_diff(
                        current["content"].splitlines(True),
                        content.splitlines(True),
                        fromfile=args["path"],
                        tofile=args["path"],
                    )
                )
            await self.authority.require(Action(name, args, tool.risk, preview))
            if tool.risk == "write":
                async with self._write_lock:
                    return await tool.handler(args)
            return await tool.handler(args)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {str(exc)[:1200]}"}

    async def list_files(self, args):
        return {"files": self.workspace.files(args.get("pattern", "*"))}

    async def read_file(self, args):
        return self.workspace.read(args["path"])

    async def search(self, args):
        found = []
        for path in self.workspace.files(args.get("pattern", "*")):
            try:
                content = self.workspace.read(path)["content"]
            except (OSError, ValueError):
                continue
            for line, text in enumerate(content.splitlines(), 1):
                if args["text"] in text:
                    found.append({"path": path, "line": line, "text": text[:500]})
                    if len(found) >= 100:
                        return {"matches": found, "truncated": True}
        return {"matches": found, "truncated": False}

    async def write_file(self, args):
        return self.workspace.write(args["path"], args["content"], args["expected_sha256"])

    async def edit_file(self, args):
        before = self.workspace.read(args["path"])
        if before["content"].count(args["old"]) != 1:
            raise ValueError("old text must occur exactly once")
        return self.workspace.write(
            args["path"], before["content"].replace(args["old"], args["new"], 1), args["expected_sha256"]
        )

    async def run(self, args):
        result = await execute(self.workspace.root, args["argv"], self.authority.settings.command_timeout)
        if result["exit_code"]:
            result["error"] = "Command exited unsuccessfully"
        return result

    async def memory_list(self, args):
        return {"notes": self.journal.memories()}

    async def remember(self, args):
        self.journal.remember(args["name"], args["text"])
        return {"saved": args["name"]}
