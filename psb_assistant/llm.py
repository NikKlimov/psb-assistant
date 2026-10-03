from __future__ import annotations

import json
import threading
import time
from abc import ABC, abstractmethod
from uuid import uuid4

import requests

from psb_assistant.config import Settings
from psb_assistant.models import GeneratedAnswer


class ContentBlocked(RuntimeError):
    pass


class LLMUnavailable(RuntimeError):
    pass


class ProviderHTTPError(LLMUnavailable):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Provider HTTP {status_code}")


class BaseLLMClient(ABC):
    name: str

    @abstractmethod
    def generate(self, system: str, user: str, temperature: float) -> str:
        """Return raw model JSON or raise an explicit provider error."""


def checked_content(content: object, *, refused: bool = False) -> str:
    if refused or not isinstance(content, str) or not content.strip():
        raise ContentBlocked("Empty response or explicit refusal")
    text = content.strip()
    # Do not treat a quoted source mentioning refusal as a model refusal.
    if not text.startswith("{") and any(
        term in text.lower()
        for term in (
            "не могу",
            "не могу ответить",
            "не могу помочь",
            "не могу обсуждать",
            "i cannot",
            "i can't",
            "отказываюсь",
            "запрос заблокирован",
            "нарушает правила",
            "не поддерживаю обсуждение",
        )
    ):
        raise ContentBlocked("Refusal text")
    return text


def post_json(
    url: str, payload: dict[str, object], timeout: float, headers: dict[str, str] | None = None
) -> dict[str, object]:
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=(8, timeout))
        return response_body(response)
    except requests.RequestException as exc:
        raise LLMUnavailable(type(exc).__name__) from exc


def response_body(response: requests.Response) -> dict[str, object]:
    try:
        body = response.json()
    except ValueError as exc:
        if not response.ok:
            raise ProviderHTTPError(response.status_code) from exc
        raise LLMUnavailable("Provider returned a non-JSON envelope") from exc
    if not response.ok:
        error = json.dumps(body, ensure_ascii=False).lower()
        if any(term in error for term in ("content_filter", "content_policy", "safety", "moderation", "blocked")):
            raise ContentBlocked("Provider content filter")
        # Never include a response body: it may echo credentials or request data.
        raise ProviderHTTPError(response.status_code)
    if not isinstance(body, dict):
        raise LLMUnavailable("Invalid provider envelope")
    return body


def completion_content(body: dict[str, object]) -> str:
    try:
        choice = body["choices"][0]  # type: ignore[index]
        message = choice["message"]
        if choice.get("finish_reason") == "length":
            raise LLMUnavailable("Provider truncated the JSON response")
        return checked_content(
            message.get("content"),
            refused=bool(message.get("refusal")) or choice.get("finish_reason") in ("content_filter", "blacklist"),
        )
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise LLMUnavailable("Malformed completion envelope") from exc


class GigaChatClient(BaseLLMClient):
    name = "gigachat"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._token = ""
        self._expires_at = 0.0
        self._token_lock = threading.Lock()

    def access_token(self) -> str:
        with self._token_lock:
            if self._token and time.time() < self._expires_at - 60:
                return self._token
            if not self.settings.gigachat_credentials:
                raise LLMUnavailable("GIGACHAT_CREDENTIALS is not configured")
            try:
                response = requests.post(
                    self.settings.gigachat_auth_url,
                    data={"scope": self.settings.gigachat_scope},
                    headers={
                        "Authorization": "Basic " + self.settings.gigachat_credentials,
                        "RqUID": str(uuid4()),
                        "Accept": "application/json",
                    },
                    timeout=(8, self.settings.llm_timeout),
                    allow_redirects=False,
                )
                body = response_body(response)
            except requests.RequestException as exc:
                raise LLMUnavailable(type(exc).__name__) from exc
            token, expiry = body.get("access_token"), body.get("expires_at")
            if not isinstance(token, str) or not token or not isinstance(expiry, (int, float)):
                raise LLMUnavailable("Malformed OAuth envelope")
            # GigaChat deployments return Unix milliseconds; accept seconds as
            # well, without persisting the short-lived token on disk.
            expires_at = expiry / 1000 if expiry > 100_000_000_000 else float(expiry)
            if expires_at <= time.time():
                raise LLMUnavailable("OAuth returned an expired token")
            self._token, self._expires_at = token, expires_at
            return token

    def generate(self, system: str, user: str, temperature: float) -> str:
        payload = {
            "model": self.settings.gigachat_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "stream": False,
            "max_tokens": 8192,
            "response_format": {
                "type": "json_schema", "schema": GeneratedAnswer.model_json_schema(), "strict": True,
            },
        }
        for attempt in range(2):
            token = self.access_token()
            try:
                body = post_json(
                    self.settings.gigachat_url.rstrip("/") + "/chat/completions",
                    payload, self.settings.llm_timeout, {"Authorization": "Bearer " + token},
                )
                return completion_content(body)
            except ProviderHTTPError as exc:
                if exc.status_code != 401 or attempt:
                    raise
                with self._token_lock:
                    if self._token == token:
                        self._token, self._expires_at = "", 0
        raise LLMUnavailable("GigaChat authentication failed")


class YandexGPTClient(BaseLLMClient):
    name = "yandex"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(self, system: str, user: str, temperature: float) -> str:
        if not self.settings.yandex_key or not self.settings.yandex_folder_id:
            raise LLMUnavailable("YANDEX_API_KEY and YANDEX_FOLDER_ID are required")
        model = self.settings.yandex_model
        if not model.startswith("gpt://"):
            model = f"gpt://{self.settings.yandex_folder_id}/{model}"
        body = post_json(
            self.settings.yandex_url.rstrip("/") + "/chat/completions",
            {
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": temperature,
                "stream": False,
                "max_tokens": 8192,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "product_answer", "schema": GeneratedAnswer.model_json_schema()},
                },
            },
            self.settings.llm_timeout,
            {"Authorization": "Api-Key " + self.settings.yandex_key, "OpenAI-Project": self.settings.yandex_folder_id},
        )
        return completion_content(body)


class OpenAIClient(BaseLLMClient):
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(self, system: str, user: str, temperature: float) -> str:
        if not self.settings.openai_key:
            raise LLMUnavailable("OPENAI_API_KEY is not configured")
        body = post_json(
            self.settings.openai_url.rstrip("/") + "/chat/completions",
            {
                "model": self.settings.openai_model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            },
            self.settings.llm_timeout,
            {"Authorization": "Bearer " + self.settings.openai_key},
        )
        try:
            choice = body["choices"][0]  # type: ignore[index]
            message = choice["message"]
            return checked_content(
                message.get("content"),
                refused=bool(message.get("refusal")) or choice.get("finish_reason") == "content_filter",
            )
        except (KeyError, TypeError, IndexError) as exc:
            raise LLMUnavailable("Malformed OpenAI envelope") from exc


class OllamaClient(BaseLLMClient):
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(self, system: str, user: str, temperature: float) -> str:
        body = post_json(
            self.settings.ollama_url.rstrip("/") + "/api/chat",
            {
                "model": self.settings.ollama_model,
                "stream": False,
                "format": "json",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": temperature},
            },
            self.settings.llm_timeout,
        )
        try:
            return checked_content(body["message"]["content"])  # type: ignore[index]
        except (KeyError, TypeError) as exc:
            raise LLMUnavailable("Malformed Ollama envelope") from exc


def make_client(name: str, settings: Settings) -> BaseLLMClient | None:
    if name == "extractive":
        return None
    if name == "openai":
        return OpenAIClient(settings)
    if name == "ollama":
        return OllamaClient(settings)
    if name == "gigachat":
        return GigaChatClient(settings)
    if name == "yandex":
        return YandexGPTClient(settings)
    raise ValueError("LLM_PROVIDER must be extractive, openai, ollama, gigachat or yandex")
