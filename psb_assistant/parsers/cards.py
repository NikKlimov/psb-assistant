from psb_assistant.models import Category
from psb_assistant.parsers.base import BaseParser


class CardParser(BaseParser):
    category: Category = "cards"
    keywords = {
        "кешбэк": r"к[еэ]шб[еэ]к|cashback|бонус|балл",
        "комиссии": r"комисси|обслуживан|бесплатн|стоимост",
        "срок": r"срок|льготн.*период|\d+\s*дн",
        "валюта": r"валют|рубл|RUB|₽",
        "снятие": r"сняти|наличн",
        "условия": r"пенсион|СВО|специальн.*военн|военнослуж|зарплат",
    }
