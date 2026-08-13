"""Shared timeout policy for Home Assistant HTTP requests."""

import aiohttp


HA_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)


def ha_client_session() -> aiohttp.ClientSession:
    """Create a bounded Home Assistant HTTP session."""
    return aiohttp.ClientSession(timeout=HA_HTTP_TIMEOUT)
