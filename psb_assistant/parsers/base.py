from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup, Tag

from psb_assistant.models import Category, Fact, Product

logger = logging.getLogger(__name__)


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


class BaseParser:
    """Extract only the product body and labelled conditions from a PSB page."""

    category: Category
    keywords: dict[str, str]
    selectors = (".page__content", "main", "[role='main']", ".product-detail", "article")

    def _rows(self, root: Tag | BeautifulSoup) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for table in root.select("table"):
            for tr in table.select("tr"):
                cells = [clean(cell.get_text(" ", strip=True)) for cell in tr.select("th,td")]
                cells = [cell for cell in cells if cell]
                if len(cells) >= 2:
                    item = (cells[0], " | ".join(cells[1:]))
                    if item not in rows:
                        rows.append(item)
        for dt in root.select("dl dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                item = (clean(dt.get_text(" ", strip=True)), clean(dd.get_text(" ", strip=True)))
                if item[0] and item[1] and item not in rows:
                    rows.append(item)
        return rows

    def parse(self, html: str, url: str) -> Product:
        soup = BeautifulSoup(html, "html.parser")
        banner = soup.select_one(".inner-head-banner__description")
        description = clean(banner.get_text(" ", strip=True)) if banner else ""
        for item in soup.select(
            "script, style, noscript, nav, header, footer, form, [hidden], "
            "[aria-hidden='true'], .advantage-slider, .products-slider, [class*='search-contacts'], "
            ".product-recommendation, .recommendation-slider"
        ):
            item.decompose()
        for block in soup.select(".simple-block"):
            if re.search(r"вам будет полезно|похожие продукты|рекомендуем", block.get_text(" ", strip=True), re.I):
                block.decompose()
        heading = soup.find("h1")
        title = clean(heading.get_text(" ", strip=True)) if heading else ""
        if not title and soup.title:
            title = clean(soup.title.get_text()).split("|")[0].strip()
        root: Tag | BeautifulSoup = soup
        mode = "soft"
        for selector in self.selectors:
            found = soup.select_one(selector)
            if found and len(clean(found.get_text(" ", strip=True))) >= 40:
                root = found
                mode = "selectors"
                break
        if mode == "soft":
            logger.warning("selector_broken url=%s fallback=body", url)
            root = soup.body or soup
        raw_lines = [clean(line) for line in root.get_text("\n", strip=True).splitlines()]
        lines = [line for line in raw_lines if line]
        rows = self._rows(root)
        row_lines = [f"{label}: {value}" for label, value in rows]
        text = "\n".join(dict.fromkeys(lines + row_lines))
        if not title or len(text) < 40 or re.search(
            r"captcha|access denied|доступ запрещен|проверка браузера", title, re.I
        ):
            raise ValueError("No product content: missing heading, empty page, or access challenge")

        params: dict[str, Fact] = {}
        for key, pattern in self.keywords.items():
            evidence: list[str] = []
            for label, value in rows:
                label_match = re.search(pattern, label, re.I)
                value_match = re.search(pattern, value, re.I)
                if key == "валюта":
                    # A currency fact must come from its label. A ruble sign
                    # in a neighbouring amount is not evidence of currency.
                    match = bool(label_match)
                elif key == "ставка":
                    unrelated = r"пск|полная стоимость|кешбэк|комисси|пеня|штраф"
                    match = bool(label_match) or (
                        self.category == "deposits"
                        and bool(value_match)
                        and not re.search(unrelated, label, re.I)
                    )
                else:
                    match = bool(label_match or value_match)
                if match:
                    excerpt = f"{label}: {value}"
                    if len(excerpt) <= 1700 and excerpt not in evidence:
                        evidence.append(excerpt)
            if not evidence:
                for line in lines:
                    if re.search(pattern, line, re.I) and len(line) <= 550 and line not in evidence:
                        evidence.append(line)
                    if len(evidence) >= 2:
                        break
            if evidence:
                params[key] = Fact(value="\n".join(evidence[:8]), source_url=url)
        if not params:
            raise ValueError("No detailed conditions found; keeping the previous snapshot")
        summary = description or next(
            (line for line in lines if line != title and 30 <= len(line) <= 450),
            next(iter(params.values())).value,
        )
        return Product(
            product_name=title[:240],
            category=self.category,
            source_url=url,
            summary=Fact(value=summary[:1800], source_url=url),
            params=params,
            text=text,
            fetched_at=datetime.now(UTC),
            parser_mode=mode,
        )
