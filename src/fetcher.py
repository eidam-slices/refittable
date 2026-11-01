import asyncio
import logging
import time

import httpx

from src.models import Calendars, General, Rules

SIRIUS_URL = "https://sirius.fit.cvut.cz/api/v1"

logger = logging.getLogger(__name__)


class FetchError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        label: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.label = label

# TODO: replace "access_token" parameter with Bearer
def build_sirius_url(general: General, endpoint: str) -> str:
    return (
        f"{SIRIUS_URL}/{endpoint}/events.ical"
        f"?access_token={general.sirius_token}"
        f"&from={general.semester_start}&to={general.semester_end}"
    )


def build_personal_calendar_url(general: General) -> str:
    return build_sirius_url(general, f"people/{general.username}")


def build_course_calendar_url(general: General, course_code: str) -> str:
    return build_sirius_url(general, f"courses/{course_code}")


async def fetch_calendar(client: httpx.AsyncClient, url: str, label: str) -> str:
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        raise FetchError(
            f"Sirius API returned HTTP {status} for {label}.",
            status_code=status,
            label=label,
        ) from None
    except httpx.TimeoutException:
        raise FetchError(
            f"Timeout while fetching {label} from Sirius API.",
            status_code=504,
            label=label,
        ) from None
    except httpx.RequestError as e:
        raise FetchError(
            f"Network error while fetching {label}: {type(e).__name__}.",
            status_code=502,
            label=label,
        ) from None


async def fetch_all_calendars(rules: Rules, timeout_secs: float = 10) -> Calendars:
    source = rules.general

    required_courses = sorted({rule.take.code for rule in rules.swaps if rule.take is not None})
    logger.debug(
        "Fetching personal schedule for '%s' and %d course(s): %s",
        source.username,
        len(required_courses),
        ", ".join(required_courses) if required_courses else "none",
    )

    t0 = time.perf_counter()
    headers = {"User-Agent": "refittable/1.0", "Accept": "text/calendar, text/plain"}

    async with httpx.AsyncClient(headers=headers, timeout=timeout_secs) as client:
        personal_task = fetch_calendar(
            client=client,
            url=build_personal_calendar_url(source),
            label=f"personal schedule ({source.username})",
        )

        course_tasks = [
            fetch_calendar(
                client=client,
                url=build_course_calendar_url(source, code),
                label=f"course {code}",
            )
            for code in required_courses
        ]

        results = await asyncio.gather(personal_task, *course_tasks)

        elapsed = (time.perf_counter() - t0) * 1000
        logger.debug("Successfully fetched %d calendars in %.1f ms", len(results), elapsed)

        personal_ical = results[0]
        course_icals = dict(zip(required_courses, results[1:], strict=True))

    return Calendars(personal_ical, course_icals)
