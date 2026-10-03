from psb_assistant.models import Category
from psb_assistant.parsers.base import BaseParser


class LoanParser(BaseParser):
    category: Category = "loans"
    keywords = {
        "ставка": r"ставк",
        "полная стоимость кредита": r"полная стоимость|ПСК",
        "срок": r"срок|\d+\s*(?:месяц|лет|год)",
        "сумма": r"сумм|лимит",
        "валюта": r"валют|рубл|RUB|₽",
        "комиссии": r"комисси|страхован",
        "условия": r"пенсион|СВО|специальн.*военн|военнослуж|дальневост|Дальн.*Восток|возраст|заемщик|заёмщик",
    }
