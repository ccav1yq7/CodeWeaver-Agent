"""User entrypoints. Noninteractive operation never treats missing input as approval."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .configuration import load_settings
from .runtime import session


def parser():
    p = argparse.ArgumentParser(prog="codeweaver")
    p.add_argument("-p", "--prompt")
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--config", type=Path, help="Explicit, user-trusted TOML configuration")
    p.add_argument("--provider", choices=["openai", "anthropic", "demo"])
    p.add_argument("--model")
    p.add_argument("--mode", choices=["review", "workspace", "read-only"])
    p.add_argument("--resume", help="Local session ID (provider/model must match)")
    p.add_argument("--json", action="store_true", help="Emit newline-delimited event JSON")
    p.add_argument("--skill", type=Path, action="append", default=[])
    p.add_argument("--mcp", action="store_true", help="Enable explicitly configured MCP servers")
    ui = p.add_mutually_exclusive_group()
    ui.add_argument("--tui", action="store_true")
    ui.add_argument("--desktop", action="store_true")
    ui.add_argument("--remote", action="store_true")
    p.add_argument("--port", type=int, default=18888)
    return p


async def console(args, settings):
    approval_lock = asyncio.Lock()

    async def approve(action):
        if args.prompt is not None or not sys.stdin.isatty():
            return False
        async with approval_lock:
            print(
                f"\nApproval: {action.tool}\n{action.preview or json.dumps(action.arguments, ensure_ascii=False)}",
                file=sys.stderr,
            )
            return (await asyncio.to_thread(input, "Allow this action? [y/N] ")).strip().lower() == "y"

    async def emit(event):
        if args.json:
            print(json.dumps(event, ensure_ascii=False), flush=True)
        elif event["type"] == "assistant" and event.get("text"):
            print(event["text"], flush=True)
        elif event["type"] == "tool_end":
            result = event["result"]
            print(f"[{event['name']}] {'error' if result.get('error') else 'done'}", file=sys.stderr)

    async with session(
        args.root, settings, resume=args.resume, approve=approve, emit=emit, skills=args.skill, mcp=args.mcp
    ) as agent:
        if args.prompt is not None:
            result = await agent.run(args.prompt)
            if args.json:
                print(json.dumps({"type": "result", **result}), flush=True)
            else:
                print(f"Session: {agent.session} ({result['status']})", file=sys.stderr)
            return 0 if result["status"] == "completed" else 2
        print(
            f"CodeWeaver | {settings.provider}/{settings.model} | {settings.mode}\nSession: {agent.session}\n/quit /sessions /memory /remember NAME TEXT"
        )
        while True:
            try:
                prompt = await asyncio.to_thread(input, "\nyou> ")
            except EOFError:
                break
            if prompt.strip() == "/quit":
                break
            if prompt.strip() == "/sessions":
                print(json.dumps(agent.journal.sessions(), indent=2))
            elif prompt.strip() == "/memory":
                print(json.dumps(agent.journal.memories(), indent=2, ensure_ascii=False))
            elif prompt.startswith("/remember "):
                _, name, text = prompt.split(" ", 2)
                agent.journal.remember(name, text)
                print("Saved user-authored memory.")
            elif prompt.strip():
                try:
                    await agent.run(prompt)
                except Exception as exc:
                    print(f"Error: {exc}", file=sys.stderr)
    return 0


def main():
    args = parser().parse_args()
    try:
        settings = load_settings(args.config, provider=args.provider, model=args.model, mode=args.mode)
        if args.tui:
            from .terminal import launch

            launch(args, settings)
            return
        if args.desktop:
            from .desktop import launch

            launch(args, settings)
            return
        if args.remote:
            from .browser import launch

            launch(args, settings)
            return
        raise SystemExit(asyncio.run(console(args, settings)))
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
