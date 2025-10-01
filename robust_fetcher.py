from __future__ import annotations

import time
import re
import random
from typing import Tuple, Callable, Optional, Dict, Any, Iterable

import requests
from requests_tor import RequestsTor
from headers_factory import HeaderFactory
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BOT_PATTERNS = re.compile(r"(Robot Check|not a robot|captcha|enter the characters you see)", re.I)
BASE = "https://www.amazon.com/"


class RobustFetcher:
    def __init__(
        self,
        use_tor: bool = False,
        tor_ports: Tuple[int, ...] = (9150,),
        tor_cport: int = 9151,
        per_req_sleep: Tuple[float, float] = (2.5, 5.0),
        max_retries: int = 4,
        backoff_base: float = 1.8,
        timeout: int = 30,
        header_factory: Optional[Callable[[], Dict[str, str]]] = None,
        headers: Optional[Dict[str, str]] = None,
        retry_http_statuses: Iterable[int] = (403, 429, 500, 502, 503, 504),
    ):
        self.use_tor = use_tor
        self.rt = None
        if use_tor:
            if not RequestsTor:
                raise RuntimeError("requests_tor not installed but use_tor=True")
            self.rt = RequestsTor(tor_ports=tor_ports, tor_cport=tor_cport)

        self.per_req_sleep = per_req_sleep
        self.backoff_base = backoff_base
        self.timeout = timeout
        self.max_retries = max(1, int(max_retries))
        self.retry_http_statuses = set(retry_http_statuses)

        # Headers
        self.header_factory = header_factory or self._default_header_factory
        self.static_headers = headers

        # Session (cookies persist here)
        self.sess = requests.Session()
        retries = Retry(total=0, backoff_factor=0, raise_on_status=False)
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=retries)
        self.sess.mount("http://", adapter)
        self.sess.mount("https://", adapter)
        self.sess.headers.update(self._build_headers())

        # Warm up once to acquire baseline cookies
        self._warmup()

    @staticmethod
    def _default_header_factory() -> Dict[str, str]:
        hf = HeaderFactory(browser="chrome", os_name="win", include_misc=True, referer=BASE)
        return hf.generate()

    def _build_headers(self) -> Dict[str, str]:
        if self.header_factory:
            return self.header_factory()
        return dict(self.static_headers or {})

    def _nav_headers(self, referer: Optional[str]) -> Dict[str, str]:
        h = self._build_headers()
        # Enrich to look like a normal navigation
        if referer:
            h["Referer"] = referer
            h["Sec-Fetch-Site"] = "same-origin" if referer.startswith(BASE) else "cross-site"
        else:
            h["Referer"] = BASE
            h["Sec-Fetch-Site"] = "none"
        h.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        h.setdefault("Accept-Language", "en-US,en;q=0.9")
        h["Sec-Fetch-Dest"] = "document"
        h["Sec-Fetch-Mode"] = "navigate"
        h["Sec-Fetch-User"] = "?1"
        h["Upgrade-Insecure-Requests"] = "1"
        h["Connection"] = "keep-alive"
        return h

    def _rotate_identity(self):
        if self.rt:
            self.rt.new_id()
            time.sleep(3)

    def _polite_sleep(self):
        lo, hi = self.per_req_sleep
        time.sleep(random.uniform(lo, hi))

    def _backoff_sleep(self, attempt: int):
        delay = (self.backoff_base ** attempt) + random.uniform(0.2, 1.1)
        time.sleep(min(25.0, delay))

    def _warmup(self):
        """Hit homepage and robots to get cookies and appear normal."""
        try:
            self.sess.get(BASE, headers=self._nav_headers(referer=None), timeout=self.timeout)
            self.sess.get(BASE + "robots.txt", headers=self._nav_headers(referer=BASE), timeout=self.timeout)
            time.sleep(random.uniform(0.8, 1.5))
        except requests.RequestException:
            pass  # warmup best-effort

    def fetch(self, url: str, rotate_on_fail: bool = True, referer: Optional[str] = None) -> str:
        self._polite_sleep()
        last_status = None
        last_text = ""

        for attempt in range(1, self.max_retries + 1):
            hdrs = self._nav_headers(referer)
            try:
                html, status = self._get(url, hdrs)
                last_status, last_text = status, html

                if status in self.retry_http_statuses or BOT_PATTERNS.search(html):
                    if attempt < self.max_retries:
                        if rotate_on_fail:
                            self._rotate_identity()
                        # Re-warm after identity change
                        self._warmup()
                        self._backoff_sleep(attempt)
                        continue
                    break

                if status < 400 and not BOT_PATTERNS.search(html):
                    return html

                break  # non-retryable 4xx
            except requests.RequestException:
                if attempt < self.max_retries:
                    if rotate_on_fail:
                        self._rotate_identity()
                    self._warmup()
                    self._backoff_sleep(attempt)
                    continue
                break

        # Fail with informative message
        msg = f"HTTP {last_status} while fetching {url}" if last_status else f"Network error while fetching {url}"
        if last_text and BOT_PATTERNS.search(last_text):
            msg = "Bot detection page returned (captcha/robot check)."
        raise RuntimeError(msg)

    def _get(self, url: str, headers: Dict[str, str]) -> tuple[str, int]:
        if self.rt:
            r = self.rt.get(url, headers=headers, timeout=self.timeout)
        else:
            r = self.sess.get(url, headers=headers, timeout=self.timeout)
        return (r.text or ""), r.status_code
