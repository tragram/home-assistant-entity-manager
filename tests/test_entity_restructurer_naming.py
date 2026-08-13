"""Tests for applying naming templates to Home Assistant registry data."""

import pytest

from entity_restructurer import EntityRestructurer
from hierarchy_manager import HierarchyManager
from naming_overrides import NamingOverrides
from naming_templates import NamingTemplates


def test_hierarchy_preserves_explicit_blank_entity_name() -> None:
    """A blank HA override must not fall through to the native name or ID."""
    hierarchy = HierarchyManager()
    hierarchy.load_from_ha(
        areas={"bar": {"name": "Bar"}},
        devices={"audio": {"name": "Bar Audio", "area_id": "bar"}},
        entities={
            "media_player.bar_audio": {
                "id": "registry-1",
                "device_id": "audio",
                "name": "",
                "original_name": "Powernode Reproduktory Media",
                "has_entity_name": True,
            }
        },
    )

    entity = hierarchy.entities["registry-1"]
    assert entity.original_name == ""
    assert entity.base_name == ""


class FakeTypeMappings:
    """Small deterministic type-mapping test double."""

    @staticmethod
    def detect_integration(entity_id):
        return "example"

    @staticmethod
    def get_translation(type_key, language, integration, domain):
        return (type_key or domain).replace("_", " ").title()


@pytest.fixture
def restructurer(tmp_path):
    result = EntityRestructurer(
        client=object(),
        naming_overrides=NamingOverrides(str(tmp_path / "overrides.json")),
        type_mappings=FakeTypeMappings(),
        naming_templates=NamingTemplates(str(tmp_path / "templates.json")),
    )
    result.floors = {"ground": {"floor_id": "ground", "name": "Ground floor"}}
    result.areas = {
        "living_room": {
            "area_id": "living_room",
            "name": "Living room",
            "floor_id": "ground",
        }
    }
    result.devices = {
        "device-1": {
            "id": "device-1",
            "name": "Controller",
            "area_id": "living_room",
            "manufacturer": "Acme",
            "model": "Model 1",
        }
    }
    result.entities = {
        "sensor.existing_id": {
            "id": "registry-1",
            "entity_id": "sensor.existing_id",
            "device_id": "device-1",
            "platform": "example",
            "original_name": "Temperature",
            "original_device_class": "temperature",
            "has_entity_name": True,
        }
    }
    return result


@pytest.mark.parametrize(
    ("preset", "expected_id", "expected_entity_name", "expected_device_name"),
    [
        (
            "entity_manager",
            "sensor.living_room_controller_temperature",
            "Living room Controller Temperature",
            "Living room Controller",
        ),
        (
            "home_assistant",
            "sensor.living_room_controller_temperature",
            "Temperature",
            "Controller",
        ),
    ],
)
def test_presets_render_registry_context(
    restructurer,
    preset,
    expected_id,
    expected_entity_name,
    expected_device_name,
):
    restructurer.naming_templates.apply_preset(preset)

    assert restructurer.generate_new_entity_id("sensor.existing_id", {}) == (
        expected_id,
        expected_entity_name,
    )
    assert restructurer.generate_device_name("device-1") == expected_device_name


def test_device_rename_cascades_to_generated_entity_id_without_reset(restructurer):
    """Changing a device name normally replaces its component in entity IDs."""
    restructurer.naming_templates.apply_preset("home_assistant")
    preserved_suffix = restructurer.build_naming_context("sensor.existing_id", {})["entity"]
    restructurer.devices["device-1"]["name"] = "Thermostat"

    assert restructurer.generate_new_entity_id(
        "sensor.existing_id",
        {},
        preserved_suffix,
    ) == ("sensor.living_room_thermostat_temperature", "Temperature")


@pytest.mark.parametrize(
    ("domain", "original_name", "expected_suffix"),
    [
        ("event", "Left action", "left_action"),
        ("event", "Right action", "right_action"),
        ("button", "Restart", "restart"),
        ("update", "Firmware", "firmware"),
    ],
)
def test_home_assistant_preset_preserves_native_entity_names(
    restructurer,
    domain,
    original_name,
    expected_suffix,
):
    restructurer.naming_templates.apply_preset("home_assistant")
    entity_id = f"{domain}.existing_id"
    restructurer.entities = {
        entity_id: {
            "id": f"registry-{domain}-{expected_suffix}",
            "entity_id": entity_id,
            "device_id": "device-1",
            "original_name": original_name,
            "has_entity_name": True,
        }
    }

    assert restructurer.generate_new_entity_id(entity_id, {}) == (
        f"{domain}.living_room_controller_{expected_suffix}",
        original_name,
    )


@pytest.mark.parametrize(
    ("entity_id", "registry", "state", "expected"),
    [
        (
            "switch.old_main",
            {"device_id": "device-1", "original_name": None, "has_entity_name": True},
            {"attributes": {"friendly_name": "Controller"}},
            ("switch.living_room_controller", ""),
        ),
        (
            "binary_sensor.old_standalone",
            {"device_id": None, "original_name": "Everyone is home", "has_entity_name": True},
            {},
            ("binary_sensor.everyone_is_home", "Everyone is home"),
        ),
    ],
)
def test_home_assistant_special_entity_shapes(restructurer, entity_id, registry, state, expected):
    restructurer.naming_templates.apply_preset("home_assistant")
    restructurer.entities = {entity_id: {"id": "registry-special", "entity_id": entity_id, **registry}}

    assert restructurer.generate_new_entity_id(entity_id, state) == expected


def test_original_name_is_not_replaced_by_existing_composed_name(restructurer):
    restructurer.naming_templates.apply_preset("home_assistant")
    restructurer.entities["sensor.existing_id"]["name"] = "Living room Controller Sensor"

    assert restructurer.generate_new_entity_id("sensor.existing_id", {}) == (
        "sensor.living_room_controller_temperature",
        "Temperature",
    )


def test_native_entity_name_equal_to_device_name_is_empty_suffix(restructurer):
    """Resetting a main entity must not duplicate the device name forever."""
    restructurer.naming_templates.apply_preset("home_assistant")
    restructurer.devices["device-1"]["name"] = "Keyboard (device 5)"
    restructurer.entities = {
        "binary_sensor.old_keyboard": {
            "id": "registry-keyboard",
            "entity_id": "binary_sensor.old_keyboard",
            "device_id": "device-1",
            "original_name": "Keyboard (device 5)",
            "has_entity_name": True,
        }
    }

    assert restructurer.generate_new_entity_id("binary_sensor.old_keyboard", {}) == (
        "binary_sensor.living_room_keyboard_device_5",
        "",
    )


def test_legacy_main_entity_full_name_is_reduced_to_empty_suffix(restructurer):
    """An area plus device registry name must not be appended as a suffix."""
    restructurer.naming_templates.apply_preset("home_assistant")
    restructurer.areas["living_room"]["name"] = "VIP"
    restructurer.devices["device-1"]["name"] = "Bodovka L1"
    restructurer.entities = {
        "light.vip_bodovka_l1_vip_bodovka_l1": {
            "id": "registry-main-light",
            "entity_id": "light.vip_bodovka_l1_vip_bodovka_l1",
            "device_id": "device-1",
            "original_name": None,
            "name": "VIP Bodovka L1",
            "has_entity_name": True,
        }
    }

    assert restructurer.generate_new_entity_id("light.vip_bodovka_l1_vip_bodovka_l1", {}) == (
        "light.vip_bodovka_l1",
        "",
    )


def test_composed_state_name_is_reduced_to_entity_name(restructurer):
    restructurer.naming_templates.apply_preset("home_assistant")
    restructurer.entities["sensor.existing_id"].update({"original_name": None, "name": None})

    assert restructurer.generate_new_entity_id(
        "sensor.existing_id",
        {"attributes": {"friendly_name": "Living room Controller Temperature"}},
    ) == ("sensor.living_room_controller_temperature", "Temperature")


def test_device_class_is_last_resort_when_ha_provides_no_name(restructurer):
    restructurer.entities["sensor.existing_id"].update({"original_name": None, "name": None, "has_entity_name": False})

    context = restructurer.build_naming_context("sensor.existing_id", {})

    assert context["entity"] == "Temperature"


def test_main_entity_keeps_empty_name_without_state_data(restructurer):
    """An HA main entity must not gain a redundant domain suffix."""
    entity_id = "light.old_main"
    restructurer.naming_templates.apply_preset("home_assistant")
    restructurer.entities = {
        entity_id: {
            "id": "registry-main-light",
            "entity_id": entity_id,
            "device_id": "device-1",
            "original_name": None,
            "name": None,
            "has_entity_name": True,
        }
    }

    assert restructurer.generate_new_entity_id(entity_id, {}) == (
        "light.living_room_controller",
        "",
    )


def test_existing_object_id_preserves_suffix_without_native_name(restructurer):
    """Legacy entities retain their distinct object-ID suffixes."""
    entity_id = "sensor.living_room_controller_energy_consumed"
    restructurer.entities = {
        entity_id: {
            "id": "registry-energy",
            "entity_id": entity_id,
            "device_id": "device-1",
            "original_name": None,
            "name": None,
        }
    }

    context = restructurer.build_naming_context(
        entity_id,
        {"attributes": {"friendly_name": "Living room Controller"}},
    )

    assert context["entity"] == "Energy Consumed"


def test_custom_templates_can_use_floor_and_metadata(restructurer):
    restructurer.naming_templates.set_templates(
        {
            "device_name": "{floor} {manufacturer} {device}",
            "entity_name": "{area} {entity} ({model})",
            "entity_id": "{floor_id} {integration} {device} {entity}",
        }
    )

    assert restructurer.generate_new_entity_id("sensor.existing_id", {}) == (
        "sensor.ground_example_controller_temperature",
        "Living room Temperature (Model 1)",
    )
    assert restructurer.generate_device_name("device-1") == "Ground floor Acme Controller"


def test_entity_area_overrides_device_area(restructurer):
    restructurer.areas["office"] = {"area_id": "office", "name": "Office"}
    restructurer.entities["sensor.existing_id"]["area_id"] = "office"

    context = restructurer.build_naming_context("sensor.existing_id", {})

    assert (context["area_id"], context["area"]) == ("office", "Office")


class FakeRegistryWebSocket:
    """Return generic registry payloads using current HA identifier fields."""

    RESULTS = {
        "config/floor_registry/list": [{"id": "ground", "name": "Ground floor"}],
        "config/area_registry/list": [{"id": "living_room", "name": "Living room", "floor_id": "ground"}],
        "config/device_registry/list": [{"id": "device-1", "name": "Controller", "area_id": "living_room"}],
        "config/entity_registry/list": [
            {
                "id": "registry-1",
                "entity_id": "sensor.controller_temperature",
                "device_id": "device-1",
                "original_name": "Temperature",
            }
        ],
    }

    def __init__(self):
        self.message_id = 0
        self.responses = []

    async def _send_message(self, message):
        self.message_id += 1
        self.responses.append(
            {
                "id": self.message_id,
                "success": True,
                "result": self.RESULTS[message["type"]],
            }
        )
        return self.message_id

    async def _receive_message(self):
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_registry_loader_accepts_current_ha_identifier_fields(restructurer):
    await restructurer.load_structure(FakeRegistryWebSocket())

    context = restructurer.build_naming_context("sensor.controller_temperature", {})

    assert (context["floor"], context["area"]) == ("Ground floor", "Living room")
