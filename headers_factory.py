import re
from typing import  Optional, Dict
from fake_headers import Headers

BASE = "https://www.amazon.com"

UA_OK = re.compile(r"(Chrome/(8\d|9\d|1\d{2})|Firefox/(8\d|9\d|1\d{2}))", re.I)

class HeaderFactory:
    def __init__(
        self,
        browser: str = "chrome",
        os_name: str = "win",
        include_misc: bool = True,
        referer: Optional[str] = BASE + "/",
        accept_language: str = "en-US,en;q=0.9",
        accept_encoding: str = "gzip, deflate, br",
    ):
        self.browser = browser
        self.os_name = os_name
        self.include_misc = include_misc
        self.referer = referer
        self.accept_language = accept_language
        self.accept_encoding = accept_encoding

    def generate(self) -> Dict[str, str]:
        h: Dict[str, str] = {}
        if Headers:
            gen = Headers(browser=self.browser, os=self.os_name, headers=self.include_misc).generate()
            h.update(gen)
        ua = h.get("User-Agent", "")
        if not UA_OK.search(ua):
            h["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        h.setdefault("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        h.setdefault("Accept-Language", self.accept_language)
        h.setdefault("Accept-Encoding", self.accept_encoding)
        h.setdefault("Connection", "keep-alive")
        if self.referer and "Referer" not in h:
            h["Referer"] = self.referer
        h.setdefault("Upgrade-Insecure-Requests", "1")
        h.setdefault("DNT", "1")
        return h