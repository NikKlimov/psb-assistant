from __future__ import annotations

import argparse
import json
from dataclasses import asdict

import uvicorn

from psb_assistant.cache import Cache
from psb_assistant.config import Settings
from psb_assistant.crawler import Crawler
from psb_assistant.http import PoliteHTTP
from psb_assistant.logging_config import configure_logging
from psb_assistant.service import Assistant


def main() -> None:
    parser = argparse.ArgumentParser(description="PSB product assistant")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    crawl = commands.add_parser("crawl")
    crawl.add_argument("--force-update", action="store_true")
    crawl.add_argument("--max-per-category", type=int, choices=range(1, 13), default=8)
    ask = commands.add_parser("ask")
    ask.add_argument("query")
    args = parser.parse_args()
    settings = Settings.from_env()
    configure_logging()
    if args.command == "serve":
        from psb_assistant.app import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port)
    else:
        cache = Cache(settings.cache_path)
        seeded = cache.seed_products(settings.snapshot_path)
        if seeded:
            print(json.dumps({"snapshot_loaded": seeded}, ensure_ascii=False))
        if args.command == "crawl":
            report = Crawler(cache, PoliteHTTP(cache, settings.crawl_delay)).run(
                force=args.force_update, max_per_category=args.max_per_category
            )
            print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
            if not all(report.categories.values()):
                raise SystemExit(1)
        else:
            print(Assistant(cache, settings).ask(args.query).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
