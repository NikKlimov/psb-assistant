from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from psb_assistant.cache import Cache
from psb_assistant.http import PoliteHTTP
from psb_assistant.models import Category, bank_url
from psb_assistant.parsers import PARSERS

logger = logging.getLogger(__name__)
SEEDS: dict[Category, str] = {
    "deposits": "https://www.psbank.ru/personal/saving",
    "loans": "https://www.psbank.ru/personal/loans",
    "cards": "https://www.psbank.ru/personal/cards",
}

# The mortgage catalogue is separate from consumer loans but belongs to the
# same product category for search questions about the Far East and SVO.
EXTRA_SEEDS: dict[Category, tuple[str, ...]] = {
    "deposits": ("https://www.psbank.ru/personal/savingsaccount",),
    "loans": ("https://www.psbank.ru/personal/mortgage/east",),
    "cards": (),
}

ALLOWED_PREFIXES: dict[Category, tuple[str, ...]] = {
    "deposits": ("/personal/saving/", "/personal/savingsaccount"),
    "loans": ("/personal/loans/",),
    "cards": (
        "/personal/cards/",
        "/personal/debetcards/",
        "/personal/creditcards/",
        "/personal/pensioncards/",
        "/personal/salary/",
    ),
}
NON_PRODUCT_PARTS: dict[Category, tuple[str, ...]] = {
    "deposits": ("/taxes", "/currency_faq", "/archivedoc", "/safes", "/partners"),
    "loans": ("/methods", "/calculator", "/deferment", "/vacation"),
    "cards": (
        "/offers",
        "/rules",
        "/stiker",
        "/cashback",
        "/refillcards",
        "/deferment",
        "/partners",
        "/online",
    ),
}
PRODUCT_HINTS: dict[Category, tuple[str, ...]] = {
    "deposits": ("vklad", "yuan", "savingsaccount", "social", "income", "strong", "dragots", "stavka"),
    "loans": ("credit", "auto", "refinancing", "specialpurpose", "creditaction"),
    "cards": (
        "yourcashback",
        "residentcard",
        "cska",
        "tolko-vpered",
        "a7-card",
        "detskaya",
        "100_plus",
        "pensioncard",
        "militarypension",
        "karta-dlya-zarplaty",
        "salary",
    ),
}


@dataclass
class CrawlReport:
    updated: int = 0
    cached: int = 0
    errors: list[str] = field(default_factory=list)
    categories: dict[str, int] = field(default_factory=dict)


class Crawler:
    def __init__(self, cache: Cache, http: PoliteHTTP) -> None:
        self.cache = cache
        self.http = http

    def listing(self, url: str, force: bool) -> str:
        row = None if force else self.cache.get(url)
        if row:
            return row[0]
        body = self.http.fetch(url)
        self.cache.put(url, body)
        return body

    @staticmethod
    def links(html: str, seed: str, category: Category) -> list[str]:
        result: list[str] = []
        allowed = ALLOWED_PREFIXES[category]
        for link in BeautifulSoup(html, "html.parser").select("a[href]"):
            url = urljoin(seed, str(link.get("href"))).rstrip("/")
            try:
                bank_url(url)
            except ValueError:
                continue
            path = urlsplit(url).path.lower()
            if (
                any(path.startswith(prefix) for prefix in allowed)
                and not path.endswith((".pdf", ".doc", ".docx", ".zip"))
                and not any(part in path for part in ("/archive", "/arhiv"))
                and not any(part in path for part in NON_PRODUCT_PARTS[category])
                and url not in result
            ):
                result.append(url)
        hints = PRODUCT_HINTS[category]
        return sorted(
            result, key=lambda url: (-sum(hint in url.lower() for hint in hints), result.index(url))
        )

    def run(self, force: bool = False, max_per_category: int = 8) -> CrawlReport:
        report = CrawlReport()
        # Cached pages require neither a network request nor a second parse.
        try:
            self.http.load_robots(force=force)
        except Exception as exc:
            logger.error("robots_unavailable error=%s", type(exc).__name__)
            report.errors.append(
                "Не удалось проверить robots.txt. Обход отменен; сохраненные данные доступны."
            )
            report.categories = self.coverage()
            return report
        for category, seed in SEEDS.items():
            seeds = (seed, *EXTRA_SEEDS[category])
            category_failed = True
            for seed in seeds:
                try:
                    if seed in EXTRA_SEEDS[category]:
                        urls = [seed]
                    else:
                        html = self.listing(seed, force)
                        urls = self.links(html, seed, category)[:max_per_category]
                    # The detail page itself is a valid source when a product
                    # landing page does not expose child links.
                    if not urls and seed != SEEDS[category]:
                        urls = [seed]
                    if not urls:
                        raise ValueError("No product links in category listing")
                    category_failed = False
                except Exception as exc:
                    logger.error(
                        "category_failed category=%s url=%s error=%s", category, seed, type(exc).__name__
                    )
                    report.errors.append(f"Не удалось прочитать каталог {category}: {seed}")
                    continue
                for url in urls:
                    try:
                        row = None if force else self.cache.get(url)
                        if row:
                            report.cached += 1
                            continue
                        body = self.http.fetch(url)
                        product = PARSERS[category].parse(body, url)
                        # Publish raw HTML and parsed conditions together after validation.
                        self.cache.put(url, body, product)
                        report.updated += 1
                        logger.info(
                            "product_updated category=%s url=%s parser=%s", category, url, product.parser_mode
                        )
                    except Exception as exc:
                        logger.error(
                            "page_failed category=%s url=%s error=%s", category, url, type(exc).__name__
                        )
                        report.errors.append(f"Не удалось обновить страницу: {url}")
            if category_failed:
                continue
        report.categories = self.coverage()
        logger.info(
            "crawl_complete updated=%s cached=%s coverage=%s",
            report.updated,
            report.cached,
            report.categories,
        )
        return report

    def coverage(self) -> dict[str, int]:
        products = self.cache.products()
        return {category: sum(p.category == category for p in products) for category in SEEDS}
