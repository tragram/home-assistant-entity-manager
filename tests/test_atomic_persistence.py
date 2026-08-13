import json

import pytest

import naming_overrides
import naming_templates
import type_mappings
from atomic_json import write_json_atomic
from naming_overrides import NamingOverrides
from naming_templates import NamingTemplates
from type_mappings import TypeMappings


def test_atomic_json_replaces_complete_document(tmp_path):
    path = tmp_path / "data.json"
    write_json_atomic(path, {"old": True})
    write_json_atomic(path, {"new": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    ("module", "factory", "mutate", "read"),
    [
        (
            naming_overrides,
            lambda path: NamingOverrides(str(path)),
            lambda store: store.set_entity_override("r1", "Name"),
            lambda store: store.get_entity_override("r1"),
        ),
        (
            naming_templates,
            lambda path: NamingTemplates(str(path)),
            lambda store: store.apply_preset("home_assistant"),
            lambda store: store.get_config()["preset"],
        ),
        (
            type_mappings,
            lambda path: TypeMappings(user_mappings_path=str(path)),
            lambda store: store.set_user_mapping("battery", "Custom"),
            lambda store: store.get_user_mapping("battery"),
        ),
    ],
)
def test_failed_write_does_not_mutate_memory(module, factory, mutate, read, tmp_path, monkeypatch):
    store = factory(tmp_path / "store.json")
    before = read(store)
    monkeypatch.setattr(module, "write_json_atomic", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk")))

    with pytest.raises(OSError, match="disk"):
        mutate(store)

    assert read(store) == before
