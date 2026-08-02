"""Tests for coordinated configuration and dashboard reference updates."""

import asyncio
from typing import Any, Dict, List, Optional

from reference_updater import ReferenceUpdater


class FakeDependencies:
    """Record dependency update calls and return a fixed result."""

    def __init__(self) -> None:
        """Initialize an empty call log."""
        self.calls = []

    async def update_all_dependencies(
        self,
        old_entity_id: str,
        new_entity_id: str,
        cached_states: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Record one dependency update call."""
        self.calls.append((old_entity_id, new_entity_id, cached_states))
        return {"total_success": 1, "total_failed": 0}


class FakeLovelace:
    """Record dashboard update calls and expose a YAML warning."""

    def __init__(self) -> None:
        """Initialize an empty call log."""
        self.calls = []

    async def update_all_dashboards(self, old_entity_id: str, new_entity_id: str) -> List[str]:
        """Record a storage-dashboard update."""
        self.calls.append(("update", old_entity_id, new_entity_id))
        return ["default"]

    async def update_dashboard_renames(self, rename_pairs: List[Any]) -> List[str]:
        """Record one atomic storage-dashboard update."""
        self.calls.append(("update_batch", rename_pairs))
        return ["default"]

    async def scan_renames(self, rename_pairs: List[Any]) -> List[Dict[str, str]]:
        """Record a dashboard scan and return one manual YAML update."""
        self.calls.append(("scan", rename_pairs))
        old_entity_id, new_entity_id = rename_pairs[0]
        return [{"dashboard": "yaml", "old": old_entity_id, "new": new_entity_id}]


def test_updates_dependencies_and_dashboards() -> None:
    """One coordinated update covers configs, storage, and YAML reporting."""
    dependencies = FakeDependencies()
    lovelace = FakeLovelace()
    updater = ReferenceUpdater(dependencies, lovelace)
    states = [{"entity_id": "automation.example"}]

    result = asyncio.run(updater.update_all("sensor.old", "sensor.new", states))

    assert dependencies.calls == [("sensor.old", "sensor.new", states)]
    assert result["dependencies"]["total_success"] == 1
    assert result["dashboards"]["updated"] == ["default"]
    assert result["dashboards"]["manual"] == [{"dashboard": "yaml", "old": "sensor.old", "new": "sensor.new"}]
    assert lovelace.calls == [
        ("update_batch", [("sensor.old", "sensor.new")]),
        ("scan", [("sensor.old", "sensor.new")]),
    ]
