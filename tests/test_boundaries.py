import asyncio
import os
from unittest.mock import patch

import pytest

from codeweaver.authorization import Action, Authority
from codeweaver.configuration import Settings, load_settings
from codeweaver.filesystem import AccessError, Workspace
from codeweaver.process import IsolationError, capture, execute, sandbox_command


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/tmp/plan.md",
        "a/../b",
        "./a",
        "a//b",
        "a\\b",
        ".env",
        "nested/.env.local",
        ".git/config",
        ".codeweaver/plans/a.md",
        "secret.pem",
        "x/.ssh/id_rsa",
    ],
)
def test_tool_paths_cannot_escape_or_access_control_files(tmp_path, path):
    with pytest.raises(AccessError):
        Workspace(tmp_path).write(path, "x", None)


def test_stale_write_preserves_other_edit_and_new_file_requires_absence(tmp_path):
    scope = Workspace(tmp_path)
    scope.write("file", "one", None)
    stamp = scope.read("file")["sha256"]
    (tmp_path / "file").write_text("two")
    with pytest.raises(AccessError):
        scope.write("file", "three", stamp)
    with pytest.raises(AccessError):
        scope.write("file", "three", None)
    assert (tmp_path / "file").read_text() == "two"


def test_symlink_components_and_fifo_are_never_opened_as_text(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    scope = Workspace(tmp_path)
    with pytest.raises(OSError):
        scope.write("link/new", "bad", None)
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(AccessError):
        scope.read("pipe")
    assert not (outside / "new").exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["sed", "-i", "s/a/b/", "file"],
        ["find", ".", "-delete"],
        ["npx", "package"],
        ["sh", "-c", "echo ok\ntouch file"],
    ],
)
async def test_explicit_deny_wins_over_approval_and_allow_commands(argv):
    called = []

    async def approve(action):
        called.append(action)
        return True

    policy = Authority(Settings(deny_tools=["run"], allow_commands=[argv]), approve)
    with pytest.raises(PermissionError):
        await policy.require(Action("run", {"argv": argv}, "execute"))
    assert not called


async def test_read_only_never_accepts_write_approval():
    async def yes(action):
        return True

    with pytest.raises(PermissionError):
        await Authority(Settings(mode="read-only"), yes).require(Action("write_file", {}, "write"))


async def test_absent_sandbox_cannot_execute_on_host(tmp_path):
    marker = tmp_path / "marker"
    with patch("codeweaver.process.shutil.which", return_value=None):
        with pytest.raises(IsolationError):
            await execute(tmp_path, ["touch", str(marker)], 2)
    assert not marker.exists()


def test_sandbox_has_no_provider_environment_and_hides_nested_credentials(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub/.env").write_text("PLACEHOLDER")
    with patch("codeweaver.process.shutil.which", return_value="/usr/bin/bwrap"):
        command = sandbox_command(tmp_path, ["/usr/bin/python3", "-V"])
    assert "--clearenv" in command and "--unshare-all" in command
    assert "/workspace/sub/.env" in command
    assert "/home" not in command


async def test_capture_drains_large_output_but_bounds_retained_bytes(tmp_path):
    result = await capture(["/usr/bin/python3", "-c", "print('x'*200000)"], tmp_path, 5)
    assert result["exit_code"] == 0 and result["truncated"]
    assert len(result["output"]) == 65536


async def test_timeout_kills_descendants_before_they_can_write(tmp_path):
    marker = tmp_path / "later"
    program = "import os,time; pid=os.fork(); time.sleep(1.0); open('later','w').write('bad')"
    with pytest.raises(TimeoutError):
        await capture(["/usr/bin/python3", "-c", program], tmp_path, 0.15)
    await asyncio.sleep(1.1)
    assert not marker.exists()


def test_no_configuration_file_required_or_repository_autoloaded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".codeweaver").mkdir()
    (tmp_path / ".codeweaver/config.toml").write_text('mode="workspace"')
    assert load_settings().mode == "review"


@pytest.mark.parametrize(
    "url",
    ["http://untrusted.example/v1", "https://user:secret@example.com", "https://example.com?key=secret"],
)
def test_unsafe_provider_urls_rejected(url):
    with pytest.raises(ValueError):
        Settings(base_url=url)


async def test_startup_failure_reports_the_kernel_reason_without_retry(tmp_path):
    from unittest.mock import AsyncMock

    failure = {
        "exit_code": 1,
        "output": "bwrap: Creating new namespace failed: Operation not permitted\n",
        "truncated": False,
    }
    with (
        patch("codeweaver.process.sandbox_command", return_value=["bwrap"]),
        patch("codeweaver.process.capture", new_callable=AsyncMock, return_value=failure) as runner,
    ):
        with pytest.raises(IsolationError, match="Operation not permitted"):
            await execute(tmp_path, ["true"], 2)
        runner.assert_awaited_once()
