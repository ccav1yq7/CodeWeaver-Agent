"""Provider adapters translate a small, serializable conversation protocol."""

import json
import os
from typing import Protocol

from .configuration import Settings


class ModelError(RuntimeError):
    pass


class Model(Protocol):
    async def reply(self, instructions: str, messages: list[dict], tools: list[dict]) -> dict: ...


class DemoModel:
    """Deterministic smoke provider. It does not pretend to solve coding tasks."""

    async def reply(self, instructions, messages, tools):
        if messages[-1]["role"] == "user":
            return {
                "role": "assistant",
                "text": "Inspecting the workspace (offline demo).",
                "calls": [
                    {"id": f"demo-{len(messages)}", "name": "list_files", "arguments": {"pattern": "*"}}
                ],
            }
        return {
            "role": "assistant",
            "text": "Offline demo completed. Configure a model provider to perform coding tasks.",
            "calls": [],
        }


class APIModel:
    def __init__(self, settings: Settings):
        self.settings = settings
        key = os.getenv(settings.key_env)
        if not key:
            raise ModelError(f"Set {settings.key_env}; credentials are read only from the environment")
        if settings.provider == "openai":
            from openai import AsyncOpenAI

            self.client = AsyncOpenAI(
                api_key=key, base_url=settings.base_url, timeout=settings.request_timeout, max_retries=2
            )
        else:
            from anthropic import AsyncAnthropic

            self.client = AsyncAnthropic(
                api_key=key, base_url=settings.base_url, timeout=settings.request_timeout, max_retries=2
            )

    async def reply(self, instructions, messages, tools):
        try:
            return await (
                self._openai(instructions, messages, tools)
                if self.settings.provider == "openai"
                else self._anthropic(instructions, messages, tools)
            )
        except Exception as exc:
            # SDK errors may contain request bodies, endpoints or credential-bearing headers.
            status = getattr(exc, "status_code", None)
            raise ModelError(
                f"Provider request failed ({type(exc).__name__}, status={status}); no tool was retried"
            ) from None

    async def _openai(self, instructions, messages, tools):
        inputs = []
        for message in messages:
            if message["role"] == "tool":
                inputs.append(
                    {"type": "function_call_output", "call_id": message["call_id"], "output": message["text"]}
                )
            elif message.get("native"):
                inputs.extend(message["native"])
            else:
                inputs.append({"role": message["role"], "content": message.get("text", "")})
                for call in message.get("calls", []):
                    inputs.append(
                        {
                            "type": "function_call",
                            "call_id": call["id"],
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"]),
                        }
                    )
        response = await self.client.responses.create(
            model=self.settings.model,
            instructions=instructions,
            input=inputs,
            tools=[
                {
                    "type": "function",
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["schema"],
                    "strict": False,
                }
                for t in tools
            ],
            store=False,
            include=["reasoning.encrypted_content"],
            max_output_tokens=self.settings.max_output_tokens,
        )
        if response.status != "completed":
            raise ModelError("Provider did not complete its turn")
        native = [item.model_dump(exclude_none=True) for item in response.output]
        calls = [
            {"id": item.call_id, "name": item.name, "arguments": json.loads(item.arguments)}
            for item in response.output
            if item.type == "function_call"
        ]
        return {
            "role": "assistant",
            "text": response.output_text,
            "calls": calls,
            "native": native,
            "usage": response.usage.model_dump() if response.usage else {},
        }

    async def _anthropic(self, instructions, messages, tools):
        inputs = []
        for message in messages:
            if message["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": message["call_id"], "content": message["text"]}
                if inputs and inputs[-1]["role"] == "user" and isinstance(inputs[-1]["content"], list):
                    inputs[-1]["content"].append(block)
                else:
                    inputs.append({"role": "user", "content": [block]})
            elif message.get("native"):
                inputs.append({"role": "assistant", "content": message["native"]})
            else:
                blocks = [{"type": "text", "text": message["text"]}] if message.get("text") else []
                blocks += [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]}
                    for c in message.get("calls", [])
                ]
                inputs.append({"role": message["role"], "content": blocks})
        response = await self.client.messages.create(
            model=self.settings.model,
            system=instructions,
            messages=inputs,
            tools=[
                {"name": t["name"], "description": t["description"], "input_schema": t["schema"]}
                for t in tools
            ],
            max_tokens=self.settings.max_output_tokens,
        )
        if response.stop_reason not in {"end_turn", "tool_use"}:
            raise ModelError("Provider did not complete its turn")
        return {
            "role": "assistant",
            "text": "\n".join(b.text for b in response.content if b.type == "text"),
            "calls": [
                {"id": b.id, "name": b.name, "arguments": b.input}
                for b in response.content
                if b.type == "tool_use"
            ],
            "native": [b.model_dump(exclude_none=True) for b in response.content],
            "usage": response.usage.model_dump(),
        }

    async def close(self):
        await self.client.close()


def make_model(settings: Settings) -> Model:
    return DemoModel() if settings.provider == "demo" else APIModel(settings)
