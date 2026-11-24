"""A polite async HTTP client for crawling.

- bounded global concurrency
- a minimum delay between requests to the same host
- retries with exponential backoff on 429 / 5xx / network errors, honouring Retry-After
- robots.txt checks for generic page crawling (public JSON APIs are fetched as documented)
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


FAST_API_HOSTS = {
    "boards-api.greenhouse.io",
    "api.lever.co",
    "api.ashbyhq.com",
    "api.smartrecruiters.com",
    "hn.algolia.com",
}


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class PoliteClient:
    def __init__(
        self,
        concurrency: int | None = None,
        per_host_delay: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 3,
    ):
        s = get_settings()
        self._sem = asyncio.Semaphore(concurrency or s.crawl_concurrency)
        self._delay = s.crawl_per_host_delay_s if per_host_delay is None else per_host_delay
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._max_retries = max_retries
        self.user_agent = s.crawl_user_agent
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": self.user_agent, "Accept-Language": "en"},
            transport=transport,
        )

    async def __aenter__(self) -> PoliteClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _delay_for(self, host: str) -> float:
        # Documented public job APIs on big CDNs tolerate a faster pace than career pages.
        return min(self._delay, 0.25) if host in FAST_API_HOSTS else self._delay

    async def _wait_for_host(self, host: str) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            last = self._host_last.get(host, 0.0)
            wait = self._delay_for(host) - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._host_last[host] = time.monotonic()

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp: RobotFileParser | None = RobotFileParser()
            try:
                resp = await self._client.get(base + "/robots.txt", timeout=10)
                if resp.status_code >= 400:
                    rp = None  # no robots.txt: everything allowed
                else:
                    rp.parse(resp.text.splitlines())
            except httpx.HTTPError:
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    async def get(
        self, url: str, *, params=None, check_robots: bool = False, **kw
    ) -> httpx.Response:
        return await self.request("GET", url, params=params, check_robots=check_robots, **kw)

    async def post_json(self, url: str, payload: dict, **kw):
        resp = await self.request("POST", url, json=payload, **kw)
        try:
            return resp.json()
        except ValueError as e:
            raise FetchError(f"invalid JSON from {url}") from e

    async def request(
        self, method: str, url: str, *, params=None, check_robots: bool = False, **kw
    ) -> httpx.Response:
        if check_robots and not await self.allowed(url):
            raise FetchError(f"disallowed by robots.txt: {url}", status=None)
        host = urlsplit(url).netloc
        attempt = 0
        while True:
            attempt += 1
            async with self._sem:
                await self._wait_for_host(host)
                try:
                    resp = await self._client.request(method, url, params=params, **kw)
                except httpx.HTTPError as e:
                    if attempt > self._max_retries:
                        raise FetchError(f"{type(e).__name__}: {e}") from e
                    await asyncio.sleep(self._backoff(attempt))
                    continue
            if resp.status_code in RETRY_STATUS and attempt <= self._max_retries:
                retry_after = resp.headers.get("Retry-After", "")
                wait = max(
                    float(retry_after) if retry_after.isdigit() else 0.0, self._backoff(attempt)
                )
                log.info("retrying %s after %.1fs (status %s)", url, wait, resp.status_code)
                await asyncio.sleep(min(wait, 60))
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code} for {url}", status=resp.status_code)
            return resp

    async def get_json(self, url: str, **kw):
        resp = await self.get(url, **kw)
        try:
            return resp.json()
        except ValueError as e:
            raise FetchError(f"invalid JSON from {url}") from e

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2**attempt, 30) + random.uniform(0, 0.5)
