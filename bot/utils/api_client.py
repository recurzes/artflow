from typing import Any

import aiohttp

from shared.config import settings


class APIClient:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._base_url = settings.api_base_url
        self._headers = {
            "X-Bot-Secret": settings.bot_secret,
            "Content-Type": "application/json"
        }

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    async def get(self, path: str, **kwargs) -> dict[str, Any]:
        async with self._session.get(
            self._url(path), headers=self._headers, **kwargs
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_any(self, path: str, **kwargs) -> Any:
        async with self._session.get(
            self._url(path),
            headers=self._headers,
                **kwargs
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_or_none(self, path: str, **kwargs) -> dict[str, Any] | None:
        async with self._session.get(
            self._url(path),
            headers=self._headers,
            **kwargs
        ) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            return await resp.json()

    async def post(self, path: str, json: dict | None = None, **kwargs) -> dict[str, Any]:
        async with self._session.post(
            self._url(path), headers=self._headers, json=json, **kwargs
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def patch(self, path: str, json: dict | None = None, **kwargs) -> dict[str, Any]:
        async with self._session.patch(
            self._url(path), headers=self._headers, json=json, **kwargs
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def delete(self, path: str, **kwargs) -> dict[str, Any]:
        async with self._session.delete(
            self._url(path), headers=self._headers, **kwargs
        ) as resp:
            resp.raise_for_status()
            return await resp.json()