"""Reparse cached public HTML without refreshing its provenance timestamp.

Useful after changing parser rules: no bank request is made and a failed parse
never replaces a previously valid product snapshot.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from psb_assistant.cache import Cache
from psb_assistant.config import Settings
from psb_assistant.parsers import PARSERS

SERVICE_PARTS = (
    "/taxes", "/currency_faq", "/archivedoc", "/safes", "/partners",
    "/offers", "/rules", "/stiker", "/cashback", "/refillcards",
    "/deferment", "/methods", "/calculator", "/vacation",
)


def category_for(url: str) -> str | None:
    if "/saving/" in url:
        return "deposits"
    if "/loans/" in url or "/mortgage/" in url:
        return "loans"
    if any(part in url for part in ("/cards/", "/debetcards/", "/pensioncards/", "/salary/")):
        return "cards"
    return None


def main() -> None:
    settings = Settings.from_env()
    cache = Cache(settings.cache_path)
    with sqlite3.connect(cache.path) as db:
        rows = db.execute("SELECT url, body, fetched FROM pages WHERE body IS NOT NULL").fetchall()
    report: list[str] = []
    for url, body, fetched in rows:
        if any(part in url for part in SERVICE_PARTS):
            cache.clear_product(url)
            continue
        category = category_for(url)
        if category is None:
            continue
        try:
            product = PARSERS[category].parse(body, url)
            product.fetched_at = datetime.fromtimestamp(fetched, UTC)
            cache.replace_product(url, product)
            report.append(f"OK {product.product_name}: {len(product.params)} facts")
        except Exception as exc:  # keep the previous valid snapshot on failure
            report.append(f"SKIP {url}: {type(exc).__name__}")
    print("\n".join(report))


if __name__ == "__main__":
    main()
