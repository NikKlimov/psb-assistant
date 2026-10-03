from psb_assistant.models import Category
from psb_assistant.parsers.base import BaseParser


class DepositParser(BaseParser):
    category: Category = "deposits"
    keywords = {
        "ставка": r"ставк|доходност|\d+[.,]?\d*\s*%",
        "срок": r"срок|\d+\s*(?:дн|месяц|лет|год)",
        "валюта": r"валют|юан|CNY|рубл|RUB|₽",
        "сумма": r"сумм|минимальн.*(?:взнос|остаток)",
        "пополнение": r"пополн",
        "снятие": r"сняти|досроч|расторжен",
        "условия": r"пенсион|СВО|специальн.*военн|военнослуж|капитализац|начислен|нов.*клиент",
    }
