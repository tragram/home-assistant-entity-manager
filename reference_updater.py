"""Coordinate entity reference updates across Home Assistant configuration."""

from typing import Any, Dict, List, Optional, Tuple

from dependency_updater import DependencyUpdater
from lovelace_updater import LovelaceUpdater


class ReferenceUpdater:
    """Update entity references in configuration and Lovelace dashboards."""

    def __init__(self, dependencies: DependencyUpdater, lovelace: LovelaceUpdater) -> None:
        """Initialize the updater with REST and WebSocket clients."""
        self.dependencies = dependencies
        self.lovelace = lovelace

    async def update_all(
        self,
        old_entity_id: str,
        new_entity_id: str,
        cached_states: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Replace one entity ID in editable HA configuration and dashboards."""
        dependencies = await self.dependencies.update_all_dependencies(
            old_entity_id,
            new_entity_id,
            cached_states,
        )
        dashboard_results = await self.update_dashboards([(old_entity_id, new_entity_id)])

        return {
            "dependencies": dependencies,
            "dashboards": dashboard_results,
        }

    async def update_dashboards(self, rename_pairs: List[Tuple[str, str]]) -> Dict[str, Any]:
        """Apply a complete rename batch to each dashboard atomically."""
        dashboards = await self.lovelace.update_dashboard_renames(rename_pairs)
        manual_dashboards = await self.lovelace.scan_renames(rename_pairs)
        return {"updated": dashboards, "manual": manual_dashboards}
