import asyncio
import logging
from typing import Any

from prisma import Json, Prisma

logger = logging.getLogger(__name__)

INITIAL_SOURCES: list[dict[str, Any]] = [
    {
        "name": "almin7",
        "display_name": "Almin7 Scholarships",
        "base_url": "https://almin7.com",
        "api_endpoint": "/scholarship/",
        "method": "html",
        "pagination_config": {"per_page": 20, "limit": 50},
        "field_mapping": {},
        "is_active": True,
        "scrape_frequency": "daily",
    },
    {
        "name": "grabscholarship",
        "display_name": "GrabScholarships",
        "base_url": "https://grabscholarships.com",
        "api_endpoint": "/wp-json/wp/v2/posts",
        "method": "wordpress_api",
        "pagination_config": {"per_page": 20, "limit": 50},
        "field_mapping": {
            "title": "title.rendered",
            "content": "content.rendered",
            "excerpt": "excerpt.rendered",
            "url": "link",
            "date": "date",
        },
        "is_active": True,
        "scrape_frequency": "daily",
    },
    {
        "name": "scholars4dev",
        "display_name": "Scholars4Dev International Scholarships",
        "base_url": "https://www.scholars4dev.com",
        "api_endpoint": "/category/scholarships-list",
        "method": "html",
        "pagination_config": {"limit": 50},
        "field_mapping": {
            "title": "h2 a",
            "summary": "div.entry",
            "url": "h2 a[href]",
        },
        "is_active": True,
        "scrape_frequency": "daily",
    },
]


async def seed_sources(db: Prisma | None = None) -> list[Any]:
    """يضيف المصادر الافتراضية إلى جدول Source في قاعدة البيانات إذا لم تكن موجودة."""
    should_disconnect = False
    if db is None:
        db = Prisma()
        await db.connect()
        should_disconnect = True

    seeded = []
    try:
        for source_data in INITIAL_SOURCES:
            data = dict(source_data)
            data["pagination_config"] = Json(data["pagination_config"])
            data["field_mapping"] = Json(data["field_mapping"])

            existing = await db.source.find_unique(where={"name": data["name"]})
            if not existing:
                created = await db.source.create(data=data)  # type: ignore[arg-type]
                logger.info("Seeded source: %s (%s)", created.name, created.id)
                seeded.append(created)
            else:
                logger.info(
                    "Source already exists: %s (%s)", existing.name, existing.id
                )
                seeded.append(existing)
    finally:
        if should_disconnect and db.is_connected():
            await db.disconnect()

    return seeded


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed_sources())
