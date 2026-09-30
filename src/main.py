import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.errors import register_ai_error_handlers
from src.api.routes.v1 import ai, health, scrape, webhook
from src.modules.core.config.settings import get_settings
from src.modules.core.database.prisma_client import connect, disconnect
from src.modules.infrastructure.llm.providers import close_llm_clients

settings = get_settings()

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """يفتح اتصال قاعدة البيانات عند الإقلاع ويغلقه عند الإيقاف."""
    await connect()
    logger.info("Service started in %s mode", settings.environment)
    yield
    await close_llm_clients()
    await disconnect()


app = FastAPI(
    title="Levora Python Service",
    version="0.1.0",
    lifespan=lifespan,
)

register_ai_error_handlers(app)

app.include_router(health.router)
app.include_router(scrape.router)
app.include_router(webhook.router)
app.include_router(ai.router)
