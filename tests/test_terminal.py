from argparse import Namespace

import pytest

pytest.importorskip("textual")
from textual.widgets import Input

from codeweaver.configuration import Settings
from codeweaver.terminal import create_terminal


async def test_textual_demo_uses_shared_runtime_and_preserves_session(tmp_path):
    args = Namespace(root=tmp_path, resume=None, skill=[], mcp=False)
    app = create_terminal(args, Settings(provider="demo"))
    async with app.run_test() as pilot:
        app.query_one(Input).value = "Inspect files"
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if app.agent_task and app.agent_task.done():
                break
        assert app.current
        assert app.agent_task.done()
        assert (tmp_path / ".codeweaver/sessions.sqlite3").exists()
