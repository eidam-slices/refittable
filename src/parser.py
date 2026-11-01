import logging
import tomllib
from pathlib import Path
from typing import Any

from src.models import AddRule, General, Rules, Session, SwapRule

logger = logging.getLogger(__name__)

GENERAL_KEY = "general"
SWAPS_KEY = "swaps"
DROP_KEY = "drop"
TAKE_KEY = "take"
ADDS_KEY = "adds"


class RulesError(Exception):
    def __init__(self, errors: list[str] | str) -> None:
        if isinstance(errors, str):
            self.errors = [errors]
        else:
            self.errors = errors

        super().__init__(str(self))

    def __str__(self) -> str:
        if not self.errors:
            return "Unknown rules error."

        if len(self.errors) == 1:
            return self.errors[0]

        bullet_points = "\n - ".join(self.errors)
        return f"{len(self.errors)} errors found:\n - {bullet_points}"


def read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RulesError(f"File with rules not found: {path.resolve()}")

    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise RulesError(f"TOML file {path.resolve()} is invalid: {e}") from e


def parse_general(data: dict[str, Any], errors: list[str]) -> General | None:
    if GENERAL_KEY not in data:
        errors.append(f"Missing required [{GENERAL_KEY}] section.")
        return None
    try:
        return General(**data[GENERAL_KEY])
    except (TypeError, ValueError) as e:
        errors.append(f"Section [{GENERAL_KEY}]: {e}")
        return None


def parse_session(
    data: dict[str, Any], label: str, index: int, errors: list[str]
) -> Session | None:
    try:
        return Session(**data)
    except (TypeError, ValueError) as e:
        target = data.get("code", f"item #{index}")
        errors.append(f"Subsection [{label}] ({target}): {e}")
        return None


def parse_swap(index: int, item: Any, errors: list[str]) -> SwapRule | None:
    drop_data = item.get(DROP_KEY)
    if not drop_data:
        errors.append(
            f"Item #{index} in [[{SWAPS_KEY}]]: Missing required subsection [{SWAPS_KEY}.{DROP_KEY}]."
        )
        return None
    drop_session = parse_session(drop_data, f"{SWAPS_KEY}.{DROP_KEY}", index, errors)
    if not drop_session:
        return None

    take_data = item.get(TAKE_KEY)
    if take_data:
        take_session = parse_session(take_data, f"{SWAPS_KEY}.{TAKE_KEY}", index, errors)
        if not take_session:
            return None
    else:
        take_session = None

    return SwapRule(drop_session, take_session)


def parse_swaps(data: dict[str, Any], errors: list[str]) -> list[SwapRule]:
    swaps: list[SwapRule] = []

    for index, swap_data in enumerate(data.get(SWAPS_KEY, []), start=1):
        swap = parse_swap(index, swap_data, errors)
        if not swap:
            continue

        swaps.append(swap)

    return swaps


def parse_add(index: int, item: Any, errors: list[str]) -> AddRule | None:
    try:
        return AddRule(**item)
    except (TypeError, ValueError) as e:
        target = item.get("title", f"item #{index}")
        errors.append(f"Section [[{ADDS_KEY}]] ({target}): {e}")
        return None


def parse_adds(data: dict[str, Any], errors: list[str]) -> list[AddRule]:
    adds: list[AddRule] = []

    for index, add_data in enumerate(data.get(ADDS_KEY, []), start=1):
        add = parse_add(index, add_data, errors)
        if not add:
            continue

        adds.append(add)

    return adds


def parse_rules(data: dict[str, Any]) -> Rules:
    errors: list[str] = []

    general = parse_general(data, errors)
    swaps = parse_swaps(data, errors)
    adds = parse_adds(data, errors)

    if errors:
        raise RulesError(errors)

    assert general is not None
    return Rules(general, swaps, adds)


def validate_rules(rules: Rules) -> None:
    errors: list[str] = []
    # TODO: implement validation
    if errors:
        raise RulesError(errors)


def load_rules(path: Path) -> Rules:
    data = read_toml(path)

    rules = parse_rules(data)
    validate_rules(rules)

    return rules
