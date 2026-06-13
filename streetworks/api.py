"""FastAPI application: SNS receiver, GeoJSON read API, health check, frontend."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import sns
from .config import Settings, load_settings
from .processor import process_notification
from .store import InMemoryStore, Store, filter_closures

logger = logging.getLogger("streetworks")

STATIC_DIR = Path(__file__).parent / "static"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_store(settings: Settings) -> Store:
    if settings.database_url:
        try:
            from .store_postgres import PostgresStore

            return PostgresStore(settings.database_url)
        except Exception as exc:  # pragma: no cover - depends on env
            logger.warning(
                "DATABASE_URL set but PostGIS store unavailable (%s); "
                "falling back to in-memory store",
                exc,
            )
    return InMemoryStore()


def create_app(
    settings: Settings | None = None,
    store: Store | None = None,
    *,
    cert_fetcher=None,
    subscribe_getter=None,
) -> FastAPI:
    """Build the app. Dependencies are injectable so tests can stub network I/O."""
    settings = settings or load_settings()
    store = store or _build_store(settings)

    app = FastAPI(title="Oxted & Hurst Green — road closures", version="0.1.0")
    app.state.settings = settings
    app.state.store = store

    def _handle_notification(envelope: dict) -> None:
        """Process a Notification (runs in the background after we return 200)."""
        store.record_message(_now_iso())
        result = process_notification(envelope, settings)
        if result.accepted and result.closure is not None:
            store.upsert(result.closure)
            logger.info("upserted closure %s (%s)", result.closure.reference, result.closure.status.value)
        else:
            # Filtered or unparseable. Out-of-area records are normal; log the
            # reason so genuine dead-letters (bad payloads) are visible.
            logger.info("notification not stored: %s", result.reason)

    # ── SNS webhook receiver ──────────────────────────────────────────────
    @app.post("/sns")
    async def sns_webhook(request: Request, background: BackgroundTasks) -> Response:
        raw = await request.body()
        try:
            envelope = sns.parse_envelope(raw)
        except Exception:
            logger.warning("could not parse SNS envelope; dropping")
            return JSONResponse({"status": "bad envelope"}, status_code=400)

        msg_type = envelope.get("Type")
        topic_arn = envelope.get("TopicArn")

        # Every message except a bare confirmation must come from a known topic.
        if topic_arn not in settings.allowed_topic_arns:
            logger.warning("rejecting message from unknown topic %s", topic_arn)
            return JSONResponse({"status": "unknown topic"}, status_code=403)

        if msg_type == "SubscriptionConfirmation":
            try:
                sns.confirm_subscription(envelope, getter=subscribe_getter)
            except Exception as exc:
                logger.error("subscription confirmation failed: %s", exc)
                return JSONResponse({"status": "confirm failed"}, status_code=502)
            logger.info("confirmed subscription to %s", topic_arn)
            return JSONResponse({"status": "subscription confirmed"})

        if msg_type == "UnsubscribeConfirmation":
            logger.warning("received UnsubscribeConfirmation for %s", topic_arn)
            return JSONResponse({"status": "unsubscribe noted"})

        if msg_type == "Notification":
            if settings.verify_signatures:
                try:
                    if cert_fetcher is not None:
                        sns.verify_signature(envelope, cert_fetcher=cert_fetcher)
                    else:
                        sns.verify_signature(envelope)
                except sns.SignatureError as exc:
                    logger.warning("rejecting notification: %s", exc)
                    return JSONResponse({"status": "bad signature"}, status_code=403)
            # Return 200 immediately; process out of band.
            background.add_task(_handle_notification, envelope)
            return JSONResponse({"status": "accepted"})

        logger.warning("unknown SNS message type %r", msg_type)
        return JSONResponse({"status": "ignored"}, status_code=400)

    # ── Read API: active closures as GeoJSON ──────────────────────────────
    @app.get("/closures")
    def get_closures(
        status: str | None = Query(None, description="proposed|in_progress|completed|inactive"),
        traffic_management_type: str | None = Query(None),
        work_category: str | None = Query(None),
        start_date: str | None = Query(None, description="ISO YYYY-MM-DD"),
        end_date: str | None = Query(None, description="ISO YYYY-MM-DD"),
    ) -> JSONResponse:
        closures = filter_closures(
            store.list_closures(),
            active_only=status is None,
            status=status,
            traffic_management_type=traffic_management_type,
            work_category=work_category,
            start_date=start_date,
            end_date=end_date,
        )
        return JSONResponse(
            {
                "type": "FeatureCollection",
                "features": [c.to_feature() for c in closures],
            }
        )

    # ── Health check ──────────────────────────────────────────────────────
    @app.get("/healthz")
    def healthz() -> JSONResponse:
        last = store.last_message_at()
        stale = False
        if last is not None:
            age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600
            stale = age_hours > settings.health_max_silence_hours
        payload = {
            "status": "degraded" if stale else "ok",
            "last_message_at": last,
            "closures_tracked": len(store.list_closures()),
            "swa_code": settings.surrey_swa_code,
        }
        # Degraded (no traffic for N hours) is still a 200 so the page loads,
        # but the status field lets an external monitor alert.
        return JSONResponse(payload, status_code=200 if not stale else 503)

    # ── Frontend ──────────────────────────────────────────────────────────
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> Response:
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return JSONResponse({"status": "ok", "see": "/closures"})

    return app


# Module-level app for `uvicorn streetworks.api:app`.
app = create_app()
