from __future__ import annotations

import re

from psb_assistant.models import Product

STOP = {
    "какой",
    "какая",
    "какие",
    "для",
    "мне",
    "что",
    "или",
    "как",
    "есть",
    "банк",
    "псб",
    "самый",
    "выгоднее",
    "лучше",
    "сравни",
    "сравнить",
    "покажи",
    "нужен",
    "найди",
}
SOCIAL = {
    "svo": (
        r"\bсво\b|военн.*операц|участник.*боев|ветеран",
        r"\bсво\b|свои|специальн.*военн|ветеран|боев.*действ",
    ),
    "pension": (r"пенсион", r"пенсион"),
    "east": (r"дальн.*восток|дальневост", r"дальн.*восток|дальневост"),
}
CATEGORIES = {
    "deposits": r"вклад|счет|счёт|накопит|юан",
    "loans": r"кредит|ипотек|займ",
    "cards": r"карт|к[еэ]шб[еэ]к",
}


def tokens(text: str) -> set[str]:
    return {
        token[:6]
        for token in re.findall(r"[а-яёa-z0-9]+", text.lower().replace("ё", "е"))
        if len(token) > 2 and token not in STOP
    }


def search(products: list[Product], query: str, limit: int = 6) -> list[Product]:
    terms = tokens(query)
    wanted = {category for category, pattern in CATEGORIES.items() if re.search(pattern, query, re.I)}
    comparing = bool(re.search(r"сравн|выгоднее|лучше|или|разниц", query, re.I))
    social = [evidence for pattern, evidence in SOCIAL.values() if re.search(pattern, query, re.I)]
    # In an explicit "A или B" comparison each phrase is an independent
    # product request. Do not force the social filter from phrase A onto B.
    if comparing and re.search(r"\s+или\s+", query, re.I):
        social = []
    yuan = bool(re.search(r"юан|\bCNY\b", query, re.I))
    ranked: list[tuple[float, Product]] = []
    for product in products:
        corpus = product.product_name + "\n" + product.text
        if wanted and product.category not in wanted:
            continue
        if social and not all(re.search(pattern, corpus, re.I) for pattern in social):
            continue
        # In a comparison, a RUB account may be included alongside a CNY deposit.
        if yuan and not comparing and not re.search(r"юан|\bCNY\b", corpus, re.I):
            continue
        name_terms = tokens(product.product_name)
        corpus_terms = tokens(corpus)
        score = 4 * len(terms & name_terms) + len(terms & corpus_terms)
        if wanted:
            score += 2
        if yuan and re.search(r"юан|\bCNY\b", product.product_name, re.I):
            score += 10
        if re.search(r"накопит", query, re.I) and re.search(r"накопит", product.product_name, re.I):
            score += 10
        if score > 0:
            ranked.append((score, product))
    ranked.sort(key=lambda item: (-item[0], item[1].product_name))
    alternatives = re.split(r"\s+или\s+", query, flags=re.I)
    if comparing and len(alternatives) >= 2:
        selected: list[Product] = []
        for phrase in alternatives:
            phrase_terms = tokens(phrase)
            candidates = []
            for product in products:
                if wanted and product.category not in wanted:
                    continue
                name_score = len(phrase_terms & tokens(product.product_name))
                corpus_score = len(phrase_terms & tokens(product.product_name + "\n" + product.text))
                # An explicit alternative must resolve to the product title;
                # a generic corpus hit (for example any page mentioning
                # "вклад") would otherwise substitute an unrelated product.
                if name_score:
                    candidates.append((name_score * 10 + corpus_score, product))
            candidates.sort(key=lambda item: (-item[0], item[1].product_name))
            if candidates and candidates[0][1] not in selected:
                selected.append(candidates[0][1])
        if selected:
            return selected[:limit]
    # Compare across requested categories before taking further similar products.
    if comparing and len(wanted) > 1:
        selected: list[Product] = []
        for category in sorted(wanted):
            match = next((product for _, product in ranked if product.category == category), None)
            if match:
                selected.append(match)
        selected.extend(product for _, product in ranked if product not in selected)
        return selected[:limit]
    return [product for _, product in ranked[:limit]]
