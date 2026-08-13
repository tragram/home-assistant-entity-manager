"""Input-boundary regression tests."""

import web_ui


def test_names_are_not_html_encoded_before_persistence():
    assert web_ui.sanitize_name("Kid's Light & Audio") == "Kid's Light & Audio"


def test_entity_batch_is_normalized_and_preserves_blank_name():
    entities, error = web_ui._validate_entity_rename_batch(
        [{"old_id": "LIGHT.Old", "new_id": "light.new", "new_name": ""}]
    )

    assert error is None
    assert entities == [{"old_id": "light.old", "new_id": "light.new", "new_name": ""}]


def test_entity_batch_rejects_duplicate_sources():
    entities, error = web_ui._validate_entity_rename_batch(
        [
            {"old_id": "light.old", "new_id": "light.one", "new_name": "One"},
            {"old_id": "light.old", "new_id": "light.two", "new_name": "Two"},
        ]
    )

    assert entities == []
    assert "appears more than once" in error


def test_entity_batch_rejects_duplicate_targets():
    entities, error = web_ui._validate_entity_rename_batch(
        [
            {"old_id": "light.one", "new_id": "light.target", "new_name": "One"},
            {"old_id": "light.two", "new_id": "light.target", "new_name": "Two"},
        ]
    )

    assert entities == []
    assert "Target entity ID" in error
