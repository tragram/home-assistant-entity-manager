"""Update entity references in Home Assistant configs and groups."""

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

    async def _request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> tuple[int, Any]:
        """Call one Home Assistant REST endpoint and return status plus JSON."""
        url = f"{self.base_url}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=self.headers, json=payload) as response:
                try:
                    body = await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    body = None
                return response.status, body

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

    async def get_group_config_entries(self) -> List[Dict[str, Any]]:
        """Return UI-created Group helper config entries."""
        status, entries = await self._request_json("GET", "/api/config/config_entries/entry?domain=group")
        if status != 200 or not isinstance(entries, list):
            logger.warning("Could not fetch Group helper configurations: HTTP %s", status)
            return []
        return entries

    async def start_group_options_flow(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Open a Group helper options form, including its saved values."""
        status, flow = await self._request_json(
            "POST",
            "/api/config/config_entries/options/flow",
            {"handler": entry_id},
        )
        if status != 200 or not isinstance(flow, dict) or not flow.get("flow_id"):
            logger.error("Could not start options flow for Group helper %s: HTTP %s", entry_id, status)
            return None
        return flow

    @staticmethod
    def group_options_from_flow(flow: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the saved values Home Assistant suggests in an options form."""
        options: Dict[str, Any] = {}
        for field in flow.get("data_schema", []):
            if not isinstance(field, dict) or not field.get("name"):
                continue
            if "default" in field:
                options[field["name"]] = field["default"]
            elif "suggested_value" in field:
                options[field["name"]] = field["suggested_value"]
            elif "value" in field:
                options[field["name"]] = field["value"]
            elif isinstance(field.get("description"), dict) and "suggested_value" in field["description"]:
                options[field["name"]] = field["description"]["suggested_value"]
        return options

    async def abort_group_options_flow(self, flow_id: str) -> None:
        """Discard an options flow that did not need changes."""
        await self._request_json("DELETE", f"/api/config/config_entries/options/flow/{flow_id}")

    async def update_group_config_entry(
        self,
        entry: Dict[str, Any],
        flow: Dict[str, Any],
        options: Dict[str, Any],
        members: List[str],
    ) -> bool:
        """Update a UI-created Group helper through its supported options flow."""
        entry_id = entry.get("entry_id")
        if not entry_id or not isinstance(options, dict):
            return False

        # Submit every field exposed by the current form so future Home
        # Assistant Group options are preserved without a code update.
        field_names = {
            field.get("name")
            for field in flow.get("data_schema", [])
            if isinstance(field, dict) and field.get("name")
        }
        user_input = {key: value for key, value in options.items() if key in field_names and key != "entities"}
        user_input["entities"] = members
        status, result = await self._request_json(
            "POST",
            f"/api/config/config_entries/options/flow/{flow['flow_id']}",
            user_input,
        )
        success = status == 200 and isinstance(result, dict) and result.get("type") == "create_entry"
        if not success:
            logger.error("Could not save Group helper %s: HTTP %s (%s)", entry_id, status, result)
        return success

    async def update_legacy_group(self, state: Dict[str, Any], members: List[str]) -> bool:
        """Update an old-style ``group.*`` entity through ``group.set``."""
        entity_id = state.get("entity_id", "")
        attributes = state.get("attributes", {})
        payload: Dict[str, Any] = {
            "object_id": entity_id.removeprefix("group."),
            "entities": members,
        }
        for source, target in (("friendly_name", "name"), ("icon", "icon"), ("all", "all")):
            if source in attributes:
                payload[target] = attributes[source]
        status, _ = await self._request_json("POST", "/api/services/group/set", payload)
        if status != 200:
            logger.error("Could not update legacy group %s: HTTP %s", entity_id, status)
        return status == 200

    async def update_group_dependencies(
        self,
        old_entity_id: str,
        new_entity_id: str,
        states: List[Dict[str, Any]],
        results: Dict[str, Any],
    ) -> None:
        """Replace one member in UI helpers and legacy groups."""
        entries = await self.get_group_config_entries()
        for entry in entries:
            entry_id = entry.get("entry_id")
            if not entry_id or not (flow := await self.start_group_options_flow(entry_id)):
                continue
            options = self.group_options_from_flow(flow)
            members = options.get("entities")
            if not isinstance(members, list) or old_entity_id not in members:
                await self.abort_group_options_flow(flow["flow_id"])
                continue
            updated_members = [new_entity_id if member == old_entity_id else member for member in members]
            success = await self.update_group_config_entry(entry, flow, options, updated_members)
            self._record_result(results, "groups", entry.get("title") or entry.get("entry_id", "group"), success)

        for state in states:
            entity_id = state.get("entity_id", "")
            members = state.get("attributes", {}).get("entity_id")
            if not entity_id.startswith("group.") or not isinstance(members, list) or old_entity_id not in members:
                continue
            updated_members = [new_entity_id if member == old_entity_id else member for member in members]
            success = await self.update_legacy_group(state, updated_members)
            self._record_result(results, "groups", entity_id, success)
            if success:
                # Device batch renames reuse the same state snapshot. Keep it
                # current so a later member rename cannot restore an old ID.
                state["attributes"]["entity_id"] = updated_members

    @staticmethod
    def _new_results() -> Dict[str, Any]:
        """Create an empty reference-update result."""
        return {
            "scenes": {"success": [], "failed": []},
            "scripts": {"success": [], "failed": []},
            "automations": {"success": [], "failed": []},
            "groups": {"success": [], "failed": []},
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
        """Replace an entity ID in every editable config and group."""
        states = cached_states if cached_states is not None else await self.get_states()
        results = self._new_results()

        try:
            await self.update_group_dependencies(old_entity_id, new_entity_id, states, results)
        except Exception:  # noqa: BLE001 - other dependency types must still update
            logger.exception("Failed to update group references for %s -> %s", old_entity_id, new_entity_id)

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
