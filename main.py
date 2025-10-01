# amz_scraper.py
from __future__ import annotations

import time
import re
import random
import os
import csv
import json
from dataclasses import dataclass, asdict, is_dataclass
from typing import List, Optional, Dict, Any, Iterable, Tuple, Callable
from urllib.parse import urlparse, parse_qs, unquote, urljoin

from bs4 import BeautifulSoup, Tag

# Optional deps
try:
    from fake_headers import Headers as FakeHeaders  # pip install fake-headers html5lib bs4
except Exception:
    FakeHeaders = None

try:
    from requests_tor import RequestsTor  # pip install requests_tor
except Exception:
    RequestsTor = None

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# -----------------------------
# Selectors
# -----------------------------
DEFAULT_SELECTORS: Dict[str, Any] = {
    "navbar": {
        "search_result_input": "#twotabsearchtextbox",
        "search_button": "#nav-search-submit-button",
        "zipcode": {
            "open_zipcode": "#nav-global-location-popover-link",
            "zipcode_input": "#GLUXZipUpdateInput",
            "apply_button": "#GLUXZipUpdate-announce",
            "done_button": "#a-autoid-51-announce",
        },
    },
    "page_result_products": {
        "product_container": ".a-section.a-spacing-base.desktop-grid-content-view",
        "price": '[data-a-size="xl"]',
        "is_coupon_exist": ".a-size-base.s-highlighted-text-padding.s-coupon-highlight-color.aok-inline-block",
        "product_link_to_extra_data": "a.a-link-normal.s-no-outline",
        "title": "h2.a-size-base-plus.a-spacing-none.a-color-base.a-text-normal",
        "is_limited_time_deal": 'span[data-a-badge-color="sx-red-mvt"]',
    },
    "product_page": {
        "title": "#productTitle, h1#title",
        "images": "#canvasCaption",
        "seller_name": "#sellerProfileTriggerId",
        "description": "#feature-bullets",
        "is_on_stock": "#availability",
        "return_policy": "#returnsInfoFeature_feature_div > div.offer-display-feature-text.a-size-small > span > a > span",
        "details_table_rows": (
            "#productDetails_techSpec_section_1 tr, "
            "#productDetails_detailBullets_sections1 tr, "
            "#productDetails_techSpec_section_2 tr, "
            "table.prodDetTable tr"
        ),
        "details_th": "th, td.prodDetSectionEntry",
        "details_td": "td, td.prodDetAttrValue",
        "is_more_deals_on_releated_products": "#sp_detail_thematic-hercules_hybrid_deals_T1",
        "stock_positive_keywords": "in stock|available|ships soon",

        # Pricing selectors (common variants on Amazon product pages)
        "price_current": "#corePrice_feature_div .a-price .a-offscreen, #price_inside_buybox, #tp_price_block_total_price_ww",
        "price_original": "#price .a-text-price .a-offscreen, #corePrice_desktop .a-text-price .a-offscreen, #listPriceLegalMessage .a-offscreen",
        "coupon_text": "#couponBadgeRegularArithmetic, #couponTextBucket, #promoPriceBlockMessage_feature_div",
        "limited_deal_badge": "span[data-a-badge-color='sx-red-mvt'], #dealBadge_feature_div, #priceBadging_feature_div",
    },
}

BASE = "https://www.amazon.com"

# -----------------------------
# Header factory
# -----------------------------
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
        if FakeHeaders:
            gen = FakeHeaders(browser=self.browser, os=self.os_name, headers=self.include_misc).generate()
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


# -----------------------------
# Robust fetcher
# -----------------------------
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
        self.headers = (header_factory or HeaderFactory().generate)()

        self.sess = requests.Session()
        self.sess.headers.update(self.headers)

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
        if self.rt:
            r = self.rt.get(url, headers=self.sess.headers, timeout=self.timeout)
        else:
            r = self.sess.get(url, timeout=self.timeout)
        return r.text or "", r.status_code


# -----------------------------
# Data models
# -----------------------------
@dataclass
class SearchCard:
    title: Optional[str]
    price_text: Optional[str]
    has_coupon: bool
    is_limited_time_deal: bool
    product_url: Optional[str]


@dataclass
class ProductDetails:
    name: Optional[str]
    seller_name: Optional[str]
    description_text: Optional[str]
    is_in_stock: Optional[bool]
    return_policy_text: Optional[str]
    images_text: Optional[str]
    details_kv: Dict[str, str]
    has_related_deals: bool
    price_current: Optional[float] = None
    price_original: Optional[float] = None
    coupon_text: Optional[str] = None
    limited_deal_text: Optional[str] = None
    discount_percent: Optional[float] = None
    discount_source: Optional[str] = None  # "coupon" | "limited_deal" | "price_compare"


# -----------------------------
# CSV helpers
# -----------------------------
def _ensure_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def export_rows_csv(path: str, rows: List[Dict[str, Any]], append: bool = False) -> None:
    if not rows:
        return
    _ensure_dir(path)
    # preserve column order based on first row
    fieldnames = list(rows[0].keys())
    mode = "a" if append and os.path.exists(path) else "w"
    with open(path, mode, newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if mode == "w":
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})


# -----------------------------
# Scraper
# -----------------------------
MONEY_RE = re.compile(r"(\d{1,3}(?:[,]\d{3})*(?:\.\d{2})|\d+(?:\.\d{2})?)")
PCT_RE = re.compile(r"(\d{1,3})\s*%")
COUPON_HINT = re.compile(r"(coupon|save|apply)", re.I)
LTD_HINT = re.compile(r"(limited[-\s]?time|deal|lightning)", re.I)

class AmzScraper:
    def __init__(
        self,
        selectors: Dict[str, Any] | None = None,
        use_tor: bool = False,
        tor_ports: Tuple[int, ...] = (9150,),
        tor_cport: int = 9151,
        timeout: int = 30,
        header_factory: Optional[Callable[[], Dict[str, str]]] = None,
    ):
        self.sel = selectors or DEFAULT_SELECTORS
        self.fetcher = RobustFetcher(
            use_tor=use_tor,
            tor_ports=tor_ports,
            tor_cport=tor_cport,
            timeout=timeout,
            header_factory=header_factory,
        )

    # Network
    def fetch(self, url: str, rotate_ip: bool = True) -> str:
        return self.fetcher.fetch(url, rotate_on_fail=rotate_ip)

    # Soup / DOM
    @staticmethod
    def soup(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    @staticmethod
    def _clean_text(s: Optional[str]) -> Optional[str]:
        return re.sub(r"\s+", " ", s).strip() if s else None

    def query_exists(self, root: BeautifulSoup | Tag, selector: str) -> bool:
        return bool(root.select_one(selector))

    def query_text(self, root: BeautifulSoup | Tag, selector: str) -> Optional[str]:
        node = root.select_one(selector)
        return self._clean_text(node.get_text(separator=" ", strip=True)) if node else None

    def query_attr(self, root: BeautifulSoup | Tag, selector: str, attr: str) -> Optional[str]:
        node = root.select_one(selector)
        return node.get(attr) if node and node.has_attr(attr) else None

    # URL normalization and ad-unwrapping
    def normalize_product_url(self, href: Optional[str]) -> Optional[str]:
        if not href:
            return None
        # Absolute?
        if href.startswith("http://") or href.startswith("https://"):
            u = href
        else:
            u = urljoin(BASE, href)

        # Unwrap sspa/click ads if present
        p = urlparse(u)
        if "/sspa/click" in p.path:
            q = parse_qs(p.query)
            inner = q.get("url", [None])[0]
            if inner:
                inner = unquote(inner)
                if inner.startswith("/"):
                    u = urljoin(BASE, inner)
                else:
                    u = inner
        return u

    # Product page getters
    def get_product_name(self, root: BeautifulSoup | Tag) -> Optional[str]:
        return self.query_text(root, self.sel["product_page"]["title"])

    def get_seller_name(self, root: BeautifulSoup | Tag) -> Optional[str]:
        return self.query_text(root, self.sel["product_page"]["seller_name"])

    def get_description(self, root: BeautifulSoup | Tag) -> Optional[str]:
        return self.query_text(root, self.sel["product_page"]["description"])

    def get_return_policy(self, root: BeautifulSoup | Tag) -> Optional[str]:
        return self.query_text(root, self.sel["product_page"]["return_policy"])

    def is_in_stock(self, root: BeautifulSoup | Tag) -> Optional[bool]:
        avail = self.query_text(root, self.sel["product_page"]["is_on_stock"])
        if avail is None:
            return None
        pattern = self.sel["product_page"].get("stock_positive_keywords", "in stock")
        return bool(re.search(pattern, avail, re.I))

    def get_images_text(self, root: BeautifulSoup | Tag) -> Optional[str]:
        return self.query_text(root, self.sel["product_page"]["images"])

    def has_related_deals(self, root: BeautifulSoup | Tag) -> bool:
        return self.query_exists(root, self.sel["product_page"]["is_more_deals_on_releated_products"])

    def get_details_kv(self, root: BeautifulSoup | Tag) -> Dict[str, str]:
        rows_sel = self.sel["product_page"]["details_table_rows"]
        th_sel = self.sel["product_page"]["details_th"]
        td_sel = self.sel["product_page"]["details_td"]
        kv: Dict[str, str] = {}
        for row in root.select(rows_sel):
            k = self.query_text(row, th_sel)
            v = self.query_text(row, td_sel)
            if k and v:
                kv[k] = v
        return kv

    # Pricing helpers
    @staticmethod
    def _money_to_float(text: Optional[str]) -> Optional[float]:
        if not text:
            return None
        m = MONEY_RE.search(text.replace(",", ""))
        return float(m.group(1)) if m else None

    def _extract_price_fields(self, root: BeautifulSoup | Tag) -> Dict[str, Optional[str]]:
        s = self.sel["product_page"]
        return {
            "price_current_text": self.query_text(root, s["price_current"]),
            "price_original_text": self.query_text(root, s["price_original"]),
            "coupon_text": self.query_text(root, s["coupon_text"]),
            "limited_deal_text": self.query_text(root, s["limited_deal_badge"]),
        }

    @staticmethod
    def _compute_discount(
        price_current: Optional[float],
        price_original: Optional[float],
        coupon_text: Optional[str],
        ltd_text: Optional[str],
    ) -> Tuple[Optional[float], Optional[str]]:
        # 1) If coupon mentions percent: "Save 10%" or "Apply 15% coupon"
        if coupon_text:
            m = PCT_RE.search(coupon_text)
            if m:
                return float(m.group(1)), "coupon"
            # If coupon is amount: "Save $5"
            amt = MONEY_RE.search(coupon_text or "")
            if amt and price_current:
                # percent of current price (approx)
                val = float(amt.group(1))
                if price_current > 0:
                    return round(100.0 * val / price_current, 2), "coupon"

        # 2) Limited time deal often reflected by crossed-out original price
        if price_current is not None and price_original and price_original > 0:
            pct = round(100.0 * (price_original - price_current) / price_original, 2)
            if pct > 0:
                # hint if limited deal badge exists
                if ltd_text and LTD_HINT.search(ltd_text or ""):
                    return pct, "limited_deal"
                return pct, "price_compare"

        # 3) If limited-deal text itself has percent
        if ltd_text:
            m = PCT_RE.search(ltd_text)
            if m:
                return float(m.group(1)), "limited_deal"

        return None, None

    def parse_product_page(self, html: str) -> ProductDetails:
        root = self.soup(html)
        price_fields = self._extract_price_fields(root)
        price_current = self._money_to_float(price_fields["price_current_text"])
        price_original = self._money_to_float(price_fields["price_original_text"])
        discount_percent, discount_source = self._compute_discount(
            price_current, price_original, price_fields["coupon_text"], price_fields["limited_deal_text"]
        )

        return ProductDetails(
            name=self.get_product_name(root),
            seller_name=self.get_seller_name(root),
            description_text=self.get_description(root),
            is_in_stock=self.is_in_stock(root),
            return_policy_text=self.get_return_policy(root),
            images_text=self.get_images_text(root),
            details_kv=self.get_details_kv(root),
            has_related_deals=self.has_related_deals(root),
            price_current=price_current,
            price_original=price_original,
            coupon_text=price_fields["coupon_text"],
            limited_deal_text=price_fields["limited_deal_text"],
            discount_percent=discount_percent,
            discount_source=discount_source,
        )

    # Search parsing
    def _iter_product_cards(self, root: BeautifulSoup | Tag) -> Iterable[Tag]:
        return root.select(self.sel["page_result_products"]["product_container"])

    def get_card_title(self, card: Tag) -> Optional[str]:
        return self.query_text(card, self.sel["page_result_products"]["title"])

    def get_card_price_text(self, card: Tag) -> Optional[str]:
        return self.query_text(card, self.sel["page_result_products"]["price"])

    def card_has_coupon(self, card: Tag) -> bool:
        return self.query_exists(card, self.sel["page_result_products"]["is_coupon_exist"])

    def card_is_limited_time_deal(self, card: Tag) -> bool:
        return self.query_exists(card, self.sel["page_result_products"]["is_limited_time_deal"])

    def get_card_product_url(self, card: Tag) -> Optional[str]:
        href = self.query_attr(card, self.sel["page_result_products"]["product_link_to_extra_data"], "href")
        return self.normalize_product_url(href)

    def parse_search_results(self, html: str) -> List[SearchCard]:
        root = self.soup(html)
        out: List[SearchCard] = []
        for card in self._iter_product_cards(root):
            out.append(
                SearchCard(
                    title=self.get_card_title(card),
                    price_text=self.get_card_price_text(card),
                    has_coupon=self.card_has_coupon(card),
                    is_limited_time_deal=self.card_is_limited_time_deal(card),
                    product_url=self.get_card_product_url(card),
                )
            )
        return out


# -----------------------------
# Example usage: crawl search → visit each product → CSV
# -----------------------------
if __name__ == "__main__":
    hf = HeaderFactory(browser="chrome", os_name="win", include_misc=True, referer=BASE + "/")
    scraper = AmzScraper(selectors=DEFAULT_SELECTORS, use_tor=False, header_factory=hf.generate)

    search_url = (
        "https://www.amazon.com/s?k=hats&crid=3UD0HZDEGZ2PT&sprefix=ha%2Caps%2C230&ref=nb_sb_noss_2"
    )

    # 1) Get search cards (retry loop)
    max_attempts = 50
    attempt = 0
    cards: List[SearchCard] = []
    while True:
        attempt += 1
        try:
            print(f"Attempt {attempt} fetching search page…")
            search_html = scraper.fetch(search_url, rotate_ip=True)
            cards = scraper.parse_search_results(search_html)
            if cards:
                print(f"Parsed {len(cards)} cards.")
                break
            print("No products parsed, retrying…")
        except Exception as e:
            print(f"Search fetch failed: {e}")
        time.sleep(min(30, 3 * attempt))
        if attempt >= max_attempts:
            raise RuntimeError("Exceeded maximum retry attempts for search.")

    # 2) Visit each product; parse and write CSV rows
    rows: List[Dict[str, Any]] = []
    for idx, c in enumerate(cards, 1):
        url = c.product_url
        # Single-row output shape
        row = {
            "title": c.title,
            "price_current": None,
            "price_original": None,
            "discount_percent": None,
            "discount_source": None,
            "has_coupon": c.has_coupon,
            "is_limited_time_deal": c.is_limited_time_deal,
            "url": url,
            "product_dimensions": None,
        }

        if not url:
            rows.append(row)
            continue

        # Per-product try with mild backoff
        try:
            print(f"[{idx}/{len(cards)}] Fetching product: {url}")
            html = scraper.fetch(url, rotate_ip=True)
            details = scraper.parse_product_page(html)

            # Dimensions: prefer "Product Dimensions", else "Package Dimensions"
            dims = None
            if details.details_kv:
                dims = details.details_kv.get("Product Dimensions") or details.details_kv.get("Package Dimensions")

            row.update({
                "price_current": details.price_current,
                "price_original": details.price_original,
                "discount_percent": details.discount_percent,
                "discount_source": details.discount_source,
                "product_dimensions": dims,
            })
        except Exception as e:
            print(f"Product fetch failed: {e}")

        rows.append(row)
        # polite pacing
        time.sleep(random.uniform(2.0, 5.0))

    # 3) Write CSV: one row per product
    out_path = "out/products_with_discounts.csv"
    # Ensure columns order as requested: title … flags … url … dimensions
    ordered = []
    for r in rows:
        ordered.append({
            "title": r.get("title"),
            "price_current": r.get("price_current"),
            "price_original": r.get("price_original"),
            "discount_percent": r.get("discount_percent"),
            "discount_source": r.get("discount_source"),
            "has_coupon": r.get("has_coupon"),
            "is_limited_time_deal": r.get("is_limited_time_deal"),
            "url": r.get("url"),
            "product_dimensions": r.get("product_dimensions"),
        })
    export_rows_csv(out_path, ordered, append=False)
    print(f"Wrote CSV: {out_path}")
