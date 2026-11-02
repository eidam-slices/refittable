import logging
import secrets
import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from src.calendar import BuildError, build_calendar
from src.fetcher import FetchError, fetch_all_calendars
from src.parser import RulesError, load_rules

app_logger = logging.getLogger("src")  # common logger for all modules in src/
app_logger.parent = logging.getLogger("uvicorn.error")

logger = logging.getLogger(__name__)

RULES_PATH = Path("rules.toml")

CACHE_TTL_SECONDS = 900
cache_expires_at: float = 0.0
cached_content: bytes | None = None
rules_modified_at: float = 0.0


# =============================================================================
# Authentication
# =============================================================================
def authenticate(token: str, expected_token: str) -> None:
    if not secrets.compare_digest(token, expected_token):
        raise HTTPException(
            status_code=401, detail="Neplatný nebo chybějící token."
        )


# =============================================================================
# Exception Handlers
# =============================================================================
async def handle_rules_error(request: Request, e: RulesError) -> Response:
    logger.error("Failed to load rules from %s: %s", RULES_PATH, e)
    return PlainTextResponse(
        "Chyba v pravidlech kalendáře na serveru.",
        status_code=500,
    )


async def handle_fetch_error(request: Request, e: FetchError) -> Response:
    logger.error("Failed to fetch calendar data: %s", e)
    if e.status_code in (401, 403):
        return PlainTextResponse(
            f"Neplatný Sirius token pro {e.label}.",
            status_code=400,
        )
    if e.status_code == 404:
        return PlainTextResponse(
            f"Rozvrh pro '{e.label}' nebyl na serveru Sirius nalezen.",
            status_code=400,
        )

    return PlainTextResponse(
        "Nepodařilo se spojit se serverem Sirius.",
        status_code=502,
    )


async def handle_build_error(request: Request, e: BuildError) -> Response:
    logger.error("Failed to build calendar: %s", e)
    return PlainTextResponse(
        "Chyba při sestavování kalendáře.",
        status_code=500,
    )


async def handle_unexpected_error(request: Request, e: Exception) -> Response:
    logger.exception("Unexpected error occurred.")
    return PlainTextResponse(
        "Neočekávaná chyba serveru.",
        status_code=500,
    )


# =============================================================================
# Endpoints
# =============================================================================
async def health(request: Request) -> Response:
    return PlainTextResponse("Ok\n")


async def calendar(request: Request) -> Response:
    global cached_content, cache_expires_at, rules_modified_at

    rules = load_rules(RULES_PATH)
    token = request.query_params.get("token", "")

    authenticate(token, rules.general.token)

    now = time.monotonic()
    mtime = RULES_PATH.stat().st_mtime
    rules_changed = mtime != rules_modified_at

    # if cache does not exist, or is expired
    if cached_content is None or now >= cache_expires_at or rules_changed:
        logger.debug("Rebuilding calendar (cache expired or rules changed)...")
        calendars = await fetch_all_calendars(rules)
        built_calendar = build_calendar(rules, calendars)

        cached_content = built_calendar.to_ical()
        cache_expires_at = now + CACHE_TTL_SECONDS
        rules_modified_at = mtime
    else:
        logger.debug("Using cached calendar")

    return Response(
        content=cached_content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="rozvrh.ics"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/", calendar, methods=["GET"]),
]

exception_handlers = {
    RulesError: handle_rules_error,
    FetchError: handle_fetch_error,
    BuildError: handle_build_error,
    500: handle_unexpected_error,
}

app = Starlette(
    debug=False,
    routes=routes,
    exception_handlers=exception_handlers,
)
