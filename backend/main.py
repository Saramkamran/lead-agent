import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, campaigns, conversations, health, jobs, leads, outreach_accounts
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.services.email_service import poll_imap_account
from app.services.reply_handler import handle_reply

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_imap_task: asyncio.Task | None = None


async def _poll_all_imap_sources() -> None:
    """
    Long-running loop that polls the global IMAP account plus all active outreach accounts.
    Runs on every IMAP_POLL_INTERVAL_SECONDS tick.
    """
    from sqlalchemy import select
    from app.models.outreach_account import OutreachAccount
    from app.core.crypto import decrypt_secret

    logger.info("[IMAP] Multi-account polling loop started (interval: %ds)", settings.IMAP_POLL_INTERVAL_SECONDS)

    while True:
        tasks = []

        # Global IMAP account (env vars)
        if settings.IMAP_USER and settings.IMAP_PASS:
            tasks.append(poll_imap_account(
                creds={
                    "host": settings.IMAP_HOST,
                    "port": settings.IMAP_PORT,
                    "user": settings.IMAP_USER,
                    "pass": settings.IMAP_PASS,
                    "folder": settings.IMAP_REPLY_FOLDER,
                },
                handle_reply_callback=handle_reply,
            ))

        # Per-account IMAP (from DB)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(OutreachAccount).where(OutreachAccount.is_active.is_(True))
                )
                accounts = list(result.scalars().all())

            for account in accounts:
                try:
                    plain_pass = decrypt_secret(account.smtp_pass)
                except Exception:
                    continue

                # Skip if this account's email matches the global IMAP user (same mailbox, different hostname)
                if account.smtp_user.lower() == settings.IMAP_USER.lower():
                    continue

                tasks.append(poll_imap_account(
                    creds={
                        "host": account.imap_host,
                        "port": account.imap_port,
                        "user": account.smtp_user,
                        "pass": plain_pass,
                        "folder": settings.IMAP_REPLY_FOLDER,
                    },
                    handle_reply_callback=handle_reply,
                ))
        except Exception as e:
            logger.error("[IMAP] Failed to load outreach accounts for polling: %s", e)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        await asyncio.sleep(settings.IMAP_POLL_INTERVAL_SECONDS)


async def start_imap_poller() -> None:
    global _imap_task
    _imap_task = asyncio.create_task(_poll_all_imap_sources())
    logger.info("[IMAP] Poller task created")


async def stop_imap_poller() -> None:
    global _imap_task
    if _imap_task:
        _imap_task.cancel()
        try:
            await _imap_task
        except asyncio.CancelledError:
            pass
        logger.info("[IMAP] Poller task stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_scheduler()
    await start_imap_poller()
    logger.info("Application startup complete")
    yield
    await stop_imap_poller()
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
    app.include_router(conversations.router)
    app.include_router(jobs.router)
    app.include_router(outreach_accounts.router)

    return app


app = create_app()
