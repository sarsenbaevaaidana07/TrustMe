"""
jira_client.py — клиент Jira с circuit breaker.
Fix: Basic Auth (email:token) вместо Bearer токена.
"""

import httpx
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
import base64


class JiraClient:
    CIRCUIT_OPEN_DURATION = timedelta(minutes=5)
    MAX_FAILURES = 5

    def __init__(self, base_url: str, token: str, email: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.email = email or os.environ.get("JIRA_EMAIL", "")
        self._failure_count = 0
        self._circuit_open_until: Optional[datetime] = None

        # Basic Auth: base64(email:token)
        credentials = f"{self.email}:{self.token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        self._auth_header = f"Basic {encoded}"

    def _open_circuit(self) -> None:
        self._circuit_open_until = datetime.now(timezone.utc) + self.CIRCUIT_OPEN_DURATION

    def _is_circuit_open(self) -> bool:
        if self._circuit_open_until is None:
            return False
        if datetime.now(timezone.utc) < self._circuit_open_until:
            return True
        self._circuit_open_until = None
        self._failure_count = 0
        return False

    def _record_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self.MAX_FAILURES:
            self._open_circuit()

    def _record_success(self) -> None:
        self._failure_count = 0
        self._circuit_open_until = None

    async def create_issue(self, payload: dict) -> dict:
        if self._is_circuit_open():
            reopen_at = self._circuit_open_until.strftime("%H:%M:%S UTC")
            raise RuntimeError(
                f"Jira circuit breaker открыт до {reopen_at}. "
                "Повторите запрос позже."
            )

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/rest/api/3/issue",
                    json=payload,
                    headers={
                        "Authorization": self._auth_header,
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                self._record_success()
                return resp.json()
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                self._record_failure()
                raise RuntimeError(f"Jira API error: {exc}") from exc

    async def search_issues(self, jql: str, max_results: int = 50) -> list[dict]:
        if self._is_circuit_open():
            return []

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/rest/api/3/search",
                    params={"jql": jql, "maxResults": max_results},
                    headers={"Authorization": self._auth_header},
                )
                resp.raise_for_status()
                self._record_success()
                return resp.json().get("issues", [])
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                self._record_failure()
                raise RuntimeError(f"Jira search error: {exc}") from exc
