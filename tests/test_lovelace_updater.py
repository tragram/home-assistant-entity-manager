"""Tests for the Lovelace updater (storage rewrite, YAML scan) with a mock WebSocket."""

import asyncio
import copy

from lovelace_updater import LovelaceUpdater


class MockWS:
    """Minimal HA WebSocket mock implementing the lovelace/* commands."""

    def __init__(self, dashboards, configs, yaml_paths=None):
        self._dashboards = dashboards
        self._cfgs = configs
        self._yaml = set(yaml_paths or [])  # url_paths where save fails (yaml mode)
        self._id = 0
        self._queue = []
        self.save_calls = []

    async def _send_message(self, msg):
        self._id += 1
        t = msg["type"]
        if t == "lovelace/dashboards/list":
            self._queue.append({"id": self._id, "success": True, "result": self._dashboards})
        elif t == "lovelace/config":
            url_path = msg.get("url_path")
            if url_path is None and any(item.get("url_path") == "lovelace" for item in self._dashboards):
                url_path = "lovelace"
            cfg = self._cfgs.get(url_path)
            self._queue.append({"id": self._id, "success": True, "result": copy.deepcopy(cfg)})
        elif t == "lovelace/config/save":
            up = msg.get("url_path")
            self.save_calls.append(up)
            if up in self._yaml or up is None and None in self._yaml:
                self._queue.append({"id": self._id, "success": False, "error": "yaml mode"})
            else:
                self._cfgs[up] = msg["config"]
                self._queue.append({"id": self._id, "success": True})
        return self._id

    async def _receive_message(self):
        return self._queue.pop(0)


def _run(coro):
    return asyncio.run(coro)


def test_update_all_dashboards_storage_only():
    ws = MockWS(
        dashboards=[{"url_path": "storage1", "mode": "storage"}, {"url_path": "yaml1", "mode": "yaml"}],
        configs={
            None: {"cards": [{"entity": "sensor.old"}]},
            "storage1": {"cards": [{"entity": "sensor.old"}]},
            "yaml1": {"cards": [{"entity": "sensor.old"}]},
        },
    )
    lu = LovelaceUpdater(ws)
    changed = _run(lu.update_all_dashboards("sensor.old", "sensor.new"))
    # only storage-mode targets (default + storage1) are written; yaml1 is skipped
    assert "storage1" in changed
    assert "yaml1" not in changed


def test_update_dashboard_without_mode_metadata_and_embedded_reference():
    ws = MockWS(
        dashboards=[{"url_path": "custom-dashboard"}],
        configs={
            None: None,
            "custom-dashboard": {
                "cards": [{"type": "custom:button-card", "value": "return states['sensor.old'].state"}]
            },
        },
    )
    updater = LovelaceUpdater(ws)

    changed = _run(updater.update_all_dashboards("sensor.old", "sensor.new"))

    assert changed == ["custom-dashboard"]
    assert "sensor.new" in ws._cfgs["custom-dashboard"]["cards"][0]["value"]


def test_batch_renames_save_each_dashboard_once():
    """A multi-entity rename cannot overwrite an earlier dashboard change."""
    ws = MockWS(
        dashboards=[{"url_path": "lovelace", "mode": "storage"}],
        configs={"lovelace": {"cards": [{"entities": ["sensor.old_energy", "sensor.old_voltage"]}]}},
    )
    updater = LovelaceUpdater(ws)

    changed = _run(
        updater.update_dashboard_renames(
            [
                ("sensor.old_energy", "sensor.new_energy"),
                ("sensor.old_voltage", "sensor.new_voltage"),
            ]
        )
    )

    assert changed == ["lovelace"]
    assert ws.save_calls == ["lovelace"]
    assert ws._cfgs["lovelace"]["cards"][0]["entities"] == ["sensor.new_energy", "sensor.new_voltage"]


def test_scan_renames_finds_yaml_only():
    # storage already rewritten -> only yaml dashboards still contain the old id
    ws = MockWS(
        dashboards=[{"url_path": "storage1", "mode": "storage"}, {"url_path": "yaml1", "mode": "yaml"}],
        configs={
            None: {"cards": [{"entity": "sensor.new"}]},  # already updated
            "storage1": {"cards": [{"entity": "sensor.new"}]},  # already updated
            "yaml1": {"cards": [{"entity": "sensor.old"}]},  # still old (not writable)
        },
    )
    lu = LovelaceUpdater(ws)
    manual = _run(lu.scan_renames([("sensor.old", "sensor.new")]))
    dboards = sorted(m["dashboard"] for m in manual)
    assert dboards == ["yaml1"]


def test_get_referenced_entity_ids_includes_yaml():
    ws = MockWS(
        dashboards=[{"url_path": "yaml1", "mode": "yaml"}],
        configs={
            None: {"cards": [{"entity": "sensor.a"}]},
            "yaml1": {"cards": [{"entity": "sensor.b"}]},
        },
    )
    lu = LovelaceUpdater(ws)
    refs = _run(lu.get_referenced_entity_ids())
    assert {"sensor.a", "sensor.b"} <= refs
