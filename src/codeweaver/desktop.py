"""Optional native Tk client; all model and journal work stays on one worker thread."""

import asyncio
import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

from .runtime import session


def launch(args, settings):
    window = tk.Tk()
    window.title("CodeWeaver")
    window.geometry("900x680")
    output = scrolledtext.ScrolledText(window, wrap="word", state="disabled")
    output.pack(fill="both", expand=True)
    entry = tk.Entry(window)
    entry.pack(fill="x")
    events = queue.Queue()
    state = {"busy": False, "session": args.resume, "loop": None, "task": None}

    async def approve(action):
        future = asyncio.get_running_loop().create_future()
        events.put(("approval", action, future, asyncio.get_running_loop()))
        return await future

    async def emit(event):
        events.put(("text", event.get("text") or json.dumps(event, ensure_ascii=False)))

    async def work(prompt):
        state["loop"] = asyncio.get_running_loop()
        state["task"] = asyncio.current_task()
        try:
            async with session(
                args.root,
                settings,
                resume=state["session"],
                approve=approve,
                emit=emit,
                skills=args.skill,
                mcp=args.mcp,
            ) as agent:
                state["session"] = agent.session
                await agent.run(prompt)
        except asyncio.CancelledError:
            events.put(("text", "Cancelled."))
        except Exception as exc:
            events.put(("text", str(exc)))
        finally:
            state.update(busy=False, task=None, loop=None)

    def submit(event=None):
        prompt = entry.get().strip()
        if prompt and not state["busy"]:
            entry.delete(0, "end")
            state["busy"] = True
            events.put(("text", "you> " + prompt))
            threading.Thread(target=lambda: asyncio.run(work(prompt)), daemon=True).start()

    def cancel():
        if state["loop"] and state["task"]:
            state["loop"].call_soon_threadsafe(state["task"].cancel)

    def finish(future, answer):
        if not future.done():
            future.set_result(answer)

    def poll():
        while not events.empty():
            event = events.get_nowait()
            if event[0] == "approval":
                _, action, future, loop = event
                answer = messagebox.askyesno(
                    "Approve action", f"{action.tool}\n{action.preview or json.dumps(action.arguments)}"
                )
                loop.call_soon_threadsafe(finish, future, answer)
            else:
                output.configure(state="normal")
                output.insert("end", event[1] + "\n")
                output.configure(state="disabled")
                output.see("end")
        window.after(100, poll)

    def close():
        cancel()
        # Wait for subprocess-group cancellation and journal finalization before destroying the UI.
        if state["busy"]:
            window.after(100, close)
        else:
            window.destroy()

    entry.bind("<Return>", submit)
    tk.Button(window, text="Send", command=submit).pack(side="left")
    tk.Button(window, text="Cancel", command=cancel).pack(side="left")
    window.protocol("WM_DELETE_WINDOW", close)
    poll()
    window.mainloop()
