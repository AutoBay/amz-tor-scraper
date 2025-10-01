from __future__ import annotations

import time
import re
import random
from typing import Tuple, Callable, Optional, Dict, Any

import requests
from requests_tor import RequestsTor
from headers_factory import HeaderFactory
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BOT_PATTERNS = re.compile(r"(Robot Check|not a robot|captcha|enter the characters you see)", re.I)


class RobustFetcher:
    def __init__(
        self,
        use_tor: bool = False,
        tor_ports: Tuple[int, ...] = (9150,),
        tor_cport: int = 9151,
        per_req_sleep: Tuple[float, float] = (2.5, 5.0),
        max_retries: int = 2,
        backoff_base: float = 1.5,
        timeout: int = 30,
        header_factory: Optional[Callable[[], Dict[str, str]]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        header_factory: callable returning fresh headers per request (preferred).
        headers: static headers dict (fallback). If both provided, header_factory wins.
        """
        self.use_tor = use_tor
        self.rt = None
        if use_tor:
            if not RequestsTor:
                raise RuntimeError("requests_tor not installed but use_tor=True")
            self.rt = RequestsTor(tor_ports=tor_ports, tor_cport=tor_cport)

        self.per_req_sleep = per_req_sleep
        self.backoff_base = backoff_base
        self.timeout = timeout

        # Header strategy
        self.header_factory = header_factory
        if self.header_factory is None:
            # default rotating headers generator
            def _default_headers() -> Dict[str, str]:
                hf = HeaderFactory(browser="chrome", os_name="win", include_misc=True, referer="https://www.amazon.com/")
                return hf.generate()
            self.header_factory = _default_headers
        self.static_headers = headers  # optional, unused when header_factory present

        # Session and retries
        self.sess = requests.Session()
        retries = Retry(
            total=max_retries,
            connect=max_retries,
            read=max_retries,
            status=max_retries,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
            backoff_factor=self.backoff_base,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=retries)
        self.sess.mount("http://", adapter)
        self.sess.mount("https://", adapter)

        # Prime session headers once; per-request we override again
        self.sess.headers.update(self._build_headers())

    def _build_headers(self) -> Dict[str, str]:
        if self.header_factory:
            return self.header_factory()
        return dict(self.static_headers or {})

    def _rotate_identity(self):
        if self.rt:
            self.rt.new_id()
            time.sleep(3)

    def _polite_sleep(self):
        lo, hi = self.per_req_sleep
        time.sleep(random.uniform(lo, hi))

    def fetch(self, url: str, rotate_on_fail: bool = True) -> str:
        self._polite_sleep()
        html, status = self._get(url)
        if status in (429, 503) or BOT_PATTERNS.search(html):
            if rotate_on_fail:
                self._rotate_identity()
            time.sleep(random.uniform(8.0, 15.0))
            html, status = self._get(url)

        if status >= 400:
            raise RuntimeError(f"HTTP {status} while fetching {url}")
        if BOT_PATTERNS.search(html):
            raise RuntimeError("Bot detection page returned (captcha/robot check).")
        return html

    def _get(self, url: str) -> tuple[str, int]:
        # Always use fresh headers; helps with rotation/entropy
        hdrs = self._build_headers()
        if self.rt:
            r = self.rt.get(url, headers=hdrs, timeout=self.timeout)
        else:
            r = self.sess.get(url, headers=hdrs, timeout=self.timeout)
        return r.text or "", r.status_code
