from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def bank_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.psbank.ru"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or "\\" in value
    ):
        raise ValueError("Only canonical public https://www.psbank.ru URLs are allowed")
    return value


SourceURL = Annotated[str, AfterValidator(bank_url)]
Category = Literal["deposits", "loans", "cards"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Fact(StrictModel):
    value: str = Field(min_length=1, max_length=1800)
    source_url: SourceURL


class Product(StrictModel):
    product_name: str = Field(min_length=1, max_length=240)
    category: Category
    source_url: SourceURL
    summary: Fact
    params: dict[str, Fact]
    text: str = Field(min_length=1)
    fetched_at: datetime
    parser_mode: Literal["selectors", "soft"]


class ProductAnswer(StrictModel):
    product_name: str = Field(min_length=1, max_length=240)
    source_url: SourceURL
    summary: Fact
    params: dict[str, Fact]
    risk_warning: Literal["Проверьте полные условия на странице банка."] | None


class GeneratedAnswer(StrictModel):
    products: list[ProductAnswer] = Field(min_length=1, max_length=3)


class ComparisonInsight(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, max_length=500)
    evidence: dict[str, Fact] = Field(default_factory=dict)


class Answer(StrictModel):
    status: Literal["ok", "fallback", "error", "no_data"]
    mode: Literal["search", "compare"]
    message: str
    products: list[ProductAnswer] = Field(default_factory=list)
    provider: str
    warnings: list[str] = Field(default_factory=list)
    fetched_at: dict[str, str] = Field(default_factory=dict)
    insights: list[ComparisonInsight] = Field(default_factory=list)
    clarifications: list[str] = Field(default_factory=list)


class AskRequest(StrictModel):
    query: str = Field(min_length=2, max_length=1500)


class CompareRequest(StrictModel):
    urls: list[SourceURL] = Field(min_length=2, max_length=3)
