"""Update entity references in Home Assistant scenes, scripts, and automations."""

import logging
from typing import Any, Dict, List, Optional

import aiohttp

from entity_ref_utils import replace_entity_in_obj

logger = logging.getLogger(__name__)


class DependencyUpdater:
    """Read and update Home Assistant configuration through its REST API."""

    def __init__(self, base_url: str, token: str) -> None:
        """Initialize the updater for one Home Assistant instance."""
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def get_states(self) -> List[Dict[str, Any]]:
        """Return all current Home Assistant states."""
        url = f"{self.base_url}/api/states"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                if response.status != 200:
                    raise RuntimeError(f"Failed to fetch Home Assistant states: HTTP {response.status}")
                return await response.json()

    async def _get_config(self, kind: str, config_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one editable scene, script, or automation configuration."""
        url = f"{self.base_url}/api/config/{kind}/config/{config_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                if response.status == 200:
                    return await response.json()
                logger.debug("Could not fetch %s %s: HTTP %s", kind, config_id, response.status)
                return None

    async def _save_config(self, kind: str, config_id: str, config: Dict[str, Any]) -> bool:
        """Save one editable scene, script, or automation configuration."""
        url = f"{self.base_url}/api/config/{kind}/config/{config_id}"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, json=config) as response:
                if response.status != 200:
                    logger.error("Failed to update %s %s: HTTP %s", kind, config_id, response.status)
                    return False
                result = await response.json()
                return result.get("result") == "ok"

    async def get_scene_config(self, scene_numeric_id: str) -> Optional[Dict[str, Any]]:
        """Return an editable scene configuration, if available."""
        return await self._get_config("scene", scene_numeric_id)

    async def update_scene_config(self, scene_numeric_id: str, config: Dict[str, Any]) -> bool:
        """Save an editable scene configuration."""
        return await self._save_config("scene", scene_numeric_id, config)

    async def update_scene_entities(
        self,
        scene_id: str,
        scene_numeric_id: str,
        old_entity_id: str,
        new_entity_id: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Replace an entity reference in one scene."""
        config = config if config is not None else await self.get_scene_config(scene_numeric_id)
        if config is None or not replace_entity_in_obj(config, old_entity_id, new_entity_id):
            return False

        logger.info("Updating scene %s: %s -> %s", scene_id, old_entity_id, new_entity_id)
        return await self.update_scene_config(scene_numeric_id, config)

    async def get_script_config(self, script_id: str) -> Optional[Dict[str, Any]]:
        """Return an editable script configuration, if available."""
        return await self._get_config("script", script_id.removeprefix("script."))

    async def update_script_config(self, script_id: str, config: Dict[str, Any]) -> bool:
        """Save an editable script configuration."""
        return await self._save_config("script", script_id.removeprefix("script."), config)

    def replace_entity_in_dict(self, data: Any, old_entity_id: str, new_entity_id: str) -> bool:
        """Replace entity references recursively in a configuration object."""
        return replace_entity_in_obj(data, old_entity_id, new_entity_id)

    async def update_script_entities(
        self,
        script_id: str,
        old_entity_id: str,
        new_entity_id: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Replace an entity reference in one script."""
        config = config if config is not None else await self.get_script_config(script_id)
        if config is None or not self.replace_entity_in_dict(config, old_entity_id, new_entity_id):
            return False

        logger.info("Updating script %s: %s -> %s", script_id, old_entity_id, new_entity_id)
        return await self.update_script_config(script_id, config)

    async def get_automation_config(self, automation_numeric_id: str) -> Optional[Dict[str, Any]]:
        """Return an editable automation configuration, if available."""
        return await self._get_config("automation", automation_numeric_id)

    async def update_automation_config(self, automation_numeric_id: str, config: Dict[str, Any]) -> bool:
        """Save an editable automation configuration."""
        return await self._save_config("automation", automation_numeric_id, config)

    async def update_automation_entities(
        self,
        automation_id: str,
        automation_numeric_id: str,
        old_entity_id: str,
        new_entity_id: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Replace an entity reference in one automation."""
        config = config if config is not None else await self.get_automation_config(automation_numeric_id)
        if config is None or not self.replace_entity_in_dict(config, old_entity_id, new_entity_id):
            return False

        logger.info("Updating automation %s: %s -> %s", automation_id, old_entity_id, new_entity_id)
        return await self.update_automation_config(automation_numeric_id, config)

    @staticmethod
    def _new_results() -> Dict[str, Any]:
        """Create an empty reference-update result."""
        return {
            "scenes": {"success": [], "failed": []},
            "scripts": {"success": [], "failed": []},
            "automations": {"success": [], "failed": []},
            "total_success": 0,
            "total_failed": 0,
        }

    @staticmethod
    def _record_result(results: Dict[str, Any], kind: str, entity_id: str, success: bool) -> None:
        """Record the outcome of one configuration update."""
        outcome = "success" if success else "failed"
        results[kind][outcome].append(entity_id)
        results[f"total_{outcome}"] += 1

    async def update_all_dependencies(
        self,
        old_entity_id: str,
        new_entity_id: str,
        cached_states: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Replace an entity ID in every editable scene, script, and automation."""
        states = cached_states if cached_states is not None else await self.get_states()
        results = self._new_results()

        for state in states:
            entity_id = state.get("entity_id", "")
            attributes = state.get("attributes", {})

            if entity_id.startswith("scene."):
                numeric_id = attributes.get("id")
                if not numeric_id:
                    continue
                config = await self.get_scene_config(numeric_id)
                if config is not None and replace_entity_in_obj(config, old_entity_id, new_entity_id):
                    success = await self.update_scene_config(numeric_id, config)
                    self._record_result(results, "scenes", entity_id, success)

            elif entity_id.startswith("script."):
                config = await self.get_script_config(entity_id)
                if config is not None and replace_entity_in_obj(config, old_entity_id, new_entity_id):
                    success = await self.update_script_config(entity_id, config)
                    self._record_result(results, "scripts", entity_id, success)

            elif entity_id.startswith("automation."):
                numeric_id = attributes.get("id")
                if not numeric_id:
                    continue
                config = await self.get_automation_config(numeric_id)
                if config is not None and replace_entity_in_obj(config, old_entity_id, new_entity_id):
                    success = await self.update_automation_config(numeric_id, config)
                    self._record_result(results, "automations", entity_id, success)

        return results
