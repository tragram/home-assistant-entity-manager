"""Tests for the async rename_device endpoint (request-thread path only).

These verify that the request thread validates, sanitizes and enqueues the job
(and copies the payload, since the worker thread has no request context) without
touching Home Assistant. The worker is not started, so enqueued jobs stay queued.
"""

import asyncio

import pytest

from jobs import TERMINAL_STATES, JobStore, JobWorker
import web_ui


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = JobStore(str(tmp_path), terminal_states=TERMINAL_STATES)
    monkeypatch.setitem(web_ui.renamer_state, "job_store", store)
    monkeypatch.setitem(web_ui.renamer_state, "worker", JobWorker(store))
    web_ui.app.config["TESTING"] = True
    return web_ui.app.test_client(), store


def test_rename_device_enqueues_job(client):
    c, store = client
    resp = c.post("/api/rename_device", json={"device_id": "dev1", "new_name": "Kitchen Light"})
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["type"] == "rename_device"
    assert body["state"] == "queued"
    assert store.load(body["job_id"])["payload"] == {"device_id": "dev1", "new_name": "Kitchen Light"}


def test_rename_device_missing_field_is_400(client):
    c, _ = client
    resp = c.post("/api/rename_device", json={"device_id": "dev1"})
    assert resp.status_code == 400


def test_rename_device_duplicate_job_is_409(client):
    """Only concurrent jobs for the same device are rejected."""
    c, _ = client
    assert c.post("/api/rename_device", json={"device_id": "dev1", "new_name": "A"}).status_code == 202
    dup = c.post("/api/rename_device", json={"device_id": "dev1", "new_name": "B"})
    assert dup.status_code == 409


def test_rename_devices_may_share_display_name(client):
    """HA permits separate devices to use the same display name."""
    c, _ = client

    assert c.post("/api/rename_device", json={"device_id": "dev1", "new_name": "Lamp"}).status_code == 202
    assert c.post("/api/rename_device", json={"device_id": "dev2", "new_name": "Lamp"}).status_code == 202


def test_job_get_and_list(client):
    c, _ = client
    jid = c.post("/api/rename_device", json={"device_id": "dev1", "new_name": "A"}).get_json()["job_id"]
    assert c.get(f"/api/jobs/{jid}").get_json()["job_id"] == jid
    assert c.get("/api/jobs/does-not-exist").status_code == 404
    listing = c.get("/api/jobs").get_json()["jobs"]
    assert [j["job_id"] for j in listing] == [jid]


def test_device_rename_plan_uses_shared_naming_generator() -> None:
    """Device renames preserve distinct names through the shared generator."""

    class FakeRestructurer:
        """Generate deterministic IDs from native entity names."""

        entities = {
            "event.old_left": {"device_id": "dev1"},
            "event.old_right": {"device_id": "dev1"},
            "sensor.unrelated": {"device_id": "dev2"},
        }

        def generate_new_entity_id(
            self,
            entity_id: str,
            state: dict,
            entity_name: str | None = None,
        ) -> tuple[str, str]:
            """Return an ID containing the entity's distinct native name."""
            name = entity_name or state["attributes"]["native_name"]
            suffix = name.lower().replace(" ", "_")
            return f"event.hall_wall_switch_{suffix}", name

    states = [
        {"entity_id": "event.old_left", "attributes": {"native_name": "Button Left"}},
        {"entity_id": "event.old_right", "attributes": {"native_name": "Button Right"}},
    ]

    assert web_ui._plan_device_entity_changes(FakeRestructurer(), "dev1", states) == [
        ("event.old_left", "event.hall_wall_switch_button_left", "Button Left"),
        ("event.old_right", "event.hall_wall_switch_button_right", "Button Right"),
    ]


def test_device_rename_preserves_names_captured_before_device_change() -> None:
    """Same-domain entities remain distinct after their device name changes."""

    class FakeRestructurer:
        """Model naming context before and after a device rename."""

        entities = {
            "sensor.kitchen_sofa_energy": {"device_id": "dev1"},
            "sensor.kitchen_sofa_voltage": {"device_id": "dev1"},
        }

        def build_naming_context(self, entity_id: str, state: dict) -> dict[str, str]:
            """Extract the entity part while the old device name is known."""
            return {"entity": entity_id.rsplit("_", 1)[-1].title()}

        def generate_new_entity_id(
            self,
            entity_id: str,
            state: dict,
            entity_name: str | None = None,
        ) -> tuple[str, str]:
            """Generate an ID using the preserved entity-specific name."""
            suffix = (entity_name or "").lower().replace(" ", "_")
            return f"sensor.kitchen_sofa1_{suffix}", entity_name or ""

    restructurer = FakeRestructurer()
    states = [
        {"entity_id": "sensor.kitchen_sofa_energy", "attributes": {"friendly_name": "Kitchen Sofa Energy"}},
        {"entity_id": "sensor.kitchen_sofa_voltage", "attributes": {"friendly_name": "Kitchen Sofa Voltage"}},
    ]

    names = web_ui._capture_device_entity_names(restructurer, "dev1", states)

    assert web_ui._plan_device_entity_changes(restructurer, "dev1", states, names) == [
        ("sensor.kitchen_sofa_energy", "sensor.kitchen_sofa1_energy", "Energy"),
        ("sensor.kitchen_sofa_voltage", "sensor.kitchen_sofa1_voltage", "Voltage"),
    ]


def test_init_client_recreates_missing_restructurer(monkeypatch) -> None:
    """A worker can restore the restructurer when the REST client already exists."""
    client = object()
    monkeypatch.setitem(web_ui.renamer_state, "client", client)
    monkeypatch.setitem(web_ui.renamer_state, "restructurer", None)

    assert asyncio.run(web_ui.init_client()) is client
    assert web_ui.renamer_state["restructurer"].client is client


def test_single_entity_rename_can_clear_friendly_name(monkeypatch) -> None:
    """An explicitly empty name is sent to HA instead of rejected as missing."""
    calls = []

    class FakeWebSocket:
        """Provide the connection lifecycle used by the endpoint."""

        def __init__(self, url: str, token: str) -> None:
            """Accept the configured HA connection details."""

        async def connect(self) -> None:
            """Open the fake connection."""

        async def disconnect(self) -> None:
            """Close the fake connection."""

    class FakeEntityRegistry:
        """Record the update sent by the endpoint."""

        def __init__(self, websocket: FakeWebSocket) -> None:
            """Accept the endpoint's WebSocket client."""

        async def rename_entity(
            self,
            old_entity_id: str,
            new_entity_id: str | None,
            friendly_name: str | None,
        ) -> dict:
            """Record and accept an entity update."""
            calls.append((old_entity_id, new_entity_id, friendly_name))
            return {"entity_id": old_entity_id}

    monkeypatch.setenv("HA_URL", "http://homeassistant:8123")
    monkeypatch.setenv("HA_TOKEN", "token")
    monkeypatch.setattr(web_ui, "HomeAssistantWebSocket", FakeWebSocket)
    monkeypatch.setattr(web_ui, "EntityRegistry", FakeEntityRegistry)

    with web_ui.app.test_request_context(
        "/api/rename_entity",
        method="POST",
        json={"old_entity_id": "light.kitchen_lamp", "new_friendly_name": ""},
    ):
        response = asyncio.run(web_ui._rename_entity_async())

    assert response.get_json()["success"] is True
    assert calls == [("light.kitchen_lamp", None, "")]
