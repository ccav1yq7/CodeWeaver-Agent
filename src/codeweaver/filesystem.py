"""Descriptor-relative file operations; model paths never follow symlinks.

The application trusts the workspace owner, not model-generated path strings.
An external program changing a file after our last comparison is outside an
optimistic write's transaction boundary. Every replacement is nevertheless atomic.
"""

import contextlib
import hashlib
import os
import stat
import uuid
from pathlib import Path, PurePosixPath


class AccessError(ValueError):
    pass


def protected(parts: tuple[str, ...]) -> bool:
    return any(
        p in {".git", ".codeweaver", ".ssh", ".aws", ".gnupg", ".kube", ".netrc", ".npmrc", ".pypirc"}
        or p == ".env"
        or p.startswith(".env.")
        or p.endswith((".pem", ".key", ".p12", ".pfx"))
        for p in parts
    )


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Workspace:
    limit = 2 * 1024 * 1024

    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise AccessError("Workspace must be a directory")

    def parts(self, path: str) -> tuple[str, ...]:
        p = PurePosixPath(path)
        if (
            not path
            or any(ord(c) < 32 for c in path)
            or "\\" in path
            or p.is_absolute()
            or any(x in {"", ".", ".."} for x in path.split("/"))
        ):
            raise AccessError("Use a workspace-relative path without traversal")
        if protected(p.parts):
            raise AccessError("Credentials and control files are not available to tools")
        return p.parts

    @contextlib.contextmanager
    def parent(self, path: str, create: bool = False):
        parts = self.parts(path)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(self.root, flags)
        try:
            for component in parts[:-1]:
                if create:
                    try:
                        os.mkdir(component, mode=0o755, dir_fd=fd)
                    except FileExistsError:
                        pass
                child = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd, parts[-1]
        finally:
            os.close(fd)

    def _bytes(self, fd: int, name: str) -> bytes:
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(handle)
            if not stat.S_ISREG(info.st_mode) or info.st_size > self.limit:
                raise AccessError("Only regular files up to 2 MiB are supported")
            with os.fdopen(handle, "rb", closefd=False) as stream:
                data = stream.read(self.limit + 1)
            if len(data) > self.limit:
                raise AccessError("File grew past the size limit")
            return data
        finally:
            os.close(handle)

    def read(self, path: str) -> dict:
        with self.parent(path) as (fd, name):
            data = self._bytes(fd, name)
        return {"path": path, "sha256": digest(data), "content": data.decode("utf-8")}

    def write(self, path: str, content: str, expected: str | None) -> dict:
        data = content.encode()
        if len(data) > self.limit:
            raise AccessError("File exceeds 2 MiB")
        with self.parent(path, create=True) as (fd, name):
            try:
                old = self._bytes(fd, name)
                mode = stat.S_IMODE(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode) & 0o777
            except FileNotFoundError:
                old, mode = None, 0o644
            if (digest(old) if old is not None else None) != expected:
                raise AccessError("File changed or was not read; read again before editing")
            temporary = f".cw-{uuid.uuid4().hex}"
            handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=fd)
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=fd)
        return {"path": path, "sha256": digest(data), "bytes": len(data)}

    def files(self, pattern: str = "*") -> list[str]:
        import fnmatch

        result = []
        for parent, dirs, files in os.walk(self.root, followlinks=False):
            relative = Path(parent).relative_to(self.root)
            dirs[:] = sorted(
                d
                for d in dirs
                if not protected((d,))
                and d not in {".venv", "node_modules", "__pycache__"}
                and not (Path(parent) / d).is_symlink()
            )
            for name in sorted(files):
                path = (relative / name).as_posix()
                if (
                    not protected((name,))
                    and not (Path(parent) / name).is_symlink()
                    and fnmatch.fnmatchcase(path, pattern)
                ):
                    result.append(path)
                    if len(result) >= 5000:
                        return result
        return result
