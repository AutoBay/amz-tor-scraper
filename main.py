from __future__ import annotations

import os
import time
import random
from typing import List, Dict, Any

from selenium_fetcher import BrowserFetcher
from amz_scraper import AmzScraper
from data_models import SearchCard
from csv_fns import export_rows_csv

BASE = "https://www.amazon.com"

TOR_BROWSER_PATH = None  # e.g. "/Applications/Tor Browser.app/Contents/MacOS/firefox"
GECKODRIVER_PATH = None  # e.g. "/opt/homebrew/bin/geckodriver" or "/usr/local/bin/geckodriver"


def run(seed_url: str, page_limit: int = 10) -> None:
    fetcher = BrowserFetcher(
        tor_browser_path=TOR_BROWSER_PATH,
        geckodriver_path=GECKODRIVER_PATH,
        headless=False,
        page_load_timeout=60,
        per_req_sleep=(1.2, 2.8),
        warmup=True,
    )

    scraper = AmzScraper(fetcher=fetcher)

    try:
        cards: List[SearchCard] = scraper.crawl_search(seed_url, page_limit=page_limit, rotate_ip=True)
        print(f"Collected {len(cards)} cards across pages.")

        rows: List[Dict[str, Any]] = []
        for idx, c in enumerate(cards, 1):
            url = c.product_url
            row: Dict[str, Any] = {
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

            try:
                print(f"[{idx}/{len(cards)}] Fetching product: {url}")
                html = scraper.fetch(url, rotate_ip=True)
                details = scraper.parse_product_page(html)

                dims = AmzScraper.get_dimensions_from_kv(details.details_kv or {})

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
            time.sleep(random.uniform(1.5, 3.5))

        out_path = "out/products_with_discounts.csv"
        ordered = [{
            "title": r.get("title"),
            "price_current": r.get("price_current"),
            "price_original": r.get("price_original"),
            "discount_percent": r.get("discount_percent"),
            "discount_source": r.get("discount_source"),
            "has_coupon": r.get("has_coupon"),
            "is_limited_time_deal": r.get("is_limited_time_deal"),
            "url": r.get("url"),
            "product_dimensions": r.get("product_dimensions"),
        } for r in rows]
        export_rows_csv(out_path, ordered, append=False)
        print(f"Wrote CSV: {out_path}")

    finally:
        fetcher.close()


if __name__ == "__main__":
    seed_search_url = "https://www.amazon.com/s?k=hats&ref=nb_sb_noss_2"
    run(seed_search_url, page_limit=10)
