from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cache_path: Path = Path("data/cache.sqlite3")
    snapshot_path: Path = Path("artifacts/products.json")
    llm_provider: str = "extractive"
    fallback_provider: str = "extractive"
    openai_key: str = Field(default="", repr=False, exclude=True)
    openai_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen2.5:7b"
    gigachat_credentials: str = Field(default="", repr=False, exclude=True)
    gigachat_url: str = "https://api.giga.chat/v1"
    gigachat_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-3-Ultra"
    yandex_key: str = Field(default="", repr=False, exclude=True)
    yandex_folder_id: str = ""
    yandex_url: str = "https://ai.api.cloud.yandex.net/v1"
    yandex_model: str = "yandexgpt-5.1"
    telegram_token: str = Field(default="", repr=False, exclude=True)
    telegram_poll_timeout: int = Field(default=25, ge=1, le=50)
    llm_timeout: float = Field(default=45, ge=1, le=180)
    crawl_delay: float = Field(default=2, ge=1)
    auto_crawl: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        return cls(
            cache_path=Path(os.getenv("CACHE_PATH", "data/cache.sqlite3")),
            snapshot_path=Path(os.getenv("SNAPSHOT_PATH", "artifacts/products.json")),
            llm_provider=os.getenv("LLM_PROVIDER", "extractive"),
            fallback_provider=os.getenv("LLM_FALLBACK_PROVIDER", "extractive"),
            openai_key=os.getenv("OPENAI_API_KEY", ""),
            openai_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            ollama_url=os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
            gigachat_credentials=os.getenv("GIGACHAT_CREDENTIALS", ""),
            gigachat_url=os.getenv("GIGACHAT_BASE_URL", "https://api.giga.chat/v1"),
            gigachat_auth_url=os.getenv("GIGACHAT_AUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"),
            gigachat_scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            gigachat_model=os.getenv("GIGACHAT_MODEL", "GigaChat-3-Ultra"),
            yandex_key=os.getenv("YANDEX_API_KEY", ""),
            yandex_folder_id=os.getenv("YANDEX_FOLDER_ID", ""),
            yandex_url=os.getenv("YANDEX_BASE_URL", "https://ai.api.cloud.yandex.net/v1"),
            yandex_model=os.getenv("YANDEX_MODEL", "yandexgpt-5.1"),
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_poll_timeout=int(os.getenv("TELEGRAM_POLL_TIMEOUT", "25")),
            llm_timeout=float(os.getenv("LLM_TIMEOUT", "45")),
            crawl_delay=float(os.getenv("CRAWL_DELAY", "2")),
            auto_crawl=os.getenv("AUTO_CRAWL", "true").lower() == "true",
        )
