from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from psb_assistant.cache import TTL, Cache
from psb_assistant.config import Settings
from psb_assistant.llm import BaseLLMClient, ContentBlocked, LLMUnavailable, make_client
from psb_assistant.models import Answer, ComparisonInsight, GeneratedAnswer, Product, ProductAnswer
from psb_assistant.search import search

logger = logging.getLogger(__name__)
PROMPTS = Path(__file__).parent / "prompts"
SYSTEM = (PROMPTS / "system.txt").read_text(encoding="utf-8")
RETRY = (PROMPTS / "retry.txt").read_text(encoding="utf-8")
NOTICE = "Ниже — выдержки из условий банка. Для выбора нужны сумма, срок и требования к снятию."


def comparison_details(sources: list[Product]) -> tuple[list[ComparisonInsight], list[str]]:
    """Build a conservative, evidence-linked comparison without inventing a winner."""
    insights: list[ComparisonInsight] = []
    all_keys = list(dict.fromkeys(key for product in sources for key in product.params))
    explanations = {
        "ставка": "Ставки приведены вместе с исходными сроками, суммами и условиями; максимальное значение нельзя считать гарантированным для любой заявки.",
        "полная стоимость кредита": "ПСК показывает отдельный диапазон полной стоимости кредита и не равна рекламной ставке.",
        "срок": "Сроки различаются, поэтому сравнивать только проценты без выбранного срока некорректно.",
        "валюта": "Валюта определяет базу расчета; рублевые и валютные значения нельзя складывать или сравнивать напрямую.",
        "снятие": "Условия снятия и комиссии влияют на доступность денег и итоговый результат.",
        "пополнение": "Возможность пополнения меняет сценарий регулярных накоплений.",
        "кешбэк": "Кешбэк зависит от регистрации, категорий и партнеров; это отдельная выгода от процентной ставки.",
    }
    for key in all_keys:
        evidence = {p.product_name: p.params[key] for p in sources if key in p.params}
        values = {fact.value for fact in evidence.values()}
        if len(evidence) >= 2 and len(values) > 1:
            insights.append(
                ComparisonInsight(
                    title=key.capitalize(),
                    explanation=explanations.get(
                        key, "Параметр отличается между выбранными продуктами; его нужно сопоставить с вашей суммой и целью."
                    ),
                    evidence=evidence,
                )
            )
    clarifications = [
        "Какую сумму вы планируете разместить или получить?",
        "На какой срок нужен продукт?",
        "В какой валюте вы будете вносить деньги и хотите получить результат?",
        "Нужно ли пополнять продукт или снимать деньги до окончания срока?",
    ]
    if len({p.category for p in sources}) > 1:
        clarifications.insert(0, "Какова цель: накопление, кредитование или повседневные платежи?")
    return insights[:8], clarifications


def product_answer(product: Product) -> ProductAnswer:
    return ProductAnswer(
        product_name=product.product_name,
        source_url=product.source_url,
        summary=product.summary,
        params=product.params,
        risk_warning="Проверьте полные условия на странице банка.",
    )


def validate_grounding(raw: str, sources: list[Product]) -> GeneratedAnswer:
    answer = GeneratedAnswer.model_validate_json(raw)
    index = {product.source_url: product for product in sources}
    seen: set[str] = set()
    for item in answer.products:
        source = index.get(item.source_url)
        if source is None or item.source_url in seen:
            raise ValueError("Unknown or duplicate source")
        seen.add(item.source_url)
        if item.product_name != source.product_name or item.summary != source.summary:
            raise ValueError("Product name or summary not grounded")
        if not item.params:
            raise ValueError("Product must include sourced conditions")
        for key, fact in item.params.items():
            if key not in source.params or fact != source.params[key]:
                raise ValueError("Fact is not present in this source snapshot")
    return answer


def canonicalize_generation(raw: str, sources: list[Product]) -> GeneratedAnswer:
    """Use the model only as a source selector, never as a fact formatter.

    Some providers normalize table cells (for example, joining a rate row with
    its header). The selected URL and product name still have to match exactly;
    every displayed fact is then projected from our verified snapshot.
    """
    generated = GeneratedAnswer.model_validate_json(raw)
    index = {product.source_url: product for product in sources}
    seen: set[str] = set()
    projected: list[ProductAnswer] = []
    for item in generated.products:
        source = index.get(item.source_url)
        if source is None or item.source_url in seen:
            raise ValueError("Unknown or duplicate source")
        if item.product_name != source.product_name:
            raise ValueError("Product name is not grounded")
        seen.add(item.source_url)
        projected.append(product_answer(source))
    if not projected:
        raise ValueError("No selected sources")
    return GeneratedAnswer(products=projected)


class Assistant:
    def __init__(
        self,
        cache: Cache,
        settings: Settings,
        primary: BaseLLMClient | None = None,
        fallback: BaseLLMClient | None = None,
    ) -> None:
        self.cache = cache
        self.settings = settings
        self.primary = primary if primary is not None else make_client(settings.llm_provider, settings)
        self.fallback = (
            fallback if fallback is not None else make_client(settings.fallback_provider, settings)
        )

    def ask(self, query: str) -> Answer:
        mode = "compare" if re.search(r"сравн|выгоднее|лучше|или|разниц", query, re.I) else "search"
        sources = search(self.cache.products(), query)
        if not sources:
            _, clarifications = comparison_details([])
            return Answer(
                status="no_data",
                mode=mode,
                provider="none",
                message="В сохраненных страницах нет подтвержденных данных по этому запросу. Обновите каталог или уточните льготные условия в отделении банка.",
                clarifications=clarifications if mode == "compare" else [],
            )
        if mode == "compare" and len(sources) < 2:
            _, clarifications = comparison_details(sources)
            return Answer(
                status="no_data",
                mode=mode,
                provider="none",
                products=[product_answer(sources[0])],
                message="Найден только один продукт. Для сравнения нужны подтвержденные данные еще хотя бы об одном.",
                clarifications=clarifications,
            )
        return self.answer_sources(sources, query, mode)

    def compare(self, urls: list[str]) -> Answer:
        if len(set(urls)) != len(urls):
            return Answer(
                status="error", mode="compare", provider="none", message="Выберите 2–3 разных продукта."
            )
        index = {product.source_url: product for product in self.cache.products()}
        if any(url not in index for url in urls):
            return Answer(
                status="no_data",
                mode="compare",
                provider="none",
                message="Один из продуктов отсутствует в проверенной базе.",
            )
        sources = [index[url] for url in urls]
        # Manual comparison preserves all user-selected products and their original facts.
        return self.decorate(
            Answer(
                status="ok",
                mode="compare",
                message=NOTICE,
                provider="extractive",
                products=[product_answer(p) for p in sources],
            ),
            sources,
        )

    def answer_sources(self, sources: list[Product], query: str, mode: str) -> Answer:
        if self.primary is None:
            return self.extractive(sources, mode)
        user = json.dumps(
            {
                "query": query,
                "schema": GeneratedAnswer.model_json_schema(),
                "SOURCES": [product_answer(p).model_dump() for p in sources],
            },
            ensure_ascii=False,
        )
        for client in (self.primary, self.fallback):
            if client is None:
                break
            for attempt in range(3):
                try:
                    raw = client.generate(
                        SYSTEM, user + ("\n" + RETRY if attempt else ""), 0.0 if attempt else 0.2
                    )
                    # Empty/refusal responses from any adapter must trigger failover.
                    from psb_assistant.llm import checked_content

                    checked = checked_content(raw)
                    try:
                        generated = validate_grounding(checked, sources)
                    except ValueError:
                        if client.name not in {"gigachat", "yandex"}:
                            raise
                        # Provider output remains schema-validated; only its
                        # formatting of facts is discarded in favour of the
                        # exact server snapshot.
                        logger.warning("llm_fact_projection provider=%s", client.name)
                        generated = canonicalize_generation(checked, sources)
                    if mode == "compare" and len(generated.products) < 2:
                        raise ValueError("Comparison requires 2–3 products")
                    result = Answer(
                        status="ok" if client is self.primary else "fallback",
                        mode=mode,
                        message=NOTICE,
                        products=generated.products,
                        provider=client.name,
                    )
                    return self.decorate(result, sources)
                except (ContentBlocked, LLMUnavailable) as exc:
                    logger.warning(
                        "llm_blocked_or_unavailable provider=%s reason=%s", client.name, type(exc).__name__
                    )
                    break
                except (ValidationError, ValueError):
                    logger.warning("llm_validation_failed provider=%s attempt=%s", client.name, attempt + 1)
                    if attempt == 2:
                        return Answer(
                            status="error",
                            mode=mode,
                            provider=client.name,
                            message="Ответ модели не прошел проверку после двух повторных запросов. Недостоверные данные скрыты; используйте каталог и ручное сравнение.",
                        )
        result = self.extractive(sources, mode)
        result.status = "fallback"
        result.warnings.append(
            "Модель недоступна или отклонила запрос. Показаны сохраненные выдержки из источников; льготные условия уточните в отделении банка."
        )
        return result

    def extractive(self, sources: list[Product], mode: str) -> Answer:
        result = Answer(
            status="ok",
            mode=mode,
            message=NOTICE,
            provider="extractive",
            products=[product_answer(p) for p in sources[:3]],
        )
        return self.decorate(result, sources)

    def decorate(self, answer: Answer, sources: list[Product]) -> Answer:
        selected = {p.source_url for p in answer.products}
        for product in sources:
            if product.source_url not in selected:
                continue
            answer.fetched_at[product.source_url] = product.fetched_at.isoformat()
            if (datetime.now(UTC) - product.fetched_at).total_seconds() >= TTL:
                answer.warnings.append(
                    f"Данные старше 24 часов: {product.product_name}. Дата загрузки отображается у продукта."
                )
        if answer.mode == "compare":
            answer.insights, answer.clarifications = comparison_details(sources)
            answer.warnings.append(
                "Проценты по продуктам в разных валютах нельзя напрямую сравнивать без учета конвертации и изменения курса. Итоговая выгода без дополнительных данных не рассчитана."
            )
        return answer
