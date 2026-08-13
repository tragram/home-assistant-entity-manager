"""Tests for ingress trust and explicit direct-access modes."""

import pytest

import web_ui

INGRESS_IP = "172.30.32.2"  # inside the Supervisor network
DIRECT_IP = "192.168.1.50"  # a LAN/host address (not Ingress)


@pytest.fixture
def store():
    """Reset the shared token store before and after each test."""
    s = web_ui.renamer_state["api_token_store"]
    s.revoke()
    yield s
    s.revoke()


@pytest.fixture
def client():
    web_ui.app.config["TESTING"] = True
    return web_ui.app.test_client()


def _req(client, path, ip, token=None, method="GET"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.open(path, method=method, headers=headers, environ_overrides={"REMOTE_ADDR": ip})


def test_disabled_mode_rejects_direct_lookup_without_token(client, store, monkeypatch):
    monkeypatch.setenv("DIRECT_ACCESS_MODE", "disabled")
    resp = _req(client, "/api/rename_log?entity_id=light.x", DIRECT_IP)
    assert resp.status_code == 403


def test_disabled_mode_rejects_direct_write_without_token(client, store, monkeypatch):
    monkeypatch.setenv("DIRECT_ACCESS_MODE", "disabled")
    resp = _req(client, "/api/delete_entity", DIRECT_IP, method="POST")
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Token exists: Ingress is trusted
# --------------------------------------------------------------------------- #


def test_ingress_lookup_without_token_allowed(client, store, monkeypatch):
    monkeypatch.setenv("DIRECT_ACCESS_MODE", "disabled")
    store.generate()
    resp = _req(client, "/api/rename_log?entity_id=light.x", INGRESS_IP)
    assert resp.status_code == 200


def test_ingress_write_path_not_blocked_by_gate(client, store, monkeypatch):
    monkeypatch.setenv("DIRECT_ACCESS_MODE", "disabled")
    store.generate()
    resp = _req(client, "/api/rename_entity", INGRESS_IP, method="POST")
    assert resp.status_code != 403


def test_ingress_token_management_allowed(client, store, monkeypatch):
    monkeypatch.setenv("DIRECT_ACCESS_MODE", "disabled")
    store.generate()
    resp = _req(client, "/api/api_token", INGRESS_IP)
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Token mode permits authenticated API operations
# --------------------------------------------------------------------------- #


def test_direct_lookup_with_valid_token_allowed(client, store, monkeypatch):
    monkeypatch.setenv("DIRECT_ACCESS_MODE", "token")
    token = store.generate()
    resp = _req(client, "/api/rename_log?entity_id=light.x", DIRECT_IP, token=token)
    assert resp.status_code == 200


def test_direct_lookup_with_wrong_token_rejected(client, store, monkeypatch):
    monkeypatch.setenv("DIRECT_ACCESS_MODE", "token")
    store.generate()
    resp = _req(client, "/api/rename_log?entity_id=light.x", DIRECT_IP, token="em_wrong")
    assert resp.status_code == 401


def test_direct_lookup_without_token_rejected(client, store, monkeypatch):
    monkeypatch.setenv("DIRECT_ACCESS_MODE", "token")
    store.generate()
    resp = _req(client, "/api/rename_log?entity_id=light.x", DIRECT_IP)
    assert resp.status_code == 401


def test_direct_token_mode_allows_authenticated_write(client, store, monkeypatch):
    monkeypatch.setenv("DIRECT_ACCESS_MODE", "token")
    token = store.generate()
    resp = _req(client, "/api/rename_entity", DIRECT_IP, token=token, method="POST")
    assert resp.status_code not in (401, 403)


def test_direct_token_management_forbidden_even_with_token(client, store, monkeypatch):
    monkeypatch.setenv("DIRECT_ACCESS_MODE", "token")
    # Generating/revoking tokens must stay Ingress-only.
    token = store.generate()
    resp = _req(client, "/api/api_token", DIRECT_IP, token=token, method="POST")
    assert resp.status_code == 403


def test_trusted_mode_allows_direct_write(client, store, monkeypatch):
    monkeypatch.setenv("DIRECT_ACCESS_MODE", "trusted")
    resp = _req(client, "/api/rename_entity", DIRECT_IP, method="POST")
    assert resp.status_code not in (401, 403)


def test_non_api_path_not_gated(client, store, monkeypatch):
    monkeypatch.setenv("DIRECT_ACCESS_MODE", "disabled")
    store.generate()
    resp = _req(client, "/", DIRECT_IP)
    assert resp.status_code != 403
