#!/usr/bin/env python3
"""
Naming Override System - Speichert benutzerdefinierte Entity-Suffix-Mappings.

Schema Version History:
- v1: Original flat structure {entities: {}, devices: {}, areas: {}}
- v2: Added version field
- v3: Removed device and area overrides (use HA API directly)

Only entity suffix overrides are stored. Device and area names
come directly from the Home Assistant API.
"""

import json
import logging
from pathlib import Path
import threading
from typing import Any, Dict, Optional

from atomic_json import write_json_atomic

logger = logging.getLogger(__name__)

# Current schema version
SCHEMA_VERSION = 3


class NamingOverrides:
    """
    Manages persistent storage of user naming overrides.

    Only stores entity suffix overrides. Device and area names
    are sourced directly from Home Assistant.
    """

    def __init__(self, storage_path: str = "naming_overrides.json"):
        """
        Initialize the naming overrides manager.

        Args:
            storage_path: Path to the JSON storage file
        """
        self.storage_path = Path(storage_path)
        self._lock = threading.RLock()
        # Ensure directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load_data()
        self._migrate_if_needed()

    def _load_data(self) -> Dict[str, Any]:
        """Load stored overrides from file."""
        default_data = {"version": SCHEMA_VERSION, "entities": {}}

        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
                    # Ensure entities key exists
                    if "entities" not in existing_data:
                        existing_data["entities"] = {}
                    return existing_data
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error loading overrides: {e}")

        return default_data

    def _migrate_if_needed(self) -> None:
        """Migrate data from older schema versions if needed."""
        current_version = self.data.get("version", 1)

        if current_version < SCHEMA_VERSION:
            logger.info(f"Migrating naming overrides from v{current_version} to v{SCHEMA_VERSION}")
            self._migrate_to_v3()
            self.data["version"] = SCHEMA_VERSION
            self._save_data()

    def _migrate_to_v3(self) -> None:
        """Migrate to v3 schema - remove device and area overrides."""
        # Remove device and area overrides (no longer used)
        if "devices" in self.data:
            del self.data["devices"]
            logger.info("Migration to v3: Removed device overrides")
        if "areas" in self.data:
            del self.data["areas"]
            logger.info("Migration to v3: Removed area overrides")

    def _save_data(self) -> None:
        """Persist overrides atomically and surface write failures to callers."""
        write_json_atomic(self.storage_path, self.data)
        logger.info("Saved %d entity overrides", len(self.data["entities"]))

    # === Entity Overrides ===

    def set_entity_override(self, registry_id: str, name: str, type_override: Optional[str] = None) -> None:
        """Setze Entity Name Override"""
        with self._lock:
            entities = dict(self.data.get("entities", {}))
            entry = {"name": name}
            if type_override:
                entry["type"] = type_override
            entities[registry_id] = entry
            candidate = {**self.data, "entities": entities}
            write_json_atomic(self.storage_path, candidate)
            self.data = candidate
        logger.info(f"Entity override gesetzt: {registry_id} -> {name}")

    def get_entity_override(self, registry_id: str) -> Optional[Dict[str, str]]:
        """Hole Entity Override"""
        return self.data.get("entities", {}).get(registry_id)

    def remove_entity_override(self, registry_id: str) -> None:
        """Entferne Entity Override"""
        with self._lock:
            if registry_id not in self.data.get("entities", {}):
                return
            entities = dict(self.data["entities"])
            del entities[registry_id]
            candidate = {**self.data, "entities": entities}
            write_json_atomic(self.storage_path, candidate)
            self.data = candidate
        logger.info(f"Entity override entfernt: {registry_id}")

    # === Bulk Operations ===

    def get_all_entity_overrides(self) -> Dict[str, Dict[str, str]]:
        """Hole alle Entity Overrides"""
        return self.data.get("entities", {}).copy()

    def clear_all(self) -> None:
        """Clear all overrides while preserving schema version."""
        candidate = {"version": SCHEMA_VERSION, "entities": {}}
        with self._lock:
            write_json_atomic(self.storage_path, candidate)
            self.data = candidate
        logger.info("All overrides cleared")

    # === Statistics ===

    def get_stats(self) -> Dict[str, int]:
        """Get statistics about stored overrides."""
        return {
            "version": self.data.get("version", 1),
            "entity_overrides": len(self.data.get("entities", {})),
        }

    def has_any_overrides(self) -> bool:
        """Check if any overrides are stored."""
        return bool(self.data.get("entities"))
