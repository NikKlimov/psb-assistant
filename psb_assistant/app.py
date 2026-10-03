from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from psb_assistant.cache import Cache
from psb_assistant.config import Settings
from psb_assistant.crawler import Crawler, CrawlReport
from psb_assistant.http import PoliteHTTP
from psb_assistant.logging_config import configure_logging
from psb_assistant.models import Answer, AskRequest, CompareRequest, Product
from psb_assistant.search import search
from psb_assistant.service import Assistant

logger = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    force: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    cache = Cache(settings.cache_path)
    crawler = Crawler(cache, PoliteHTTP(cache, settings.crawl_delay))
    assistant = Assistant(cache, settings)
    refresh_lock = threading.Lock()
    crawl_state: dict[str, object] = {"running": False, "last_report": None}

    def refresh(force: bool = False) -> CrawlReport:
        if not refresh_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Обновление уже выполняется")
        crawl_state["running"] = True
        try:
            report = crawler.run(force=force)
            crawl_state["last_report"] = asdict(report)
            return report
        finally:
            crawl_state["running"] = False
            refresh_lock.release()

    async def startup_refresh() -> None:
        try:
            await asyncio.to_thread(refresh)
        except Exception:
            logger.exception("startup_refresh_failed")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        task = asyncio.create_task(startup_refresh()) if settings.auto_crawl else None
        yield
        if task:
            await task

    app = FastAPI(title="ПСБ · Ассистент по продуктам", version="0.1.0", lifespan=lifespan)
    app.state.cache = cache
    app.state.assistant = assistant
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, object]:
        coverage = crawler.coverage()
        return {
            "status": "ok",
            "provider": settings.llm_provider,
            "products": sum(coverage.values()),
            "coverage": coverage,
            "ready": all(count >= 1 for count in coverage.values()),
            **crawl_state,
        }

    @app.get("/api/products", response_model=list[Product])
    def products(q: str = "") -> list[Product]:
        if len(q) > 1500:
            raise HTTPException(status_code=422, detail="Слишком длинный запрос")
        records = cache.products()
        return search(records, q, limit=30) if q else records

    @app.post("/api/ask", response_model=Answer)
    def ask(request: AskRequest) -> Answer:
        return assistant.ask(request.query.strip())

    @app.post("/api/compare", response_model=Answer)
    def compare(request: CompareRequest) -> Answer:
        return assistant.compare(request.urls)

    @app.post("/api/refresh")
    def update(request: RefreshRequest) -> dict[str, object]:
        return asdict(refresh(request.force))

    return app
