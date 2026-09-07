"""Optional Textual front end. Permission decisions stay in the shared runtime."""

import asyncio
import json

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, RichLog

from .runtime import session


def create_terminal(args, settings):
    class Terminal(App):
        BINDINGS = [("ctrl+q", "quit", "Quit"), ("ctrl+x", "cancel", "Cancel task")]
        CSS = "RichLog { height: 1fr; } Input { dock: bottom; }"

        def __init__(self):
            super().__init__()
            self.current = args.resume
            self.pending = None
            self.agent_task = None

        def compose(self) -> ComposeResult:
            yield Header()
            yield RichLog(wrap=True, markup=False)
            yield Input(placeholder="Task, or y/n for a pending approval")
            yield Footer()

        def on_mount(self):
            self.query_one(Input).focus()

        async def approval(self, action):
            self.query_one(RichLog).write(
                f"Approval: {action.tool}\n{action.preview or json.dumps(action.arguments)}\nEnter y or n."
            )
            self.pending = asyncio.get_running_loop().create_future()
            try:
                return await self.pending
            finally:
                self.pending = None

        async def emit(self, event):
            if event["type"] == "assistant":
                self.query_one(RichLog).write(event.get("text", ""))
            elif event["type"] == "tool_end":
                self.query_one(RichLog).write(f"[{event['name']}] {str(event['result'])[:2000]}")

        async def work(self, prompt):
            try:
                async with session(
                    args.root,
                    settings,
                    resume=self.current,
                    approve=self.approval,
                    emit=self.emit,
                    skills=args.skill,
                    mcp=args.mcp,
                ) as agent:
                    self.current = agent.session
                    result = await agent.run(prompt)
                    self.query_one(RichLog).write(result["status"])
            except asyncio.CancelledError:
                self.query_one(RichLog).write("Cancelled; completed file changes remain in the workspace.")
            except Exception as exc:
                self.query_one(RichLog).write(str(exc))

        async def on_input_submitted(self, event: Input.Submitted):
            text = event.value.strip()
            event.input.value = ""
            if self.pending and not self.pending.done():
                self.pending.set_result(text.lower() == "y")
            elif self.agent_task and not self.agent_task.done():
                self.query_one(RichLog).write("A task is running. Ctrl+X cancels it.")
            elif text:
                self.query_one(RichLog).write("you> " + text)
                self.agent_task = asyncio.create_task(self.work(text))

        def action_cancel(self):
            if self.agent_task:
                self.agent_task.cancel()

        async def on_unmount(self):
            if self.agent_task and not self.agent_task.done():
                self.agent_task.cancel()
                await self.agent_task

    return Terminal()


def launch(args, settings):
    create_terminal(args, settings).run()
