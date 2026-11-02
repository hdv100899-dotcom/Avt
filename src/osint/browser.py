"""Render pages in a headless browser through Crawl4AI, for sites that need JavaScript.

Crawl4AI is asyncio-based and the collector is threaded, so one dedicated thread owns an event
loop and a single browser; any thread can submit a render and wait for it. Concurrency is capped,
and robots.txt is honoured unless a source opts out.
"""

import asyncio
import threading
from dataclasses import dataclass

from osint.config import browser_cdp_url, user_agent


@dataclass
class RenderedPage:
    url: str
    status: int | None
    html: str
    error: str | None = None


class BrowserUnavailable(RuntimeError):
    pass


class BrowserFetcher:
    def __init__(
        self, cdp_url: str | None = None, concurrency: int = 3, timeout_s: float = 45
    ) -> None:
        self._cdp_url = cdp_url if cdp_url is not None else browser_cdp_url()
        self._concurrency = concurrency
        self._timeout_s = timeout_s
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._crawler = None
        self._slots: asyncio.Semaphore | None = None

    def render(self, url: str, *, wait_for: str | None = None, respect_robots: bool = True):
        """Load ``url`` in the browser and return the rendered HTML. Never raises on page errors."""
        loop = self._ensure_started()
        future = asyncio.run_coroutine_threadsafe(self._render(url, wait_for, respect_robots), loop)
        try:
            return future.result(timeout=self._timeout_s + 15)
        except TimeoutError:
            future.cancel()
            return RenderedPage(url, None, "", f"timed out after {self._timeout_s:.0f}s")

    def close(self) -> None:
        with self._lock:
            loop, thread = self._loop, self._thread
            self._loop = self._thread = None
        if loop is None:
            return
        if self._crawler is not None:
            asyncio.run_coroutine_threadsafe(self._crawler.close(), loop).result(timeout=30)
            self._crawler = None
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=10)

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None:
                return self._loop
            loop = asyncio.new_event_loop()
            ready = threading.Event()

            def run() -> None:
                asyncio.set_event_loop(loop)
                loop.call_soon(ready.set)
                loop.run_forever()

            thread = threading.Thread(target=run, name="browser-loop", daemon=True)
            thread.start()
            ready.wait()
            try:
                asyncio.run_coroutine_threadsafe(self._start(), loop).result(timeout=120)
            except Exception as exc:
                loop.call_soon_threadsafe(loop.stop)
                raise BrowserUnavailable(f"{type(exc).__name__}: {exc}") from exc
            self._loop, self._thread = loop, thread
            return loop

    async def _start(self) -> None:
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig
        except ImportError as exc:
            raise BrowserUnavailable("crawl4ai is not installed: pip install '.[crawl]'") from exc
        config = BrowserConfig(
            headless=True, verbose=False, user_agent=user_agent(), cdp_url=self._cdp_url
        )
        self._crawler = AsyncWebCrawler(config=config)
        await self._crawler.start()
        self._slots = asyncio.Semaphore(self._concurrency)

    async def _render(self, url: str, wait_for: str | None, respect_robots: bool) -> RenderedPage:
        from crawl4ai import CacheMode, CrawlerRunConfig

        run = CrawlerRunConfig(
            wait_for=wait_for,
            check_robots_txt=respect_robots,
            page_timeout=int(self._timeout_s * 1000),
            cache_mode=CacheMode.BYPASS,
        )
        async with self._slots:
            try:
                result = await self._crawler.arun(url, config=run)
            except Exception as exc:
                return RenderedPage(url, None, "", f"{type(exc).__name__}: {exc}")
        if not result.success:
            return RenderedPage(
                url, result.status_code, "", result.error_message or "render failed"
            )
        return RenderedPage(result.redirected_url or url, result.status_code, result.html or "")
