from typing import Any

import httpx


class OKKClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        user_id: int = 1,
        timeout_seconds: float = 20.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.user_id = user_id
        self.timeout_seconds = timeout_seconds

    async def get_health(self) -> dict[str, Any]:
        return await self._get_absolute(self._root_base_url() + "/health")

    async def list_strategies(self) -> dict[str, Any]:
        return await self._get("/strategies/")

    async def get_strategy(self, strategy_id: int) -> dict[str, Any]:
        return await self._get(f"/strategies/{strategy_id}")

    async def get_strategy_stats(self, strategy_id: int) -> dict[str, Any]:
        return await self._get(f"/strategies/{strategy_id}/stats")

    async def get_strategy_risk(self, strategy_id: int) -> dict[str, Any]:
        return await self._get(f"/risk-control/check/{strategy_id}")

    async def get_balance(self) -> dict[str, Any]:
        return await self._get("/positions/balance")

    async def list_positions(self, inst_type: str = "SWAP") -> Any:
        return await self._get("/positions/list", params={"inst_type": inst_type})

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._get_absolute(f"{self.base_url}{path}", params=params)

    async def _get_absolute(self, url: str, params: dict[str, Any] | None = None) -> Any:
        headers = self._headers()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            return {
                "ok": False,
                "status_code": exc.response.status_code,
                "error": exc.response.text,
                "url": str(exc.request.url),
            }
        except httpx.RequestError as exc:
            return {
                "ok": False,
                "status_code": None,
                "error": str(exc),
                "url": str(exc.request.url) if exc.request else url,
            }

    def _headers(self) -> dict[str, str]:
        headers = {"X-OKK-User-ID": str(self.user_id)}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _root_base_url(self) -> str:
        if self.base_url.endswith("/api/v1"):
            return self.base_url[: -len("/api/v1")]
        return self.base_url
