"""Tests for updating references from actual Home Assistant configurations."""

import asyncio
import copy
from typing import Any, Dict, Optional

from dependency_updater import DependencyUpdater


class FakeDependencyUpdater(DependencyUpdater):
    """Store Home Assistant configurations in memory for updater tests."""

    def __init__(self, configs: Dict[str, Dict[str, Dict[str, Any]]]) -> None:
        """Initialize the fake with configurations grouped by domain and ID."""
        self.configs = copy.deepcopy(configs)
        self.saved = []

    async def _get(self, kind: str, config_id: str) -> Optional[Dict[str, Any]]:
        """Return a copied configuration from the in-memory store."""
        config = self.configs.get(kind, {}).get(config_id)
        return copy.deepcopy(config) if config is not None else None

    async def _save(self, kind: str, config_id: str, config: Dict[str, Any]) -> bool:
        """Persist a copied configuration in the in-memory store."""
        self.configs[kind][config_id] = copy.deepcopy(config)
        self.saved.append((kind, config_id))
        return True

    async def get_scene_config(self, scene_numeric_id: str) -> Optional[Dict[str, Any]]:
        """Return a scene configuration."""
        return await self._get("scenes", scene_numeric_id)

    async def update_scene_config(self, scene_numeric_id: str, config: Dict[str, Any]) -> bool:
        """Save a scene configuration."""
        return await self._save("scenes", scene_numeric_id, config)

    async def get_script_config(self, script_id: str) -> Optional[Dict[str, Any]]:
        """Return a script configuration."""
        return await self._get("scripts", script_id)

    async def update_script_config(self, script_id: str, config: Dict[str, Any]) -> bool:
        """Save a script configuration."""
        return await self._save("scripts", script_id, config)

    async def get_automation_config(self, automation_numeric_id: str) -> Optional[Dict[str, Any]]:
        """Return an automation configuration."""
        return await self._get("automations", automation_numeric_id)

    async def update_automation_config(self, automation_numeric_id: str, config: Dict[str, Any]) -> bool:
        """Save an automation configuration."""
        return await self._save("automations", automation_numeric_id, config)

    async def get_group_config_entries(self) -> list[dict[str, Any]]:
        """Return configured Group helpers from the in-memory store."""
        return copy.deepcopy(list(self.configs.get("groups", {}).values()))

    async def start_group_options_flow(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Expose stored helper options in the shape of an HA options form."""
        options = self.configs["groups"][entry_id]["options"]
        return {
            "flow_id": f"flow-{entry_id}",
            "data_schema": [{"name": key, "default": value} for key, value in options.items()],
        }

    async def abort_group_options_flow(self, flow_id: str) -> None:
        """Accept an unused fake flow."""

    async def update_group_config_entry(
        self,
        entry: Dict[str, Any],
        flow: Dict[str, Any],
        options: Dict[str, Any],
        members: list[str],
    ) -> bool:
        """Save Group helper members in memory."""
        entry["options"]["entities"] = members
        return await self._save("groups", entry["entry_id"], entry)

    async def update_legacy_group(self, state: Dict[str, Any], members: list[str]) -> bool:
        """Record an old-style group update in memory."""
        state["attributes"]["entity_id"] = members
        self.saved.append(("legacy_groups", state["entity_id"]))
        return True


def test_updates_actual_configs_without_state_attribute_hints() -> None:
    """References are found in configs even when runtime states do not expose them."""
    old_id = "sensor.old"
    new_id = "sensor.new"
    updater = FakeDependencyUpdater(
        {
            "scenes": {"scene-config": {"entities": {old_id: {"state": "on"}}}},
            "scripts": {"script.example": {"sequence": [{"target": {"entity_id": old_id}}]}},
            "automations": {"automation-config": {"actions": [{"data": {"value": "{{ states('sensor.old') }}"}}]}},
        }
    )
    states = [
        {"entity_id": "scene.example", "attributes": {"id": "scene-config"}},
        {"entity_id": "script.example", "attributes": {}},
        {"entity_id": "automation.example", "attributes": {"id": "automation-config"}},
    ]

    result = asyncio.run(updater.update_all_dependencies(old_id, new_id, states))

    assert result["total_success"] == 3
    assert updater.saved == [
        ("scenes", "scene-config"),
        ("scripts", "script.example"),
        ("automations", "automation-config"),
    ]
    assert old_id not in str(updater.configs)
    assert new_id in str(updater.configs)


def test_ignores_configs_without_matching_reference() -> None:
    """Configurations that do not reference the old entity remain untouched."""
    updater = FakeDependencyUpdater(
        {
            "scenes": {},
            "scripts": {"script.example": {"sequence": [{"entity_id": "sensor.other"}]}},
            "automations": {},
        }
    )
    states = [{"entity_id": "script.example", "attributes": {}}]

    result = asyncio.run(updater.update_all_dependencies("sensor.old", "sensor.new", states))

    assert result["total_success"] == 0
    assert result["total_failed"] == 0
    assert updater.saved == []


def test_updates_ui_group_helpers_and_legacy_groups() -> None:
    """Both supported Home Assistant group storage mechanisms are rewritten."""
    updater = FakeDependencyUpdater(
        {
            "scenes": {},
            "scripts": {},
            "automations": {},
            "groups": {
                "entry-1": {
                    "entry_id": "entry-1",
                    "title": "Downstairs lights",
                    "options": {
                        "group_type": "light",
                        "name": "Downstairs lights",
                        "entities": ["light.old", "light.other"],
                        "all": True,
                    },
                }
            },
        }
    )
    states = [
        {
            "entity_id": "group.evening",
            "attributes": {"entity_id": ["light.old", "switch.other"]},
        }
    ]

    result = asyncio.run(updater.update_all_dependencies("light.old", "light.new", states))

    assert result["groups"]["success"] == ["Downstairs lights", "group.evening"]
    assert result["total_success"] == 2
    assert updater.configs["groups"]["entry-1"]["options"]["entities"] == ["light.new", "light.other"]
    assert updater.saved == [("groups", "entry-1"), ("legacy_groups", "group.evening")]


def test_legacy_group_updates_accumulate_across_batch_renames() -> None:
    """Later member updates retain IDs already replaced in the same state snapshot."""
    updater = FakeDependencyUpdater({"scenes": {}, "scripts": {}, "automations": {}, "groups": {}})
    states = [
        {
            "entity_id": "group.all_lights",
            "attributes": {"entity_id": ["light.old_one", "light.old_two"]},
        }
    ]

    asyncio.run(updater.update_all_dependencies("light.old_one", "light.new_one", states))
    asyncio.run(updater.update_all_dependencies("light.old_two", "light.new_two", states))

    assert states[0]["attributes"]["entity_id"] == ["light.new_one", "light.new_two"]


def test_group_helper_options_flow_preserves_behavior_options() -> None:
    """Saving members carries the Group helper's type-specific settings forward."""

    class RecordingUpdater(DependencyUpdater):
        def __init__(self) -> None:
            self.calls = []

        async def _request_json(self, method: str, path: str, payload=None):
            self.calls.append((method, path, payload))
            if path == "/api/config/config_entries/options/flow":
                return 200, {"flow_id": "flow-1", "type": "form"}
            return 200, {"type": "create_entry"}

    updater = RecordingUpdater()
    entry = {
        "entry_id": "entry-1",
        "options": {
            "name": "Temperatures",
            "group_type": "sensor",
            "entities": ["sensor.old"],
            "type": "mean",
            "ignore_non_numeric": True,
            "hide_members": False,
        },
    }

    flow = {
        "flow_id": "flow-1",
        "data_schema": [
            {"name": "entities", "default": ["sensor.old"]},
            {"name": "type", "default": "mean"},
            {"name": "ignore_non_numeric", "suggested_value": True},
            {"name": "hide_members", "description": {"suggested_value": False}},
        ],
    }
    options = updater.group_options_from_flow(flow)
    success = asyncio.run(updater.update_group_config_entry(entry, flow, options, ["sensor.new"]))

    assert success is True
    assert updater.calls == [
        (
            "POST",
            "/api/config/config_entries/options/flow/flow-1",
            {
                "hide_members": False,
                "type": "mean",
                "ignore_non_numeric": True,
                "entities": ["sensor.new"],
            },
        )
    ]
