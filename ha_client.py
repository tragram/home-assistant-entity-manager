import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from ha_http import ha_client_session

logger = logging.getLogger(__name__)


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.session = None

    async def __aenter__(self):
        self.session = ha_client_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.session:
            await self.session.close()

    async def connect(self):
        if not self.session:
            self.session = ha_client_session()

    async def disconnect(self):
        if self.session:
            await self.session.close()
            self.session = None

    @asynccontextmanager
    async def _session(self):
        """Yield a connected session, or a request-scoped fallback.

        Flask handlers use separate event loops, so the shared client normally
        uses request-scoped sessions. Callers doing several operations on one
        loop can use ``async with client`` to reuse a connection safely.
        """
        if self.session is not None and not self.session.closed:
            yield self.session
            return
        async with ha_client_session() as session:
            yield session

    async def get_states(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/api/states"
        async with self._session() as session:
            async with session.get(url, headers=self.headers) as response:
                response.raise_for_status()
                return await response.json()

    async def get_entity(self, entity_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/api/states/{entity_id}"
        async with self._session() as session:
            async with session.get(url, headers=self.headers) as response:
                response.raise_for_status()
                return await response.json()

    async def update_entity(
        self, entity_id: str, new_entity_id: str = None, friendly_name: str = None
    ) -> Dict[str, Any]:
        # Entity registry updates must be done via WebSocket
        # This function is a placeholder for the integration
        raise NotImplementedError("Entity registry updates require WebSocket connection")

    async def call_service(self, domain: str, service: str, data: Dict = None) -> Any:
        url = f"{self.base_url}/api/services/{domain}/{service}"
        async with self._session() as session:
            async with session.post(url, headers=self.headers, json=data or {}) as response:
                response.raise_for_status()
                return await response.json()

    async def get_config(self) -> Dict[str, Any]:
        url = f"{self.base_url}/api/config"
        async with self._session() as session:
            async with session.get(url, headers=self.headers) as response:
                response.raise_for_status()
                return await response.json()

    async def check_api_access(self) -> bool:
        try:
            url = f"{self.base_url}/api/"
            async with self._session() as session:
                async with session.get(url, headers=self.headers) as response:
                    data = await response.json()
                    return data.get("message") == "API running."
        except Exception as e:
            logger.error(f"API access check failed: {e}")
            return False
