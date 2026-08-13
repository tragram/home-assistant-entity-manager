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


def test_blank_entity_override_is_distinct_from_cleared_name() -> None:
    """An explicit blank suppresses the native name; null exposes it."""
    assert web_ui._effective_registry_name({"name": "", "original_name": "Native"}) == ""
    assert web_ui._effective_registry_name({"name": None, "original_name": "Native"}) == "Native"
    assert web_ui._entity_registry_name_matches({"name": "", "original_name": "Native"}, "") is True
    assert web_ui._entity_registry_name_matches({"name": None, "original_name": "Native"}, "") is False
    assert web_ui._entity_registry_name_matches({"name": None, "original_name": None}, "") is True
    assert web_ui._entity_registry_name_matches({"name": None, "original_name": "Native"}, None) is True
    assert web_ui._entity_registry_name_matches({"name": "Custom", "original_name": "Native"}, None) is False


def test_entity_name_match_prefers_user_override() -> None:
    """A user override, including a stale one, takes precedence over the native name."""
    entity = {"name": "Old custom name", "original_name": "Firmware"}

    assert web_ui._entity_registry_name_matches(entity, "Firmware") is False
    assert web_ui._entity_registry_name_matches(entity, "Old custom name") is True


def test_rename_device_enqueues_entity_id_reset(client):
    """Single-device renames can explicitly rebuild every entity ID."""
    c, store = client

    response = c.post(
        "/api/rename_device",
        json={"device_id": "dev1", "new_name": "Kitchen Light", "reset_entity_ids": True},
    )

    assert response.status_code == 202
    job = response.get_json()
    assert store.load(job["job_id"])["payload"] == {
        "device_id": "dev1",
        "new_name": "Kitchen Light",
        "reset_entity_ids": True,
    }


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


def test_batch_device_rename_enqueues_sanitized_changes(client):
    """A batch request stores all independently editable device names."""
    c, store = client

    response = c.post(
        "/api/rename_devices",
        json={
            "devices": [
                {"device_id": "dev1", "new_name": " Hall Lamp ", "reset_entity_ids": True},
                {"device_id": "dev2", "new_name": "Kitchen Lamp"},
            ]
        },
    )

    assert response.status_code == 202
    job = response.get_json()
    assert job["type"] == "rename_devices"
    assert store.load(job["job_id"])["payload"]["devices"] == [
        {"device_id": "dev1", "new_name": "Hall Lamp", "reset_entity_ids": True},
        {"device_id": "dev2", "new_name": "Kitchen Lamp"},
    ]


@pytest.mark.parametrize(
    "devices,error",
    [
        ([], "Select at least one device"),
        ([{"device_id": "dev1", "new_name": ""}], "Invalid device name"),
        (
            [
                {"device_id": "dev1", "new_name": "One"},
                {"device_id": "dev1", "new_name": "Two"},
            ],
            "appears more than once",
        ),
    ],
)
def test_batch_device_rename_rejects_invalid_changes(client, devices, error):
    """Malformed or duplicate device rows are rejected before enqueueing."""
    c, _ = client

    response = c.post("/api/rename_devices", json={"devices": devices})

    assert response.status_code == 400
    assert error in response.get_json()["error"]


def test_batch_device_rename_rejects_device_in_another_rename(client):
    """A device cannot be queued in both a single and batch rename."""
    c, _ = client
    assert c.post("/api/rename_device", json={"device_id": "dev1", "new_name": "One"}).status_code == 202

    response = c.post(
        "/api/rename_devices",
        json={"devices": [{"device_id": "dev1", "new_name": "Two"}]},
    )

    assert response.status_code == 409
    assert response.get_json()["device_ids"] == ["dev1"]


def test_single_device_rename_rejects_device_in_batch(client):
    """The overlap guard works regardless of which rename type was queued first."""
    c, _ = client
    assert (
        c.post(
            "/api/rename_devices",
            json={"devices": [{"device_id": "dev1", "new_name": "One"}]},
        ).status_code
        == 202
    )

    response = c.post("/api/rename_device", json={"device_id": "dev1", "new_name": "Two"})

    assert response.status_code == 409


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


def test_device_rename_plan_resets_ids_and_names() -> None:
    """A full reset uses native naming context for both IDs and names."""

    class FakeRestructurer:
        entities = {"sensor.custom_id": {"device_id": "dev1"}}

        def generate_new_entity_id(
            self,
            entity_id: str,
            state: dict,
            entity_name: str | None = None,
        ) -> tuple[str, str]:
            suffix = entity_name or state["attributes"]["native_name"]
            return f"sensor.kitchen_{suffix.lower().replace(' ', '_')}", suffix

    changes = web_ui._plan_device_entity_changes(
        FakeRestructurer(),
        "dev1",
        [{"entity_id": "sensor.custom_id", "attributes": {"native_name": "Temperature"}}],
        {"sensor.custom_id": "Custom suffix"},
        {"sensor.custom_id": "My displayed temperature"},
        reset_entity_ids=True,
    )

    assert changes == [("sensor.custom_id", "sensor.kitchen_temperature", "Temperature")]


def test_device_rename_includes_switch_as_light_helper() -> None:
    """A device rename includes helpers linked by source entity ID or registry UUID."""

    class FakeRestructurer:
        entities = {
            "switch.kitchen_plug": {"device_id": "dev1", "id": "source-registry-id"},
            "light.kitchen_plug": {
                "device_id": None,
                "id": "helper-registry-id",
                "platform": "switch_as_x",
                "options": {
                    "switch_as_x": {
                        "entity_id": "source-registry-id",
                        "invert": False,
                    }
                },
                "original_name": "Plug",
            },
            "sensor.unrelated": {
                "device_id": None,
                "options": {"example": {"entity_id": "sensor.elsewhere"}},
            },
        }

        def build_naming_context(self, entity_id: str, state: dict, device_id: str | None = None) -> dict[str, str]:
            assert entity_id != "light.kitchen_plug" or device_id == "dev1"
            return {"entity": "Plug"}

        def generate_new_entity_id(
            self,
            entity_id: str,
            state: dict,
            entity_name: str | None = None,
            device_id: str | None = None,
        ) -> tuple[str, str]:
            assert entity_id != "light.kitchen_plug" or device_id == "dev1"
            domain = entity_id.partition(".")[0]
            return f"{domain}.dining_room_plug", entity_name or "Plug"

    restructurer = FakeRestructurer()
    states = [
        {"entity_id": "switch.kitchen_plug", "attributes": {}},
        {"entity_id": "light.kitchen_plug", "attributes": {}},
    ]
    names = web_ui._capture_device_entity_names(restructurer, "dev1", states)

    assert names == {"switch.kitchen_plug": "Plug", "light.kitchen_plug": "Plug"}
    assert web_ui._plan_device_entity_changes(restructurer, "dev1", states, names) == [
        ("switch.kitchen_plug", "switch.dining_room_plug", "Plug"),
        ("light.kitchen_plug", "light.dining_room_plug", "Plug"),
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


def test_device_rename_preserves_explicit_ha_entity_name() -> None:
    """Renaming a device must not reset an entity name assigned by the user in HA."""

    class FakeRestructurer:
        """Model one user-named entity on a renamed device."""

        entities = {
            "sensor.kitchen_shelly_power": {
                "device_id": "dev1",
                "name": "Power",
                "original_name": "Switch power",
            }
        }

        def build_naming_context(self, entity_id: str, state: dict) -> dict[str, str]:
            """Return the integration's native suffix when no user name exists."""
            return {"entity": "Switch power"}

        def generate_new_entity_id(
            self,
            entity_id: str,
            state: dict,
            entity_name: str | None = None,
        ) -> tuple[str, str]:
            """Generate an ID while modeling a full generated friendly name."""
            suffix = (entity_name or "").lower().replace(" ", "_")
            return f"sensor.living_room_shelly_{suffix}", f"Living room Shelly {entity_name}"

    restructurer = FakeRestructurer()
    states = [{"entity_id": "sensor.kitchen_shelly_power", "attributes": {}}]
    entity_names = web_ui._capture_device_entity_names(restructurer, "dev1", states)
    user_names = web_ui._capture_device_user_names(restructurer, "dev1")

    assert entity_names == {"sensor.kitchen_shelly_power": "Power"}
    assert web_ui._plan_device_entity_changes(restructurer, "dev1", states, entity_names, user_names) == [
        ("sensor.kitchen_shelly_power", "sensor.living_room_shelly_power", "Power")
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


def test_single_entity_rename_can_remove_friendly_name_override(monkeypatch) -> None:
    """An explicit null reaches HA and removes the registry name override."""
    calls = []

    class FakeWebSocket:
        def __init__(self, url: str, token: str) -> None:
            pass

        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

    class FakeEntityRegistry:
        def __init__(self, websocket: FakeWebSocket) -> None:
            pass

        async def rename_entity(
            self,
            old_entity_id: str,
            new_entity_id: str | None,
            friendly_name: str | None,
        ) -> dict:
            calls.append((old_entity_id, new_entity_id, friendly_name))
            return {"entity_id": old_entity_id}

    monkeypatch.setenv("HA_URL", "http://homeassistant:8123")
    monkeypatch.setenv("HA_TOKEN", "token")
    monkeypatch.setattr(web_ui, "HomeAssistantWebSocket", FakeWebSocket)
    monkeypatch.setattr(web_ui, "EntityRegistry", FakeEntityRegistry)

    with web_ui.app.test_request_context(
        "/api/rename_entity",
        method="POST",
        json={"old_entity_id": "light.kitchen_lamp", "new_friendly_name": None},
    ):
        response = asyncio.run(web_ui._rename_entity_async())

    assert response.get_json()["success"] is True
    assert calls == [("light.kitchen_lamp", None, None)]


def test_device_rename_updates_dashboards_when_dependency_update_fails(monkeypatch) -> None:
    """A REST failure cannot discard a successful entity rename from the dashboard batch."""
    dashboard_calls = []

    class FakeWebSocket:
        """Provide the connection lifecycle used by the worker."""

        def __init__(self, url: str, token: str) -> None:
            """Accept the configured HA connection details."""

        async def connect(self) -> None:
            """Open the fake connection."""

        async def disconnect(self) -> None:
            """Close the fake connection."""

    class FakeRestructurer:
        """Expose one entity belonging to the renamed device."""

        entities = {"light.old_lamp": {"device_id": "dev1", "name": "Lamp"}}

        async def load_structure(self, websocket: FakeWebSocket) -> None:
            """Accept registry reloads."""

    class FakeDependencyUpdater:
        """Fail after HA has already accepted the entity rename."""

        def __init__(self, base_url: str, token: str) -> None:
            """Accept connection settings."""

        async def get_states(self) -> list[dict]:
            """Return the state used to plan the rename."""
            return [{"entity_id": "light.old_lamp", "attributes": {}}]

        async def update_all_dependencies(self, old_id: str, new_id: str, states: list[dict]) -> dict:
            """Model a failed automation API request."""
            raise RuntimeError("automation API unavailable")

    class FakeReferenceUpdater:
        """Record the dashboard rename batch."""

        def __init__(self, dependencies: FakeDependencyUpdater, lovelace: object) -> None:
            """Accept updater dependencies."""

        async def update_dashboards(self, rename_pairs: list[tuple[str, str]]) -> dict:
            """Record and accept the dashboard update."""
            dashboard_calls.append(rename_pairs)
            return {"updated": ["lovelace"], "manual": []}

    class FakeDeviceRegistry:
        """Accept the device rename."""

        def __init__(self, websocket: FakeWebSocket) -> None:
            """Accept the worker WebSocket."""

        async def rename_device(self, device_id: str, new_name: str) -> bool:
            """Report a successful device rename."""
            return True

    class FakeEntityRegistry:
        """Accept the planned entity rename."""

        def __init__(self, websocket: FakeWebSocket) -> None:
            """Accept the worker WebSocket."""

        async def rename_entity(self, old_id: str, new_id: str, name: str) -> None:
            """Report a successful entity rename."""

    class FakeContext:
        """Collect no-op worker progress and log events."""

        def progress(self, completed: int, total: int, **details) -> None:
            """Accept a progress update."""

        def log(self, level: str, message: str) -> None:
            """Accept a worker log entry."""

    async def fake_init_client() -> None:
        """Keep the preconfigured fake restructurer."""

    async def fake_sync(*args) -> dict:
        """Skip Zigbee2MQTT synchronization."""
        return {"supported": False, "synced": False}

    monkeypatch.setenv("HA_URL", "http://homeassistant:8123")
    monkeypatch.setenv("HA_TOKEN", "token")
    monkeypatch.setitem(web_ui.renamer_state, "restructurer", FakeRestructurer())
    monkeypatch.setattr(web_ui, "HomeAssistantWebSocket", FakeWebSocket)
    monkeypatch.setattr(web_ui, "DependencyUpdater", FakeDependencyUpdater)
    monkeypatch.setattr(web_ui, "ReferenceUpdater", FakeReferenceUpdater)
    monkeypatch.setattr(web_ui, "LovelaceUpdater", lambda websocket: object())
    monkeypatch.setattr(web_ui, "DeviceRegistry", FakeDeviceRegistry)
    monkeypatch.setattr(web_ui, "EntityRegistry", FakeEntityRegistry)
    monkeypatch.setattr(web_ui, "init_client", fake_init_client)
    monkeypatch.setattr(web_ui, "_sync_z2m_name", fake_sync)
    monkeypatch.setattr(web_ui, "_capture_device_entity_names", lambda *args: {"light.old_lamp": ""})
    monkeypatch.setattr(
        web_ui,
        "_plan_device_entity_changes",
        lambda *args: [("light.old_lamp", "light.new_lamp", "Lamp")],
    )

    result = asyncio.run(
        web_ui.rename_device_handler(
            {"payload": {"device_id": "dev1", "new_name": "New Lamp"}},
            FakeContext(),
        )
    )

    assert result["entities_updated"] == 1
    assert result["entities_failed"] == 0
    assert result["dashboards_updated"] == ["lovelace"]
    assert dashboard_calls == [[("light.old_lamp", "light.new_lamp")]]


def test_batch_device_rename_continues_after_individual_failure(monkeypatch) -> None:
    """A failed device is recorded without preventing later devices from running."""
    calls = []

    async def fake_rename_device(job: dict, ctx: object) -> dict:
        """Return a success, failure, and warning for three generic devices."""
        device_id = job["payload"]["device_id"]
        calls.append(device_id)
        if device_id == "dev2":
            raise RuntimeError("registry unavailable")
        return {
            "entities_failed": 1 if device_id == "dev3" else 0,
            "z2m_failed": None,
            "dashboard_manual_updates": [],
        }

    class FakeContext:
        """Record batch progress and log updates."""

        def __init__(self) -> None:
            """Create empty event collections."""
            self.progress_events = []
            self.log_events = []

        def progress(self, done: int, total: int, current: str = "") -> None:
            """Record a progress update."""
            self.progress_events.append((done, total, current))

        def log(self, step: str, message: str) -> None:
            """Record a log update."""
            self.log_events.append((step, message))

    monkeypatch.setattr(web_ui, "rename_device_handler", fake_rename_device)
    context = FakeContext()
    job = {
        "payload": {
            "devices": [
                {"device_id": "dev1", "new_name": "One"},
                {"device_id": "dev2", "new_name": "Two"},
                {"device_id": "dev3", "new_name": "Three"},
            ]
        }
    }

    result = asyncio.run(web_ui.rename_devices_handler(job, context))

    assert calls == ["dev1", "dev2", "dev3"]
    assert (result["completed"], result["warnings"], result["failed"]) == (1, 1, 1)
    assert [device["status"] for device in result["devices"]] == ["completed", "failed", "warning"]
    assert context.progress_events[-1] == (3, 3, "Finished Three")


def test_device_type_prefers_control_domain_over_diagnostics() -> None:
    """Device browsing categories use the most useful exposed domain."""
    assert web_ui._device_type_from_domains(["sensor", "binary_sensor", "light"]) == "light"
    assert web_ui._device_type_from_domains(["sensor", "binary_sensor"]) == "sensor"
    assert web_ui._device_type_from_domains([]) is None
