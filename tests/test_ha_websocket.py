"""Timeout and lifecycle tests for the Home Assistant WebSocket client."""

import asyncio

import pytest

from ha_websocket import HomeAssistantWebSocket


class NeverResponds:
    async def recv(self):
        await asyncio.sleep(1)


def test_receive_message_has_a_bounded_timeout():
    client = HomeAssistantWebSocket("ws://example", "token", io_timeout=0.01)
    client.websocket = NeverResponds()

    with pytest.raises(TimeoutError, match="did not respond"):
        asyncio.run(client._receive_message())
