from __future__ import annotations

import os
import time
import random
import shutil
from typing import Optional, Tuple

from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


BASE = "https://www.amazon.com/"


def _default_tor_binary_paths() -> list[str]:
    # Common Tor Browser locations on macOS
    return [
        "/Applications/Tor Browser.app/Contents/MacOS/firefox",
        os.path.expanduser("~/Applications/Tor Browser.app/Contents/MacOS/firefox"),
    ]


def _resolve_tor_binary(user_path: Optional[str]) -> str:
    candidates = []
    if user_path:
        candidates.append(user_path)
    candidates += _default_tor_binary_paths()
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    # last resort: search Spotlight
    try:
        import subprocess
        out = subprocess.check_output(
            ["mdfind", "kMDItemCFBundleIdentifier == 'org.torproject.torbrowser'"], text=True
        ).strip().splitlines()
        for app in out:
            fp = os.path.join(app, "Contents", "MacOS", "firefox")
            if os.path.isfile(fp):
                return fp
    except Exception:
        pass
    raise FileNotFoundError(
        "Tor Browser binary not found. Set tor_browser_path to Tor Browser.app/Contents/MacOS/firefox"
    )


def _resolve_geckodriver(user_path: Optional[str]) -> Optional[str]:
    # If user provided a path, validate it
    if user_path:
        if os.path.isfile(user_path):
            return user_path
        raise FileNotFoundError(f"geckodriver path is not a file: {user_path}")

    # Try PATH
    which = shutil.which("geckodriver")
    if which and os.path.isfile(which):
        return which

    # If not found, return None; Selenium Manager can try to download automatically
    return None


class BrowserFetcher:
    """
    Selenium-backed fetcher that launches the actual Tor Browser (Firefox ESR),
    so you can see pages loading in real time.
    """

    def __init__(
        self,
        tor_browser_path: Optional[str] = None,
        geckodriver_path: Optional[str] = None,
        headless: bool = False,
        page_load_timeout: int = 45,
        per_req_sleep: Tuple[float, float] = (1.0, 2.5),
        warmup: bool = True,
    ):
        self.per_req_sleep = per_req_sleep

        tor_bin = _resolve_tor_binary(tor_browser_path)
        gecko_bin = _resolve_geckodriver(geckodriver_path)

        opts = FirefoxOptions()
        opts.binary_location = tor_bin
        if headless:
            opts.add_argument("-headless")

        # If geckodriver path is known, use it; otherwise let Selenium Manager resolve it
        if gecko_bin:
            service = FirefoxService(executable_path=gecko_bin)
            self.driver = webdriver.Firefox(service=service, options=opts)
        else:
            # Selenium Manager path (requires Selenium 4.10+)
            self.driver = webdriver.Firefox(options=opts)

        self.driver.set_page_load_timeout(page_load_timeout)

        if warmup:
            self._warmup()

    def _warmup(self):
        try:
            self.driver.get(BASE)
            WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(random.uniform(0.6, 1.2))
            self.driver.get(BASE + "robots.txt")
            WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "pre")))
            time.sleep(random.uniform(0.6, 1.2))
        except Exception:
            pass  # best-effort

    def fetch(self, url: str, rotate_on_fail: bool = True, referer: Optional[str] = None) -> str:
        time.sleep(random.uniform(*self.per_req_sleep))
        self.driver.get(url)
        WebDriverWait(self.driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(1.0)
        return self.driver.page_source

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass
