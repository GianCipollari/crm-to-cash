"""A small HTTP client with client-side rate limiting and retries.

Used by both loaders. It spaces requests out (min_interval), retries on
429 and 5xx with exponential backoff, and honours the Retry-After header.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} on {url}: {body[:500]}")
        self.status = status
        self.body = body


class RateLimitedClient:
    def __init__(
        self,
        base_url: str,
        headers: dict[str, str],
        min_interval: float = 0.15,
        max_retries: int = 5,
        backoff_base: float = 1.0,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = headers
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.session = session or requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._last_call = -float("inf")
        self.calls = 0

    def _throttle(self) -> None:
        wait = self.min_interval - (self._clock() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = self._clock()

    def request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        headers = {**self.headers, **kwargs.pop("headers", {})}
        for attempt in range(self.max_retries + 1):
            self._throttle()
            self.calls += 1
            resp = self.session.request(method, url, headers=headers, timeout=30, **kwargs)
            if resp.status_code < 400:
                return resp.json() if resp.content else {}
            if resp.status_code in RETRY_STATUS and attempt < self.max_retries:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else self.backoff_base * 2 ** attempt
                log.warning("HTTP %s on %s, retry %d in %.1fs", resp.status_code, path, attempt + 1, delay)
                self._sleep(delay)
                continue
            raise ApiError(resp.status_code, resp.text, url)
        raise AssertionError("unreachable")
