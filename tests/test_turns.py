import json

import pytest

from codeweaver.authorization import Authority
from codeweaver.configuration import Settings
from codeweaver.engine import Agent, compact
from codeweaver.filesystem import digest
from codeweaver.models import DemoModel


class Script:
    def __init__(self, turns):
        self.turns = iter(turns)
        self.windows = []

    async def reply(self, instructions, messages, tools):
        self.windows.append(list(messages))
        return next(self.turns)


def call(key, name, args):
    return {"role": "assistant", "text": "", "calls": [{"id": key, "name": name, "arguments": args}]}


async def test_agent_reads_edits_and_reports_through_real_dispatch(setup_tools, tmp_path):
    tools, journal = setup_tools
    (tmp_path / "sum.py").write_text("answer = 1\n")
    model = Script(
        [
            call("read", "read_file", {"path": "sum.py"}),
            call(
                "edit",
                "edit_file",
                {"path": "sum.py", "old": "1", "new": "2", "expected_sha256": digest(b"answer = 1\n")},
            ),
            {"role": "assistant", "text": "Updated", "calls": []},
        ]
    )
    agent = Agent(model, tools, tools.authority.settings, journal)
    result = await agent.run("Fix answer")
    assert result["status"] == "completed"
    assert (tmp_path / "sum.py").read_text() == "answer = 2\n"
    assert model.windows[1][-1]["call_id"] == "read"
    assert json.loads(model.windows[2][-1]["text"])["sha256"] == digest(b"answer = 2\n")


async def test_denied_file_change_reaches_model_as_error(setup_tools, tmp_path):
    tools, journal = setup_tools
    tools.authority = Authority(Settings(provider="demo"))
    model = Script(
        [
            call("w", "write_file", {"path": "new", "content": "x", "expected_sha256": None}),
            {"role": "assistant", "text": "Denied", "calls": []},
        ]
    )
    await Agent(model, tools, tools.authority.settings, journal).run("Try")
    assert not (tmp_path / "new").exists()
    assert "not approved" in model.windows[1][-1]["text"]


async def test_tool_arguments_validated_before_approval(setup_tools):
    tools, _ = setup_tools
    for name, args in [
        ("run", {"argv": "echo hi"}),
        ("read_file", {"path": "a", "extra": True}),
        ("write_file", {"path": "a", "content": "x"}),
    ]:
        assert "error" in await tools.dispatch(name, args)


async def test_plan_basename_has_no_permission_exception(setup_tools):
    tools, _ = setup_tools
    assert "error" in await tools.dispatch(
        "write_file", {"path": "/var/tmp/plan.md", "content": "x", "expected_sha256": None}
    )


async def test_duplicate_call_receipt_does_not_repeat_write(setup_tools, tmp_path):
    tools, journal = setup_tools
    arguments = {"path": "one", "content": "one", "expected_sha256": None}
    model = Script(
        [
            call("same", "write_file", arguments),
            call("same", "write_file", {**arguments, "content": "two"}),
            {"role": "assistant", "text": "done", "calls": []},
        ]
    )
    await Agent(model, tools, tools.authority.settings, journal).run("Write")
    assert (tmp_path / "one").read_text() == "one"


async def test_interrupted_call_is_not_replayed_on_resume(setup_tools, tmp_path):
    tools, journal = setup_tools
    agent = Agent(DemoModel(), tools, tools.authority.settings, journal)
    agent.messages = [
        {"role": "user", "text": "write"},
        call("pending", "write_file", {"path": "new", "content": "x", "expected_sha256": None}),
    ]
    journal.save(agent.session, agent.messages)
    journal.begin(agent.session, "pending", "write_file")
    restored = Agent(DemoModel(), tools, tools.authority.settings, journal, session=agent.session)
    restored.repair_interrupted_turn()
    assert restored.messages[-1]["role"] == "tool"
    assert "interrupted" in restored.messages[-1]["text"]
    assert not (tmp_path / "new").exists()


async def test_budget_terminates_without_claiming_completion(setup_tools):
    tools, journal = setup_tools
    settings = Settings(provider="demo", max_rounds=1)
    result = await Agent(DemoModel(), tools, settings, journal).run("inspect")
    assert result["status"] == "budget_exhausted"


def test_compaction_keeps_call_result_pairs_or_fails_closed():
    old = [
        {"role": "user", "text": "a" * 15000},
        call("c", "list_files", {}),
        {"role": "tool", "call_id": "c", "text": "[]"},
        {"role": "assistant", "text": "done"},
    ]
    current = [
        {"role": "user", "text": "new"},
        call("d", "list_files", {}),
        {"role": "tool", "call_id": "d", "text": "[]"},
    ]
    window, shortened = compact(old + current, 8000)
    assert shortened and window[-3:] == current
    assert all(m.get("call_id") != "c" for m in window)
    with pytest.raises(ValueError):
        compact(old, 8000)


def test_compaction_reduces_complete_tool_groups_within_one_long_task():
    messages = [{"role": "user", "text": "Keep fixing the same task"}]
    for i in range(5):
        messages += [
            call(str(i), "read_file", {"path": "file"}),
            {"role": "tool", "call_id": str(i), "text": "x" * 4000},
        ]
    reduced, shortened = compact(messages, 8000)
    assert shortened and len(json.dumps(reduced)) <= 8000
    assert any(m.get("text") == "Keep fixing the same task" for m in reduced)
    calls = {c["id"] for m in reduced for c in m.get("calls", [])}
    results = {m["call_id"] for m in reduced if m["role"] == "tool"}
    assert calls == results and "4" in calls
