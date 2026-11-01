import logging
import re
from dataclasses import dataclass
from datetime import date, time
from functools import cached_property

from icalendar import Calendar

logger = logging.getLogger(__name__)


@dataclass
class General:
    username: str
    sirius_token: str
    semester_start: date
    semester_end: date
    token: str = ""
    sort_result: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.semester_start, str):
            self.semester_start = date.fromisoformat(self.semester_start)
        if isinstance(self.semester_end, str):
            self.semester_end = date.fromisoformat(self.semester_end)
        if not self.token:
            self.token = self.sirius_token


@dataclass
class Session:
    code: str
    parallel: int
    type: str
    number: int | None = None

    def __str__(self) -> str:
        number_text = f"{self.number}. " if self.number is not None else ""
        return f"{self.code} {number_text}{self.type} ({self.parallel})"

    @cached_property
    def pattern(self) -> re.Pattern[str]:
        code_part = re.escape(self.code)

        # "\s+" -> one or more whitespaces
        # "\d+" -> one or more numbers
        # "\." -> dot (must be escaped, dot without escape means any character)
        # "^" -> start of string
        if self.number is not None:
            number_part = rf"\s+{self.number}\."
        else:
            number_part = r"(?:\s+\d+\.)?"

        type_part = rf"\s+{re.escape(self.type)}"
        parallel_part = rf"\s+\({self.parallel}\)"

        pattern = rf"^{code_part}{number_part}{type_part}{parallel_part}$"
        return re.compile(pattern, flags=re.IGNORECASE)

    def matches(self, summary: str) -> bool:
        return bool(self.pattern.match(summary.strip()))


@dataclass
class SwapRule:
    drop: Session
    take: Session | None = None


@dataclass
class AddRule:
    title: str
    start_time: time
    end_time: time
    first_date: date
    repeat_days: int = 7
    repeat_on_holidays: bool = False
    location: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.first_date, str):
            self.first_date = date.fromisoformat(self.first_date)
        if isinstance(self.start_time, str):
            self.start_time = time.fromisoformat(self.start_time)
        if isinstance(self.end_time, str):
            self.end_time = time.fromisoformat(self.end_time)


@dataclass
class Rules:
    general: General
    swaps: list[SwapRule]
    adds: list[AddRule]


@dataclass
class Calendars:
    personal: Calendar
    courses: dict[str, Calendar]
