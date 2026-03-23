import asyncio
import time
import random
import sys
from typing import Optional, List
from dataclasses import dataclass, field
import httpx
from app.core.config import settings
from app.utils.logger import log

# Ensure asyncio event loop policy is set for Vercel
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@dataclass
class ProxyEntry:
    url: str
    failures: int = 0
    last_used: float = 0.0
    last_checked: float = 0.0
    response_time: float = 999.0
    is_alive: bool = True

    def mark_failed(self):
        self.failures += 1
        if self.failures >= settings.PROXY_MAX_FAILURES:
            self.is_alive = False
            log.warning(f"Proxy DEAD: {self.url}")

    def mark_success(self, response_time: float):
        self.failures = 0
        self.is_alive = True
        self.last_used = time.time()
        self.response_time = response_time


# Free proxy API sources
PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=anonymous",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
]

TEST_URL = "https://httpbin.org/ip"


class ProxyPoolManager:
    def __init__(self):
        self._pool: List[ProxyEntry] = []
        self._lock: Optional[asyncio.Lock] = None
        self._index = 0
        self._last_refreshed: Optional[float] = None
        self._requests_served = 0
        self._refresh_task: Optional[asyncio.Task] = None
        self._tor_rotate_task: Optional[asyncio.Task] = None
        self._initialized = False
    
    def _get_lock(self) -> asyncio.Lock:
        """Lazy initialize lock - avoids event loop issues on import"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ── Startup ──────────────────────────────────────────────────────────────

    async def start(self):
        """App startup pe call karo"""
        if self._initialized:
            return  # Already started
        
        log.info("🚀 Proxy Pool Manager starting...")
        try:
            await self.refresh_pool()
            self._initialized = True
        except Exception as e:
            log.error(f"Failed to refresh proxy pool on startup: {e}")
            self._initialized = False
            # Continue anyway - will use direct connection

        # Background auto-refresh task (don't await on Vercel)
        try:
            self._refresh_task = asyncio.create_task(self._auto_refresh_loop())
        except Exception as e:
            log.warning(f"Could not create auto-refresh task: {e}")

        if settings.USE_TOR:
            try:
                self._tor_rotate_task = asyncio.create_task(self._tor_rotate_loop())
                log.info("🧅 Tor rotation enabled")
            except Exception as e:
                log.warning(f"Could not setup Tor rotation: {e}")

    async def stop(self):
        """App shutdown pe call karo"""
        if self._refresh_task:
            self._refresh_task.cancel()
        if self._tor_rotate_task:
            self._tor_rotate_task.cancel()
        log.info("🛑 Proxy Pool Manager stopped")

    # ── Proxy Fetching ────────────────────────────────────────────────────────

    async def _fetch_from_source(self, source_url: str) -> List[str]:
        """Single source se proxies fetch karo"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.get(source_url)
                proxies = []
                for line in res.text.strip().splitlines():
                    line = line.strip()
                    if line and ":" in line:
                        proxies.append(f"http://{line}" if not line.startswith("http") else line)
                log.debug(f"Fetched {len(proxies)} proxies from {source_url[:60]}")
                return proxies
        except Exception as e:
            log.warning(f"Source failed {source_url[:60]}: {e}")
            return []

    async def refresh_pool(self):
        """Saare sources se proxies fetch + test karo"""
        log.info("🔄 Refreshing proxy pool...")

        all_proxies: List[str] = []

        # Sab sources se parallel fetch with timeout
        try:
            tasks = [self._fetch_from_source(src) for src in PROXY_SOURCES]
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=30.0  # 30 second timeout for all sources
            )

            for result in results:
                if isinstance(result, list):
                    all_proxies.extend(result)
        except asyncio.TimeoutError:
            log.warning("Proxy fetching timed out")
            all_proxies = []

        # Deduplicate
        all_proxies = list(set(all_proxies))
        log.info(f"📦 Total raw proxies: {len(all_proxies)}")

        # Test proxies (parallel, limited concurrency) with timeout
        alive = []
        if all_proxies:
            try:
                alive = await asyncio.wait_for(
                    self._test_proxies_batch(all_proxies),
                    timeout=60.0  # 60 second timeout for testing
                )
            except asyncio.TimeoutError:
                log.warning("Proxy testing timed out")

        async with self._get_lock():
            self._pool = alive
            self._last_refreshed = time.time()
            self._index = 0

        log.info(f"✅ Proxy pool ready: {len(alive)} alive proxies")

    async def _test_proxies_batch(self, proxy_urls: List[str], batch_size: int = 50) -> List[ProxyEntry]:
        """Proxies ko batch mein test karo"""
        alive = []
        semaphore = asyncio.Semaphore(batch_size)

        async def test_one(proxy_url: str) -> Optional[ProxyEntry]:
            async with semaphore:
                return await self._test_proxy(proxy_url)

        tasks = [test_one(p) for p in proxy_urls[:500]]  # max 500 test
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, ProxyEntry) and result.is_alive:
                alive.append(result)

        # Sort by response time
        alive.sort(key=lambda x: x.response_time)
        return alive

    async def _test_proxy(self, proxy_url: str) -> Optional[ProxyEntry]:
        """Single proxy test karo"""
        start = time.time()
        try:
            async with httpx.AsyncClient(
                proxies={"https://": proxy_url, "http://": proxy_url},
                timeout=settings.PROXY_TEST_TIMEOUT,
            ) as client:
                res = await client.get(TEST_URL)
                if res.status_code == 200:
                    rt = time.time() - start
                    entry = ProxyEntry(url=proxy_url)
                    entry.mark_success(rt)
                    return entry
        except Exception:
            pass
        return None

    # ── Proxy Getting ─────────────────────────────────────────────────────────

    def get_proxy(self) -> Optional[str]:
        """Next alive proxy do (round-robin)"""
        if settings.USE_TOR:
            return f"socks5://127.0.0.1:{settings.TOR_SOCKS_PORT}"

        # If no proxies and never initialized, don't log warning every time
        alive = [p for p in self._pool if p.is_alive]
        if not alive:
            if self._initialized:
                log.warning("⚠️ No alive proxies! Direct connection use ho raha hai")
            return None

        # Round robin
        proxy = alive[self._index % len(alive)]
        self._index += 1
        self._requests_served += 1
        proxy.last_used = time.time()
        return proxy.url

    def get_random_proxy(self) -> Optional[str]:
        """Random alive proxy do"""
        alive = [p for p in self._pool if p.is_alive]
        if not alive:
            return None
        return random.choice(alive).url

    def report_failure(self, proxy_url: str):
        """Proxy ko failed mark karo"""
        for p in self._pool:
            if p.url == proxy_url:
                p.mark_failed()
                break

    def report_success(self, proxy_url: str, response_time: float = 0.0):
        """Proxy ko success mark karo"""
        for p in self._pool:
            if p.url == proxy_url:
                p.mark_success(response_time)
                break

    # ── Background Tasks ──────────────────────────────────────────────────────

    async def _auto_refresh_loop(self):
        """Har N seconds mein pool refresh karo"""
        while True:
            await asyncio.sleep(settings.PROXY_REFRESH_INTERVAL)
            try:
                await self.refresh_pool()
            except Exception as e:
                log.error(f"Auto-refresh failed: {e}")

    async def _tor_rotate_loop(self):
        """Tor IP rotate karo"""
        while True:
            await asyncio.sleep(settings.TOR_ROTATE_EVERY)
            try:
                self._rotate_tor_ip()
            except Exception as e:
                log.warning(f"Tor rotation failed: {e}")

    def _rotate_tor_ip(self):
        try:
            from stem import Signal
            from stem.control import Controller
            with Controller.from_port(port=settings.TOR_CONTROL_PORT) as ctrl:
                ctrl.authenticate()
                ctrl.signal(Signal.NEWNYM)
                log.info("🧅 Tor IP rotated!")
        except Exception as e:
            log.error(f"Tor rotate error: {e}")

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        alive = [p for p in self._pool if p.is_alive]
        dead = [p for p in self._pool if not p.is_alive]
        current = self.get_proxy()

        return {
            "total_proxies": len(self._pool),
            "active_proxies": len(alive),
            "failed_proxies": len(dead),
            "current_proxy": current,
            "last_refreshed": self._last_refreshed,
            "tor_enabled": settings.USE_TOR,
            "requests_served": self._requests_served,
        }


# Global proxy pool instance
proxy_pool = ProxyPoolManager()
