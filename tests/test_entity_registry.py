"""Tests for entity-registry update messages."""

import asyncio

from entity_registry import EntityRegistry


class MockWebSocket:
    """Capture one entity-registry request and return a successful response."""

    def __init__(self) -> None:
        """Initialize the captured-message list."""
        self.messages = []

    async def _send_message(self, message: dict) -> int:
        """Capture a WebSocket message and return its ID."""
        self.messages.append(message)
        return 1

    async def _receive_message(self) -> dict:
        """Return a successful entity-registry response."""
        return {"id": 1, "success": True, "result": {}}


def test_empty_name_is_sent_as_explicit_blank_override() -> None:
    """An empty suffix must suppress, rather than expose, the native name."""
    websocket = MockWebSocket()

    asyncio.run(EntityRegistry(websocket).update_entity("light.old", new_entity_id="light.new", name=""))

    assert websocket.messages == [
        {
            "type": "config/entity_registry/update",
            "entity_id": "light.old",
            "new_entity_id": "light.new",
            "name": "",
        }
    ]


def test_null_name_clears_registry_override() -> None:
    """JSON null removes the override and falls back to the native name."""
    websocket = MockWebSocket()

    asyncio.run(EntityRegistry(websocket).update_entity("light.old", name=None))

    assert websocket.messages == [
        {
            "type": "config/entity_registry/update",
            "entity_id": "light.old",
            "name": None,
        }
    ]


def test_omitted_name_does_not_change_registry_override() -> None:
    """Leaving the optional name out must preserve the current override."""
    websocket = MockWebSocket()

    asyncio.run(EntityRegistry(websocket).update_entity("light.old", new_entity_id="light.new"))

    assert websocket.messages == [
        {
            "type": "config/entity_registry/update",
            "entity_id": "light.old",
            "new_entity_id": "light.new",
        }
    ]
