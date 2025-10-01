from __future__ import annotations

import time
import random
from typing import List, Dict, Any

import default_selectors as DEFAULT_SELECTORS

from data_models import SearchCard
from amz_scraper import AmzScraper
from headers_factory import HeaderFactory
from csv_fns import export_rows_csv

BASE = "https://www.amazon.com"


if __name__ == "__main__":
    hf = HeaderFactory(browser="chrome", os_name="win", include_misc=True, referer=BASE + "/")

    scraper = AmzScraper(
        selectors=DEFAULT_SELECTORS,
        use_tor=False,
        header_factory=hf.generate,  # pass callable
    )

    search_url = "https://www.amazon.com/s?k=hats&crid=3UD0HZDEGZ2PT&sprefix=ha%2Caps%2C230&ref=nb_sb_noss_2"

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

        try:
            print(f"[{idx}/{len(cards)}] Fetching product: {url}")
            html = scraper.fetch(url, rotate_ip=True)
            details = scraper.parse_product_page(html)

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
        time.sleep(random.uniform(2.0, 5.0))  # polite pacing

    # 3) Write CSV
    out_path = "out/products_with_discounts.csv"
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
