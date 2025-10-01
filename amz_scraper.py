from __future__ import annotations

import re
from typing import List, Optional, Dict, Any, Iterable, Tuple
from urllib.parse import urlparse, parse_qs, unquote, urljoin

from bs4 import BeautifulSoup, Tag
import default_selectors as DEFAULT_SELECTORS

from data_models import ProductDetails, SearchCard

MONEY_RE = re.compile(r"(\d{1,3}(?:[,]\d{3})*(?:\.\d{2})|\d+(?:\.\d{2})?)")
PCT_RE = re.compile(r"(\d{1,3})\s*%")
LTD_HINT = re.compile(r"(limited[-\s]?time|deal|lightning)", re.I)

BASE = "https://www.amazon.com"


class AmzScraper:
    """
    Parser + flow. Expects a fetcher with a .fetch(url, rotate_on_fail=True, referer=None) -> str.
    For 'visible Tor' runs, pass BrowserFetcher from selenium_fetcher.py.
    """

    def __init__(
        self,
        fetcher,
        selectors: DEFAULT_SELECTORS = DEFAULT_SELECTORS,
    ):
        self.sel = selectors
        self.fetcher = fetcher

    # Network
    def fetch(self, url: str, rotate_ip: bool = True, referer: Optional[str] = None) -> str:
        return self.fetcher.fetch(url, rotate_on_fail=rotate_ip, referer=referer)

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
        u = href if href.startswith(("http://", "https://")) else urljoin(BASE, href)
        p = urlparse(u)
        if "/sspa/click" in p.path:
            q = parse_qs(p.query)
            inner = q.get("url", [None])[0]
            if inner:
                inner = unquote(inner)
                u = urljoin(BASE, inner) if inner.startswith("/") else inner
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

    # Tech-spec tables
    def _get_details_kv_from_tables(self, root: BeautifulSoup | Tag) -> Dict[str, str]:
        rows_sel = self.sel["product_page"]["details_table_rows"]
        th_sel = self.sel["product_page"]["details_th"]
        td_sel = self.sel["product_page"]["details_td"]
        kv: Dict[str, str] = {}
        for row in root.select(rows_sel):
            k = self.query_text(row, th_sel)
            v = self.query_text(row, td_sel)
            if k and v:
                kv[k.rstrip(":").strip()] = v
        return kv

    # Detail bullets block
    def _get_details_kv_from_bullets(self, root: BeautifulSoup | Tag) -> Dict[str, str]:
        rows = self.sel["product_page"].get("detail_bullets_rows")
        key_sel = self.sel["product_page"].get("detail_bullets_key")
        val_sel = self.sel["product_page"].get("detail_bullets_val")
        if not (rows and key_sel and val_sel):
            return {}
        kv: Dict[str, str] = {}
        for li in root.select(rows):
            k = self.query_text(li, key_sel)
            v = self.query_text(li, val_sel)
            if k:
                k = k.rstrip(":").strip()
            if k and v:
                kv[k] = v
        return kv

    def get_details_kv(self, root: BeautifulSoup | Tag) -> Dict[str, str]:
        kv = {}
        kv.update(self._get_details_kv_from_tables(root))
        kv.update(self._get_details_kv_from_bullets(root))
        return kv

    @staticmethod
    def get_dimensions_from_kv(kv: Dict[str, str]) -> Optional[str]:
        return (
            kv.get("Product Dimensions")
            or kv.get("Package Dimensions")
            or kv.get("Item Dimensions LxWxH")
            or kv.get("Item Dimensions")
        )

    # Pricing helpers
    @staticmethod
    def _money_to_float(text: Optional[str]) -> Optional[float]:
        if not text:
            return None
        m = re.search(r"(\d+(?:\.\d{2})?)", text.replace(",", ""))
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
        if coupon_text:
            m = re.search(r"(\d{1,3})\s*%", coupon_text)
            if m:
                return float(m.group(1)), "coupon"
            amt = re.search(r"(\d+(?:\.\d{2})?)", (coupon_text or "").replace(",", ""))
            if amt and price_current and price_current > 0:
                val = float(amt.group(1))
                return round(100.0 * val / price_current, 2), "coupon"

        if price_current is not None and price_original and price_original > 0:
            pct = round(100.0 * (price_original - price_current) / price_original, 2)
            if pct > 0:
                if ltd_text and LTD_HINT.search(ltd_text or ""):
                    return pct, "limited_deal"
                return pct, "price_compare"

        if ltd_text:
            m = re.search(r"(\d{1,3})\s*%", ltd_text)
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
        details_kv = self.get_details_kv(root)
        return ProductDetails(
            name=self.get_product_name(root),
            seller_name=self.get_seller_name(root),
            description_text=self.get_description(root),
            is_in_stock=self.is_in_stock(root),
            return_policy_text=self.get_return_policy(root),
            images_text=self.get_images_text(root),
            details_kv=details_kv,
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

    # Pagination
    def _next_page_url_from_root(self, root: BeautifulSoup | Tag) -> Optional[str]:
        if root.select_one("span.s-pagination-item.s-pagination-next.s-pagination-disabled"):
            return None
        a = root.select_one("a.s-pagination-item.s-pagination-next")
        if not a:
            return None
        href = a.get("href")
        return self.normalize_product_url(href)

    def next_page_url(self, html: str) -> Optional[str]:
        root = self.soup(html)
        return self._next_page_url_from_root(root)

    def crawl_search(self, start_url: str, page_limit: int = 50, rotate_ip: bool = True) -> List[SearchCard]:
        all_cards: List[SearchCard] = []
        seen_urls: set[str] = set()
        url = start_url
        pages = 0
        prev_url: Optional[str] = None  # not used by BrowserFetcher, kept for interface parity

        while url and pages < page_limit:
            if url in seen_urls:
                break
            seen_urls.add(url)
            pages += 1

            html = self.fetch(url, rotate_ip=rotate_ip, referer=prev_url or BASE + "/")
            all_cards.extend(self.parse_search_results(html))

            next_url = self.next_page_url(html)
            prev_url, url = url, next_url

        return all_cards
