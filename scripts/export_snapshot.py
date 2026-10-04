"""Export validated parsed products for a reproducible first run."""
from __future__ import annotations

import json

from psb_assistant.cache import Cache
from psb_assistant.config import Settings


def main() -> None:
    settings = Settings.from_env()
    products = Cache(settings.cache_path).products()
    if not products:
        raise SystemExit("No parsed products in the cache; run the crawler first.")
    settings.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    settings.snapshot_path.write_text(
        json.dumps([product.model_dump(mode="json") for product in products], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Exported {len(products)} products to {settings.snapshot_path}")


if __name__ == "__main__":
    main()
