import sys

import pytest

from codeweaver.authorization import Authority
from codeweaver.configuration import Connector, Settings
from codeweaver.delegation import install_delegation
from codeweaver.extensions import install_connectors, load_skills


async def test_mcp_handshake_and_call_require_separate_approvals(setup_tools, tmp_path):
    pytest.importorskip("mcp")
    server = tmp_path / "server.py"
    server.write_text(
        'from mcp.server.fastmcp import FastMCP\nmcp = FastMCP("fixture")\n@mcp.tool()\ndef add(a: int, b: int) -> int:\n    return a + b\nif __name__ == "__main__":\n    mcp.run()\n'
    )
    tools, _ = setup_tools
    approved = []

    async def approve(action):
        approved.append(action.tool)
        return True

    settings = Settings(
        provider="demo", connectors=[Connector(name="math", command=[sys.executable, str(server)])]
    )
    tools.authority = Authority(settings, approve)
    await install_connectors(tools)
    result = await tools.dispatch("mcp_math_add", {"a": 2, "b": 3})
    assert not result.get("error"), result
    assert result["content"][0]["text"] == "5"
    assert approved == ["mcp_start_math", "mcp_math_add"]


def test_skill_loading_is_explicit_and_bounded(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("Explain your verification steps.")
    assert "cannot grant permissions" in load_skills([path])
    path.write_text("x" * 20001)
    with pytest.raises(ValueError):
        load_skills([path])


async def test_delegated_workers_are_bounded_and_cannot_redelegate(setup_tools):
    tools, _ = setup_tools

    async def yes(action):
        return True

    tools.authority = Authority(Settings(provider="demo"), yes)

    class Worker:
        async def reply(self, instructions, messages, catalog):
            assert "delegate" not in {t["name"] for t in catalog}
            return {"role": "assistant", "text": "inspection", "calls": []}

    install_delegation(tools, model_factory=lambda settings: Worker())
    result = await tools.dispatch(
        "delegate",
        {"jobs": [{"task": "inspect", "mode": "inspect"}, {"task": "inspect other", "mode": "inspect"}]},
    )
    assert len(result["jobs"]) == 2 and all(j["status"] == "completed" for j in result["jobs"])
    result = await tools.dispatch("delegate", {"jobs": [{"task": "a"}] * 4})
    assert "error" in result
