import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.config import settings
from backend.operations import run_full_scan
from backend.scheduler import OperationalScheduler
from memory.drift_detector import DriftDetector
from memory.llm_store import LLMEventStore
from memory.project_store import ProjectStore
from memory.snapshot_engine import SnapshotEngine
from memory.store import OperationalStore
from observability.logger import setup_logging
from reports.generator import ReportGenerator
from scanners.process_scanner import ProcessScanner
from scanners.registry import ScannerRegistry
from scanners.repo_scanner import RepoScanner
from scanners.runtime_scanner import RuntimeScanner
from scanners.service_scanner import ServiceScanner

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging(log_level=settings.log_level, log_format=settings.log_format)

    logger.info(
        "Application starting",
        extra={
            "app_name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.app_env,
            "debug": settings.debug,
        },
    )

    _ensure_dirs()

    # Storage
    store = OperationalStore(settings.db_path)
    store.connect()
    app.state.store = store

    # LLM event store (same SQLite file, separate table)
    llm_store = LLMEventStore(settings.db_path)
    llm_store.connect()
    app.state.llm_store = llm_store

    # Project store (same SQLite file, projects table)
    project_store = ProjectStore(settings.db_path)
    project_store.connect()
    app.state.project_store = project_store

    # Operational components
    snapshot_engine = SnapshotEngine(store)
    drift_detector = DriftDetector()
    report_generator = ReportGenerator(output_dir=settings.reports_dir)

    app.state.snapshot_engine = snapshot_engine
    app.state.drift_detector = drift_detector
    app.state.report_generator = report_generator

    # Scanner registry
    registry = ScannerRegistry()
    registry.register(RepoScanner())
    registry.register(ProcessScanner())
    registry.register(ServiceScanner())
    registry.register(RuntimeScanner())
    app.state.registry = registry

    # Scheduler
    targets = [t.strip() for t in settings.scan_targets.split(",") if t.strip()]

    def _scheduled_scan(target: str) -> None:
        try:
            run_full_scan(
                target=target,
                registry=registry,
                snapshot_engine=snapshot_engine,
                drift_detector=drift_detector,
                report_generator=report_generator,
            )
        except Exception as exc:
            logger.error(
                "Scheduled scan failed",
                extra={"target": target, "error": str(exc)},
            )

    scheduler = OperationalScheduler()
    scheduler.register_scan(_scheduled_scan, targets, settings.scan_interval_seconds)
    scheduler.start()
    app.state.scheduler = scheduler

    # Telegram delivery (optional — only wired if TELEGRAM_ENABLED=true)
    if settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
        _wire_telegram_delivery(
            app=app,
            scheduler=scheduler,
            snapshot_engine=snapshot_engine,
        )
    else:
        app.state.telegram = None

    logger.info(
        "Application ready",
        extra={
            "scan_targets": targets,
            "scan_interval_s": settings.scan_interval_seconds,
            "scanners": registry.registered,
        },
    )

    yield

    logger.info("Application shutting down")
    scheduler.stop()
    store.disconnect()
    llm_store.disconnect()
    project_store.disconnect()
    logger.info("Application stopped cleanly")


def _wire_telegram_delivery(
    app: FastAPI,
    scheduler: OperationalScheduler,
    snapshot_engine: SnapshotEngine,
) -> None:
    """Wire Telegram delivery client and delivery jobs into the scheduler."""
    from delivery.formatting import format_daily_digest
    from delivery.routing import DeliveryRouter, RoutingConfig
    from delivery.telegram import TelegramDeliveryClient

    telegram = TelegramDeliveryClient(
        token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )
    router = DeliveryRouter(
        RoutingConfig(
            quiet_hours_start=settings.telegram_quiet_hours_start,
            quiet_hours_end=settings.telegram_quiet_hours_end,
        )
    )
    app.state.telegram = telegram
    app.state.delivery_router = router

    if settings.telegram_daily_digest_enabled:
        def _daily_digest_job() -> None:
            try:
                digest = format_daily_digest(
                    system_status="ok",
                    scan_count=0,
                    snapshot_count=snapshot_engine.count() if hasattr(snapshot_engine, "count") else 0,
                    max_snapshot_count=settings.max_scan_history,
                    generated_at=None,
                )
                result = telegram.send_digest(digest)
                if not result.success:
                    logger.warning(
                        "Daily digest delivery failed",
                        extra={"error": result.error},
                    )
            except Exception as exc:
                logger.error(
                    "Daily digest job error",
                    extra={"error": str(exc)},
                )

        scheduler.register_cron_job(_daily_digest_job, "telegram_daily_digest", hour=8, minute=0)
        logger.info("Telegram daily digest job registered")

    logger.info(
        "Telegram delivery configured",
        extra={"chat_id": settings.telegram_chat_id},
    )


def _ensure_dirs() -> None:
    for path in [os.path.dirname(settings.db_path), settings.reports_dir]:
        if path and not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            logger.info("Created directory", extra={"path": path})
