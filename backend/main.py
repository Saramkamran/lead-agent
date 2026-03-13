import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, campaigns, conversations, health, leads, webhooks
from app.jobs.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_scheduler()
    logger.info("Application startup complete")
    yield
    await stop_scheduler()
    logger.info("Application shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Lead Agent API",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = round((time.time() - start) * 1000)
        logger.info(
            "%s %s → %s (%dms)",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled error: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "code": "INTERNAL_ERROR"},
        )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(leads.router)
    app.include_router(campaigns.router)
    app.include_router(webhooks.router)
    app.include_router(conversations.router)

    return app


app = create_app()
