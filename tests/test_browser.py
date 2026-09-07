import asyncio

import pytest
from aiohttp import WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from codeweaver.browser import create_app
from codeweaver.configuration import Settings

TOKEN = "test-token-not-a-real-secret-1234567890"


async def receive_type(ws, expected):
    while True:
        message = await asyncio.wait_for(ws.receive_json(), 3)
        if message["type"] == expected:
            return message


async def test_rejects_missing_auth_external_origin_and_wrong_host(tmp_path, unused_tcp_port):
    origin = f"http://127.0.0.1:{unused_tcp_port}"
    app = create_app(tmp_path, Settings(provider="demo"), TOKEN, origin=origin)
    async with TestClient(TestServer(app, port=unused_tcp_port)) as client:
        with pytest.raises(WSServerHandshakeError) as failure:
            await client.ws_connect("/ws")
        assert failure.value.status == 401
        with pytest.raises(WSServerHandshakeError) as failure:
            await client.ws_connect(
                "/ws", headers={"Authorization": "Bearer " + TOKEN, "Origin": "https://untrusted.invalid"}
            )
        assert failure.value.status == 403
        response = await client.get("/", headers={"Host": "untrusted.invalid"})
        assert response.status == 403
        assert TOKEN not in await (await client.get("/")).text()


async def test_authenticated_browser_protocol_and_demo_round_trip(tmp_path, unused_tcp_port):
    origin = f"http://127.0.0.1:{unused_tcp_port}"
    app = create_app(tmp_path, Settings(provider="demo"), TOKEN, origin=origin)
    async with TestClient(TestServer(app, port=unused_tcp_port)) as client:
        async with client.ws_connect(
            "/ws", origin=origin, protocols=["codeweaver", "cw-auth-" + TOKEN]
        ) as ws:
            assert (await ws.receive_json())["type"] == "connected"
            await ws.send_json({"type": "message", "text": "Inspect"})
            assert (await receive_type(ws, "result"))["status"] == "completed"


class Writer:
    def __init__(self):
        self.turn = 0

    async def reply(self, instructions, messages, tools):
        self.turn += 1
        if self.turn == 1:
            return {
                "role": "assistant",
                "text": "",
                "calls": [
                    {
                        "id": "w",
                        "name": "write_file",
                        "arguments": {"path": "approved.txt", "content": "yes", "expected_sha256": None},
                    }
                ],
            }
        return {"role": "assistant", "text": "Done", "calls": []}


async def test_permission_cannot_be_approved_by_another_authenticated_socket(tmp_path, unused_tcp_port):
    app = create_app(
        tmp_path,
        Settings(provider="demo"),
        TOKEN,
        origin=f"http://127.0.0.1:{unused_tcp_port}",
        model_factory=lambda _: Writer(),
    )
    headers = {"Authorization": "Bearer " + TOKEN}
    async with TestClient(TestServer(app, port=unused_tcp_port)) as client:
        async with (
            client.ws_connect("/ws", headers=headers) as first,
            client.ws_connect("/ws", headers=headers) as second,
        ):
            await first.receive_json()
            await second.receive_json()
            await first.send_json({"type": "message", "text": "Write a file"})
            approval = await receive_type(first, "approval")
            await second.send_json({"type": "approve", "id": approval["id"], "allow": True})
            await asyncio.sleep(0.05)
            assert not (tmp_path / "approved.txt").exists()
            await first.send_json({"type": "approve", "id": approval["id"], "allow": True})
            assert (await receive_type(first, "result"))["status"] == "completed"
            assert (tmp_path / "approved.txt").read_text() == "yes"


async def test_disconnect_cancels_pending_write_without_approval(tmp_path, unused_tcp_port):
    app = create_app(
        tmp_path,
        Settings(provider="demo"),
        TOKEN,
        origin=f"http://127.0.0.1:{unused_tcp_port}",
        model_factory=lambda _: Writer(),
    )
    async with TestClient(TestServer(app, port=unused_tcp_port)) as client:
        ws = await client.ws_connect("/ws", headers={"Authorization": "Bearer " + TOKEN})
        await ws.receive_json()
        await ws.send_json({"type": "message", "text": "Write"})
        await receive_type(ws, "approval")
        await ws.close()
        await asyncio.sleep(0.05)
        assert not (tmp_path / "approved.txt").exists()
