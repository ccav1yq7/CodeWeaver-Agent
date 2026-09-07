"""Loopback-only browser UI with authenticated sockets and per-connection approvals."""

import asyncio
import contextlib
import hmac
import os
import re
import uuid
from urllib.parse import urlsplit

from aiohttp import web

from .runtime import session

PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><title>CodeWeaver</title>
<style>body{max-width:900px;margin:40px auto;font:16px system-ui;background:#f4f4f1;color:#17202a}input,textarea,button{font:inherit;padding:10px;margin:5px}pre{white-space:pre-wrap;background:white;padding:20px}textarea{width:90%}</style>
<h1>CodeWeaver</h1><p>Enter the token configured in CODEWEAVER_REMOTE_TOKEN. It stays in this page's memory.</p>
<input id="token" type="password" autocomplete="off" placeholder="Access token"><button id="connect">Connect</button>
<pre id="log"></pre><textarea id="prompt" placeholder="Describe your task"></textarea>
<button id="send">Send</button><button id="cancel">Cancel task</button>
<script>
let socket;const log=document.querySelector('#log');
function show(s){log.textContent+=s+'\\n';}
document.querySelector('#connect').onclick=()=>{if(socket)socket.close();socket=new WebSocket('ws://'+location.host+'/ws',['codeweaver','cw-auth-'+document.querySelector('#token').value]);
socket.onmessage=e=>{const m=JSON.parse(e.data);if(m.type==='approval'){const yes=confirm(m.tool+'\\n'+(m.preview||JSON.stringify(m.arguments)));socket.send(JSON.stringify({type:'approve',id:m.id,allow:yes}));}else show(m.text||JSON.stringify(m));};socket.onclose=()=>show('Disconnected');socket.onerror=()=>show('Connection rejected. Check the token.');};
document.querySelector('#send').onclick=()=>{if(socket&&socket.readyState===1)socket.send(JSON.stringify({type:'message',text:document.querySelector('#prompt').value}));};
document.querySelector('#cancel').onclick=()=>{if(socket&&socket.readyState===1)socket.send(JSON.stringify({type:'cancel'}));};
</script></html>"""


def create_app(
    root, settings, token: str, *, origin="http://127.0.0.1:18888", model_factory=None, skills=(), mcp=False
):
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        raise ValueError("CODEWEAVER_REMOTE_TOKEN must contain 32–256 URL-safe characters")
    expected_host = urlsplit(origin).netloc

    @web.middleware
    async def boundary(request, handler):
        if request.host != expected_host:
            raise web.HTTPForbidden(text="Host rejected")
        response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    async def index(request):
        return web.Response(text=PAGE, content_type="text/html")

    async def websocket(request):
        request_origin = request.headers.get("Origin")
        if request_origin is not None and request_origin != origin:
            raise web.HTTPForbidden(text="Origin rejected")
        authorization = request.headers.get("Authorization", "")
        supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
        if not supplied and request_origin == origin:
            supplied = next(
                (
                    p.strip()[8:]
                    for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
                    if p.strip().startswith("cw-auth-")
                ),
                "",
            )
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            raise web.HTTPUnauthorized(text="Authentication required")
        ws = web.WebSocketResponse(protocols=["codeweaver"], max_msg_size=65536, heartbeat=30)
        await ws.prepare(request)
        pending = {}
        running = None
        current_session = None

        async def approval(action):
            key = uuid.uuid4().hex
            future = asyncio.get_running_loop().create_future()
            pending[key] = future
            try:
                await ws.send_json(
                    {
                        "type": "approval",
                        "id": key,
                        "tool": action.tool,
                        "arguments": action.arguments,
                        "preview": action.preview,
                    }
                )
                return await asyncio.wait_for(future, 120)
            except TimeoutError:
                return False
            finally:
                pending.pop(key, None)

        async def emit(event):
            await ws.send_json(event)

        async def work(prompt):
            nonlocal current_session
            try:
                model = model_factory(settings) if model_factory else None
                async with session(
                    root,
                    settings,
                    resume=current_session,
                    approve=approval,
                    emit=emit,
                    model=model,
                    skills=skills,
                    mcp=mcp,
                ) as agent:
                    current_session = agent.session
                    await ws.send_json({"type": "result", **await agent.run(prompt)})
            except asyncio.CancelledError:
                if not ws.closed:
                    await ws.send_json({"type": "cancelled"})
            except Exception as exc:
                if not ws.closed:
                    await ws.send_json({"type": "error", "text": str(exc)[:1000]})

        await ws.send_json({"type": "connected"})
        try:
            async for incoming in ws:
                if incoming.type != web.WSMsgType.TEXT:
                    continue
                try:
                    message = incoming.json()
                    if not isinstance(message, dict):
                        raise ValueError()
                except (ValueError, TypeError):
                    await ws.send_json({"type": "error", "text": "Expected a JSON object"})
                    continue
                if message.get("type") == "approve":
                    future = pending.get(message.get("id"))
                    if future is not None and not future.done():
                        future.set_result(message.get("allow") is True)
                elif message.get("type") == "cancel":
                    if running:
                        running.cancel()
                elif message.get("type") == "message":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "text": "A task is already running"})
                    elif isinstance(message.get("text"), str):
                        running = asyncio.create_task(work(message["text"]))
        finally:
            if running and not running.done():
                running.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await running
            for future in pending.values():
                if not future.done():
                    future.set_result(False)
        return ws

    app = web.Application(middlewares=[boundary], client_max_size=65536)
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket)
    return app


def launch(args, settings):
    if not 1 <= args.port <= 65535:
        raise ValueError("Invalid port")
    app = create_app(
        args.root,
        settings,
        os.environ.get("CODEWEAVER_REMOTE_TOKEN", ""),
        origin=f"http://127.0.0.1:{args.port}",
        skills=args.skill,
        mcp=args.mcp,
    )
    web.run_app(app, host="127.0.0.1", port=args.port, access_log=None)
