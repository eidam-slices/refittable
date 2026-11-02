import logging
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4 as uuid
from zoneinfo import ZoneInfo

import holidays
from icalendar import Calendar, Event

from src.models import AddRule, Calendars, Rules, Session, SwapRule

DEFAULT_TZ = ZoneInfo("Europe/Prague")

logger = logging.getLogger(__name__)

czech_holidays = holidays.country_holidays("CZ")


class BuildError(Exception):
    pass


def event_timestamp(event: Event, timezone: ZoneInfo) -> float:
    dt = event.get("dtstart").dt

    if not isinstance(dt, datetime):
        dt = datetime.combine(dt, datetime.min.time(), tzinfo=timezone)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone)

    return dt.timestamp()


def matches_session(event: Event, session: Session) -> bool:
    summary = event.get("summary")
    if not summary:
        return False
    else:
        return session.matches(str(summary))


# =============================================================================
# Swap & Drop Rule Processing
# =============================================================================
def apply_drops(
    source: Calendar,
    swaps: list[SwapRule],
    events: list[Event],
) -> Counter[Session]:

    drop_counts: Counter[Session] = Counter()

    for event in source.events:
        matched_swap = next(
            (swap for swap in swaps if matches_session(event, swap.drop)),
            None,
        )
        if matched_swap:
            drop_counts[matched_swap.drop] += 1
        else:
            events.append(event)

    return drop_counts


def apply_takes(
    courses: dict[str, Calendar],
    swaps: list[SwapRule],
    events: list[Event],
) -> Counter[Session]:

    take_counts: Counter[Session] = Counter()

    for swap in swaps:
        if not swap.take:
            continue

        if swap.take.code not in courses:
            raise BuildError(
                f"Required course '{swap.take.code}' was not found in fetched calendars."
            )
        course = courses[swap.take.code]

        for event in course.events:
            if matches_session(event, swap.take):
                events.append(event)
                take_counts[swap.drop] += 1

    return take_counts


# =============================================================================
# Add Rule Processing
# =============================================================================
def create_event(
    summary: str,
    location: str | None,
    start: datetime,
    end: datetime,
    stamp: datetime,
) -> Event:
    event = Event()
    event.add("summary", summary)
    event.add("uid", f"{uuid()}@refittable")
    event.add("dtstart", start)
    event.add("dtend", end)
    event.add("dtstamp", stamp)

    if location:
        event.add("location", location)

    return event


def create_events(
    rule: AddRule,
    semester_start: date,
    semester_end: date,
    timezone: ZoneInfo,
) -> list[Event]:
    events: list[Event] = []

    start_dt = datetime.combine(rule.first_date, rule.start_time, timezone)
    end_dt = datetime.combine(rule.first_date, rule.end_time, timezone)
    now_dt = datetime.now(UTC)

    step = timedelta(days=rule.repeat_days)

    while True:
        start_d = start_dt.date()

        if not (semester_start <= start_d <= semester_end):
            break

        holiday = czech_holidays.get(start_d)

        if rule.repeat_on_holidays or not holiday or not rule.repeat_days:
            event = create_event(
                rule.title, rule.location, start_dt, end_dt, now_dt
            )
            events.append(event)
        else:
            logger.debug(
                "Skipped event '%s' on %s (%s)", rule.title, start_d, holiday
            )

        if not rule.repeat_days:
            break

        start_dt += step
        end_dt += step

    return events


def apply_adds(
    adds: list[AddRule],
    semester_start: date,
    semester_end: date,
    timezone: ZoneInfo,
    events: list[Event],
) -> Counter[str]:

    add_counts: Counter[str] = Counter()

    for add in adds:
        created_events = create_events(
            add, semester_start, semester_end, timezone
        )
        events.extend(created_events)
        add_counts[add.title] += len(created_events)

    return add_counts


# =============================================================================
# Logging
# =============================================================================
def log_statistics(
    swaps: list[SwapRule],
    drop_counts: Counter[Session],
    take_counts: Counter[Session],
    adds: list[AddRule],
    add_counts: Counter[str],
    total_events: int,
) -> None:
    for swap in swaps:
        dropped = drop_counts[swap.drop]

        if not swap.take:
            if not dropped:
                logger.warning("Drop rule '%s' matched no events.", swap.drop)
            else:
                logger.debug("Dropped '%s' (-%d events).", swap.drop, dropped)
            continue

        taken = take_counts[swap.drop]

        if not taken:
            logger.warning("Take rule '%s' matched no events.", swap.take)
        else:
            logger.debug(
                "Replaced '%s' with '%s' (-%d / +%d events).",
                swap.drop,
                swap.take,
                dropped,
                taken,
            )

    for add in adds:
        added = add_counts[add.title]

        if not added:
            logger.warning("Add rule '%s' generated no events.", add.title)
        else:
            logger.debug("Added '%s' (+%d events).", add.title, added)

    logger.debug("Built calendar contains %d events.", total_events)


# =============================================================================
# Calendar Assembly
# =============================================================================
def create_empty_calendar_from(source: Calendar) -> Calendar:
    clone = Calendar()

    for key, value in source.items():
        clone.add(key, value)

    for component in source.subcomponents:
        if component.name != "VEVENT":
            clone.add_component(component)

    return clone


def extract_timezone(source: Calendar, default: ZoneInfo) -> ZoneInfo:
    for component in source.subcomponents:
        if component.name != "VTIMEZONE":
            continue

        tzid = component.get("tzid")
        if not tzid:
            continue

        try:
            timezone = ZoneInfo(str(tzid))
            logger.debug("Resolved timezone from VTIMEZONE: %s", timezone.key)
            return timezone
        except Exception:  # noqa: BLE001
            logger.warning(
                "Unknown timezone ID (TZID=%s) in .ical file, falling back to default (%s).",
                tzid,
                default.key,
            )
            return default

    return default


def sort_events(events: list[Event], timezone: ZoneInfo) -> None:
    events.sort(key=lambda e: event_timestamp(e, timezone))


def assemble_calendar(source: Calendar, events: list[Event]) -> Calendar:
    assembled = create_empty_calendar_from(source)

    for event in events:
        assembled.add_component(event)

    return assembled


def build_calendar(rules: Rules, calendars: Calendars) -> Calendar:
    timezone = extract_timezone(calendars.personal, DEFAULT_TZ)

    events: list[Event] = []

    drops = apply_drops(calendars.personal, rules.swaps, events)
    takes = apply_takes(calendars.courses, rules.swaps, events)

    adds = apply_adds(
        rules.adds,
        rules.general.semester_start,
        rules.general.semester_end,
        timezone,
        events,
    )

    log_statistics(rules.swaps, drops, takes, rules.adds, adds, len(events))

    if rules.general.sort_result:
        sort_events(events, timezone)

    return assemble_calendar(calendars.personal, events)
