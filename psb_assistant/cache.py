from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from psb_assistant.models import Product

TTL = 24 * 60 * 60


class Cache:
    """Atomic disk snapshots; successful products survive failed refreshes."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, body TEXT NOT NULL, fetched REAL NOT NULL, product TEXT)"
            )

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=15)

    def get(self, url: str, *, fresh_only: bool = True) -> tuple[str, float, Product | None] | None:
        with self.connect() as db:
            row = db.execute("SELECT body, fetched, product FROM pages WHERE url=?", (url,)).fetchone()
        if not row or (fresh_only and time.time() - row[1] >= TTL):
            return None
        return row[0], row[1], Product.model_validate_json(row[2]) if row[2] else None

    def put(self, url: str, body: str, product: Product | None = None) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?)",
                (url, body, time.time(), product.model_dump_json() if product else None),
            )

    def replace_product(self, url: str, product: Product) -> None:
        """Replace parsed data while preserving the original fetch timestamp."""
        with self.connect() as db:
            db.execute("UPDATE pages SET product=? WHERE url=?", (product.model_dump_json(), url))

    def clear_product(self, url: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE pages SET product=NULL WHERE url=?", (url,))

    def products(self) -> list[Product]:
        with self.connect() as db:
            rows = db.execute("SELECT product FROM pages WHERE product IS NOT NULL ORDER BY url").fetchall()
        return [Product.model_validate_json(row[0]) for row in rows]

    def seed_products(self, snapshot_path: Path) -> int:
        """Load a published parsed snapshot when the persistent volume is empty."""
        if self.products() or not snapshot_path.exists():
            return 0
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        products = [Product.model_validate_json(json.dumps(item, ensure_ascii=False)) for item in payload]
        with self.connect() as db:
            for product in products:
                db.execute(
                    "INSERT OR IGNORE INTO pages VALUES (?, ?, ?, ?)",
                    (
                        product.source_url,
                        "",
                        product.fetched_at.timestamp(),
                        product.model_dump_json(),
                    ),
                )
        return len(products)
