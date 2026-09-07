"""Bounded subprocesses and mandatory OS isolation for model-directed commands."""

import asyncio
import contextlib
import os
import platform
import shutil
import signal
from pathlib import Path

from .filesystem import protected


class IsolationError(RuntimeError):
    pass


def sandbox_command(root: Path, argv: list[str]) -> list[str]:
    if not argv or not all(isinstance(x, str) and x and "\x00" not in x for x in argv):
        raise ValueError("argv must contain nonempty strings")
    if platform.system() != "Linux" or not shutil.which("bwrap"):
        raise IsolationError("Command execution requires Linux bubblewrap; no unsandboxed fallback")
    command = [shutil.which("bwrap"), "--die-with-parent", "--new-session", "--unshare-all"]
    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
        if Path(path).exists():
            command += ["--ro-bind", path, path]
    command += ["--dir", "/etc"]
    for path in ("/etc/ld.so.cache", "/etc/alternatives", "/etc/localtime"):
        if Path(path).exists():
            command += ["--ro-bind", path, path]
    command += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--bind", str(root), "/workspace"]
    # Hide credentials/control state, including nested copies, from sandboxed programs.
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs) + files:
            path = Path(directory) / name
            if protected((name,)) and not path.is_symlink():
                target = "/workspace/" + path.relative_to(root).as_posix()
                command += ["--tmpfs", target] if path.is_dir() else ["--ro-bind", "/dev/null", target]
        dirs[:] = [d for d in dirs if not protected((d,)) and not (Path(directory) / d).is_symlink()]
    command += [
        "--clearenv",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "HOME",
        "/tmp",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--chdir",
        "/workspace",
        "--",
        *argv,
    ]
    return command


async def capture(argv: list[str], cwd: Path, timeout: int, *, environment: dict | None = None) -> dict:
    """Drain output while retaining at most 64 KiB; kill the process group on cancellation."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    output = bytearray()
    truncated = False

    async def consume():
        nonlocal truncated
        while block := await proc.stdout.read(8192):
            available = max(0, 65536 - len(output))
            output.extend(block[:available])
            truncated |= len(block) > available
        await proc.wait()

    try:
        await asyncio.wait_for(consume(), timeout)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        await proc.wait()
        raise
    return {"exit_code": proc.returncode, "output": output.decode(errors="replace"), "truncated": truncated}


async def execute(root: Path, argv: list[str], timeout: int) -> dict:
    command = sandbox_command(root, argv)
    result = await capture(command, root, timeout, environment={"PATH": "/usr/bin:/bin"})
    if result["exit_code"] and result["output"].startswith("bwrap:"):
        raise IsolationError("bubblewrap could not establish isolation; command was not retried")
    return result
