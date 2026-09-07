from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from codeweaver.configuration import Settings
from codeweaver.models import APIModel, ModelError


async def test_responses_adapter_preserves_native_reasoning_and_pairs_outputs():
    model = APIModel.__new__(APIModel)
    model.settings = Settings()
    model.client = SimpleNamespace(
        responses=SimpleNamespace(
            create=AsyncMock(
                return_value=SimpleNamespace(status="completed", output=[], output_text="done", usage=None)
            )
        )
    )
    native = [
        {"type": "reasoning", "id": "r", "encrypted_content": "test-only", "summary": []},
        {"type": "function_call", "call_id": "c", "name": "read_file", "arguments": '{"path":"a"}'},
    ]
    result = await model.reply(
        "system",
        [
            {"role": "user", "text": "read"},
            {"role": "assistant", "native": native},
            {"role": "tool", "call_id": "c", "text": "result"},
        ],
        [],
    )
    request = model.client.responses.create.call_args.kwargs
    assert request["store"] is False
    assert request["input"][1:3] == native
    assert request["input"][-1] == {"type": "function_call_output", "call_id": "c", "output": "result"}
    assert result["text"] == "done"


async def test_anthropic_groups_parallel_tool_results_in_one_user_message():
    model = APIModel.__new__(APIModel)
    model.settings = Settings(provider="anthropic")
    model.client = SimpleNamespace(
        messages=SimpleNamespace(
            create=AsyncMock(
                return_value=SimpleNamespace(
                    stop_reason="end_turn", content=[], usage=SimpleNamespace(model_dump=lambda: {})
                )
            )
        )
    )
    await model.reply(
        "system",
        [
            {"role": "user", "text": "q"},
            {
                "role": "assistant",
                "native": [
                    {"type": "tool_use", "id": "a", "name": "x", "input": {}},
                    {"type": "tool_use", "id": "b", "name": "x", "input": {}},
                ],
            },
            {"role": "tool", "call_id": "a", "text": "one"},
            {"role": "tool", "call_id": "b", "text": "two"},
        ],
        [],
    )
    request = model.client.messages.create.call_args.kwargs
    assert len(request["messages"][-1]["content"]) == 2
    assert request["messages"][-1]["content"][1]["tool_use_id"] == "b"


async def test_provider_failure_does_not_expose_response_details():
    model = APIModel.__new__(APIModel)
    model.settings = Settings()
    model.client = SimpleNamespace(
        responses=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("private-body-do-not-echo")))
    )
    with pytest.raises(ModelError) as error:
        await model.reply("", [], [])
    assert "private-body" not in str(error.value)
