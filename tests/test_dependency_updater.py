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
