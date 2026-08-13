"""Access policy for Home Assistant ingress and direct HTTP clients."""

from dataclasses import dataclass


DIRECT_ACCESS_DISABLED = "disabled"
DIRECT_ACCESS_TOKEN = "token"
DIRECT_ACCESS_TRUSTED = "trusted"
DIRECT_ACCESS_MODES = frozenset(
    {DIRECT_ACCESS_DISABLED, DIRECT_ACCESS_TOKEN, DIRECT_ACCESS_TRUSTED}
)


@dataclass(frozen=True)
class AccessDecision:
    """Result of evaluating one direct API request."""

    allowed: bool
    status: int | None = None


def normalize_direct_access_mode(value: str | None) -> str:
    """Return a supported direct-access mode, defaulting safely to disabled."""
    mode = (value or DIRECT_ACCESS_DISABLED).strip().lower()
    return mode if mode in DIRECT_ACCESS_MODES else DIRECT_ACCESS_DISABLED


def authorize_direct_api(
    *,
    mode: str | None,
    path: str,
    token_configured: bool,
    token_valid: bool,
) -> AccessDecision:
    """Authorize a non-ingress API request.

    ``trusted`` is an explicit opt-in for local development networks. ``token``
    permits every API operation with a valid bearer token, except managing that
    token itself. ``disabled`` is the production-safe default.
    """
    mode = normalize_direct_access_mode(mode)
    if mode == DIRECT_ACCESS_TRUSTED:
        return AccessDecision(True)
    if mode == DIRECT_ACCESS_DISABLED:
        return AccessDecision(False, 403)
    if path == "/api/api_token":
        return AccessDecision(False, 403)
    if not token_configured or not token_valid:
        return AccessDecision(False, 401)
    return AccessDecision(True)
