import argparse
import asyncio
import logging
import sys
from os import environ
from pathlib import Path

from src.calendar import BuildError, build_calendar
from src.fetcher import FetchError, fetch_all_calendars
from src.parser import RulesError, load_rules

logger = logging.getLogger("refittable")


class ColoredFormatter(logging.Formatter):
    GREY = "\033[90m"
    BLUE = "\033[34m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BOLD_RED = "\033[1;31m"
    RESET = "\033[0m"

    COLORS = {  # noqa: RUF012
        logging.DEBUG: GREY,
        logging.INFO: BLUE,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        use_colors = sys.stderr.isatty() and "NO_COLOR" not in environ

        color = (
            self.COLORS.get(record.levelno, self.RESET) if use_colors else ""
        )
        reset = self.RESET if use_colors else ""

        prefix = f"{color}[{record.levelname}]{reset}"
        text = f"{prefix} {record.getMessage()}"

        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            text += f"\n{record.exc_text}"

        return text


async def export_calendar(
    rules_path: Path, output_path: Path | None, verbose: bool
) -> None:
    rules = load_rules(rules_path)

    def progress(msg: str) -> None:
        if output_path or verbose:
            sys.stderr.write(f"{msg}\n")
            sys.stderr.flush()

    progress(f"Pravidla úspěšně načtena z {rules_path}")

    progress("Stahování rozvrhů ze Sirius API...")
    calendars = await fetch_all_calendars(rules)

    progress("Sestavování rozvrhu...")
    built_calendar = build_calendar(rules, calendars)
    ical = built_calendar.to_ical()

    if output_path:
        output_path.write_bytes(ical)
        progress(f"Uloženo {len(ical)} bajtů do {output_path.resolve()}")

    else:
        sys.stdout.buffer.write(ical)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refittable – nástroj pro upravování rozvrhů z Sirius API"
    )
    parser.add_argument(
        "-r",
        "--rules",
        type=Path,
        default=Path("rules.toml"),
        help="Cesta k TOML souboru s pravidly (výchozí: rules.toml)",
    )
    parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Validovat syntaxi souboru s pravidly.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Exportovat upravený rozvrh do specifického souboru (.ics)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Povolit debug logy"
    )

    return parser.parse_args()


def setup_logging(verbose: bool) -> None:
    if verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.WARNING

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(ColoredFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # disable low level warnings:
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def run(args: argparse.Namespace) -> None:
    if args.check:
        rules = load_rules(args.rules)
        sys.stdout.write(
            f"OK: Soubor s pravidly {args.rules} je platný "
            f"({len(rules.swaps)} změn, {len(rules.adds)} přidání).\n"
        )
        return
    else:
        asyncio.run(export_calendar(args.rules, args.output, args.verbose))


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    try:
        run(args)
    except RulesError as e:
        logger.error("Chyba v souboru s pravidly: %s", e)
    except FetchError as e:
        logger.error("Nepodařilo se stáhnout rozvrh ze Sirius API: %s", e)
    except BuildError as e:
        logger.error("Chyba při sestavování kalendáře: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.error("Neočekávaná chyba: %s", e)
    else:
        return

    sys.exit(1)


if __name__ == "__main__":
    main()
