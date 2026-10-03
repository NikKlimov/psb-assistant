from __future__ import annotations

from datetime import UTC, datetime

from psb_assistant.cache import Cache
from psb_assistant.config import Settings
from psb_assistant.llm import BaseLLMClient, ContentBlocked
from psb_assistant.models import Fact, Product
from psb_assistant.service import (
    Assistant,
    canonicalize_generation,
    comparison_details,
    product_answer,
    validate_grounding,
)


class BlockedClient(BaseLLMClient):
    name = "primary"

    def generate(self, system: str, user: str, temperature: float) -> str:
        raise ContentBlocked("provider filter")


class WorkingClient(BaseLLMClient):
    name = "backup"

    def __init__(self, product: Product) -> None:
        self.product = product

    def generate(self, system: str, user: str, temperature: float) -> str:
        return '{"products": [' + product_answer(self.product).model_dump_json() + "]}"


def sample_product() -> Product:
    url = "https://www.psbank.ru/personal/saving/yuan"
    fact = Fact(value="От 2,5% до 3,5%", source_url=url)
    return Product(
        product_name="Вклад «В юанях»",
        category="deposits",
        source_url=url,
        summary=fact,
        params={"ставка": fact},
        text="Вклад в юанях ставка",
        fetched_at=datetime.now(UTC),
        parser_mode="soft",
    )


def test_grounding_rejects_model_fact_that_is_not_in_snapshot() -> None:
    product = sample_product()
    raw = (
        '{"products": [{"product_name": "Вклад «В юанях»", "source_url": "'
        + product.source_url
        + '", "summary": {"value": "Подмена", "source_url": "'
        + product.source_url
        + '"}, "params": {"ставка": {"value": "99%", "source_url": "'
        + product.source_url
        + '"}}, "risk_warning": null}]}'
    )
    try:
        validate_grounding(raw, [product])
    except ValueError as error:
        assert "grounded" in str(error).lower() or "present" in str(error).lower()
    else:
        raise AssertionError("Ungrounded model facts must be rejected")


def test_content_filter_switches_to_backup_client(tmp_path) -> None:
    product = sample_product()
    cache = Cache(tmp_path / "cache.sqlite3")
    cache.put(product.source_url, "html", product)
    settings = Settings(cache_path=tmp_path / "cache.sqlite3", auto_crawl=False)
    assistant = Assistant(cache, settings, primary=BlockedClient(), fallback=WorkingClient(product))
    answer = assistant.ask("вклад в юанях")
    assert answer.provider == "backup"
    assert answer.status == "fallback"
    assert answer.products[0].source_url == product.source_url


def test_comparison_returns_evidence_and_clarifying_questions() -> None:
    first = sample_product()
    second = first.model_copy(
        deep=True,
        update={
            "product_name": "Народный вклад",
            "source_url": "https://www.psbank.ru/personal/saving/narodnyy-vklad",
            "params": {"ставка": Fact(value="12%", source_url="https://www.psbank.ru/personal/saving/narodnyy-vklad")},
        },
    )
    insights, questions = comparison_details([first, second])
    assert insights and insights[0].evidence[first.product_name].value == "От 2,5% до 3,5%"
    assert any("сумму" in question for question in questions)


def test_provider_fact_projection_restores_exact_snapshot() -> None:
    product = sample_product()
    raw = '{"products": [' + product_answer(product).model_copy(update={"params": {"ставка": Fact(value="99%", source_url=product.source_url)}}).model_dump_json() + "]}"
    projected = canonicalize_generation(raw, [product])
    assert projected.products[0].params["ставка"].value == "От 2,5% до 3,5%"
