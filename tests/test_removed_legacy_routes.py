"""The current UI uses stateless preview and queued execution endpoints."""

import web_ui


def test_legacy_stateful_routes_are_not_exposed():
    rules = {rule.rule for rule in web_ui.app.url_map.iter_rules()}
    assert "/api/preview" not in rules
    assert "/api/execute" not in rules
    assert "/api/update_mapping" not in rules
    assert "/api/set_entity_override" not in rules
