"""Small dependency-free Telegram long-polling adapter for the assistant."""
from __future__ import annotations

import html
import logging
import time
from typing import Any

import requests

from psb_assistant.config import Settings
from psb_assistant.models import Answer
from psb_assistant.service import Assistant

logger = logging.getLogger(__name__)


class TelegramAPIError(RuntimeError):
    pass


class TelegramBot:
    def __init__(self, assistant: Assistant, settings: Settings) -> None:
        if not settings.telegram_token.strip():
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured")
        self.assistant = assistant
        self.settings = settings
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_token}"
        self.offset = 0

    def api(self, method: str, payload: dict[str, Any]) -> Any:
        response = requests.post(
            f"{self.base_url}/{method}",
            json=payload,
            timeout=(8, self.settings.llm_timeout + self.settings.telegram_poll_timeout),
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise TelegramAPIError(str(body.get("description", "Telegram API error")))
        return body.get("result")

    def run(self) -> None:
        self.api("deleteWebhook", {"drop_pending_updates": True})
        me = self.api("getMe", {})
        logger.info("telegram_started username=%s", me.get("username"))
        while True:
            try:
                updates = self.api(
                    "getUpdates",
                    {"offset": self.offset, "timeout": self.settings.telegram_poll_timeout, "allowed_updates": ["message"]},
                )
                for update in updates or []:
                    self.offset = max(self.offset, int(update["update_id"]) + 1)
                    self.handle_update(update)
            except (requests.RequestException, TelegramAPIError, KeyError, TypeError, ValueError) as exc:
                logger.warning("telegram_poll_failed reason=%s", type(exc).__name__)
                time.sleep(3)

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = message.get("text")
        if chat_id is None or not isinstance(text, str):
            return
        command = text.strip().lower()
        if command in {"/start", "/help"}:
            answer = (
                "Я ищу продукты ПСБ по публичным страницам банка.\n\n"
                "Напишите вопрос, например:\n"
                "• Какая ставка по вкладу в юанях?\n"
                "• Что выгоднее: вклад или накопительный счёт?\n"
                "• Какие условия для Дальнего Востока?"
            )
        else:
            answer = render_answer(self.assistant.ask(text))
        self.api("sendMessage", {"chat_id": chat_id, "text": answer, "parse_mode": "HTML", "disable_web_page_preview": True})


def render_answer(answer: Answer) -> str:
    """Render only validated answer fields; all dynamic text is HTML-escaped."""
    parts = [f"<b>{html.escape(answer.message)}</b>"]
    for product in answer.products:
        parts.append(f"\n<b>{html.escape(product.product_name)}</b>")
        parts.append(f'<a href="{html.escape(product.source_url, quote=True)}">Источник ПСБ</a>')
        parts.append(html.escape(product.summary.value))
        for key, fact in list(product.params.items())[:8]:
            parts.append(f"<b>{html.escape(key)}:</b> {html.escape(fact.value)}")
    if answer.insights:
        parts.append("\n<b>Сравнение</b>")
        for insight in answer.insights:
            parts.append(f"<b>{html.escape(insight.title)}:</b> {html.escape(insight.explanation)}")
    if answer.clarifications:
        parts.append("\n<b>Чтобы сравнить точнее:</b>")
        parts.extend(f"• {html.escape(question)}" for question in answer.clarifications)
    if answer.warnings:
        parts.append("\n<b>Предупреждение:</b> " + html.escape(" ".join(answer.warnings)))
    text = "\n".join(parts)
    return text if len(text) <= 4096 else text[:4080] + "…"
