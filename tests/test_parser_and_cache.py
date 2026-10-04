from __future__ import annotations

import json
import sqlite3
import time

from psb_assistant.cache import Cache
from psb_assistant.crawler import Crawler
from psb_assistant.models import Fact
from psb_assistant.parsers.deposits import DepositParser


def test_deposit_parser_uses_soft_fallback_and_quotes_conditions() -> None:
    html = """
    <html><head><title>Вклад «В юанях» | ПСБ</title></head><body>
      <h1>Вклад «В юанях»</h1>
      <div class="new-layout"><p>Процентная ставка от 2,5% до 3,5%</p>
      <p>Срок от 91 до 731 дня. Минимальная сумма 10 000 юаней.</p></div>
    </body></html>
    """
    url = "https://www.psbank.ru/personal/saving/yuan"
    product = DepositParser().parse(html, url)
    assert product.parser_mode == "soft"
    assert product.product_name == "Вклад «В юанях»"
    assert product.params["ставка"].source_url == url
    assert "3,5%" in product.params["ставка"].value


def test_parser_limits_evidence_to_product_content() -> None:
    html = """
    <html><body><nav>Другой вклад и бесплатный звонок</nav>
      <div class="page__content"><h1>Вклад «В юанях»</h1>
        <div class="inner-head-banner__description">Для безопасного хранения накоплений</div>
        <table><tr><th>Валюта депозита</th><td>Китайские юани</td></tr>
        <tr><th>Пополнение</th><td>Не предусмотрено</td></tr></table>
      </div><aside>Вам будет полезно: другая карта</aside>
    </body></html>
    """
    product = DepositParser().parse(html, "https://www.psbank.ru/personal/saving/yuan")
    assert product.parser_mode == "selectors"
    assert "Китайские юани" in product.params["валюта"].value
    assert "другая карта" not in product.text


def test_cache_expires_after_24_hours(tmp_path) -> None:
    cache = Cache(tmp_path / "cache.sqlite3")
    url = "https://www.psbank.ru/personal/saving/yuan"
    cache.put(url, "<html>")
    assert cache.get(url) is not None
    with sqlite3.connect(cache.path) as db:
        db.execute("UPDATE pages SET fetched=? WHERE url=?", (time.time() - 24 * 60 * 60 - 1, url))
    assert cache.get(url) is None
    assert cache.get(url, fresh_only=False) is not None


def test_cache_seeds_published_snapshot_only_when_empty(tmp_path) -> None:
    product = DepositParser().parse(
        "<h1>Вклад в юанях</h1><div class='page__content'>Подробные условия продукта для безопасного хранения накоплений. Процентная ставка 10%.</div>",
        "https://www.psbank.ru/personal/saving/yuan",
    )
    snapshot = tmp_path / "products.json"
    snapshot.write_text(json.dumps([product.model_dump(mode="json")]), encoding="utf-8")
    cache = Cache(tmp_path / "cache.sqlite3")
    assert cache.seed_products(snapshot) == 1
    assert len(cache.products()) == 1
    assert cache.seed_products(snapshot) == 0


def test_fact_rejects_non_psbank_source() -> None:
    try:
        Fact(value="10%", source_url="https://example.com/product")
    except ValueError as error:
        assert "psbank.ru" in str(error)
    else:
        raise AssertionError("External source URL must be rejected")


def test_crawler_prioritizes_card_products_over_service_pages() -> None:
    html = """
    <a href="/personal/cards/offers">Offers</a>
    <a href="/personal/debetcards/yourcashback">Your cashback</a>
    <a href="/personal/debetcards/residentcard">Resident card</a>
    <a href="/personal/cards/rules">Rules</a>
    """
    urls = Crawler.links(html, "https://www.psbank.ru/personal/cards", "cards")
    assert urls == [
        "https://www.psbank.ru/personal/debetcards/yourcashback",
        "https://www.psbank.ru/personal/debetcards/residentcard",
    ]
