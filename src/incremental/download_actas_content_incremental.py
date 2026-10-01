#!/usr/bin/env python3
"""Incrementally download the current season's actas content from fctt.cat.

The territorial leagues are listed as cards on ``https://fctt.cat/competicions-estatals/``
under the ``Lligues de la representació territorial de <territory>`` headings. Every card
links to a league page (one category and group) whose jornada buttons lead to
``<league>?jornada=N``. A jornada page holds, for each match, the date, teams and venue
and, once the match is played, the full acta (games, players) and a PDF acta link.

Output layout::

    <output_dir>/<season>/<category>/<group>/<phase>/jornada_NN.html
    <output_dir>/<season>/<category>/<group>/<phase>/jornada_NN/<match_id>.pdf

The download is incremental: a jornada whose saved HTML is marked ``complete`` (every
match played with its acta published and validated) and whose PDFs exist is not requested
again; jornadas with pending matches are refreshed on each run until they are complete.

Every downloaded jornada is validated: it must list as many matches as the league page,
every played match needs its results table (whose running score ends at the final score)
with all players linked by ``codi_jugador``, and every unplayed match needs its date, time,
teams and venue. Incomplete pages are retried; after the last retry the best page is saved
as ``partial`` with its issues in the ``acta-content-issues`` meta tag.

Note: fctt.cat intermittently answers with an empty page ("No s'han trobat partits"),
404/500 errors, and serves empty pages to non-browser user agents, so such responses are
retried with a different browser user agent and exponential backoff. A future jornada
(every match dated later than now on the league page) is not requested at all: there are
no results to wait for, so the minimal match info (date, time, teams, venue) of the league
page is saved instead and never retried.

Metrics of every request (attempts, duration, errors) and match day outcome are kept in
``metrics/download_actas_content_incremental_metrics.json``. Later runs use them (unless
``--no-adaptive``) to size the retry budget from the observed retry success rate, to slow
down when the server rate-limits, and to stop retrying match days that keep returning the
same incomplete content.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import itertools
import json
import logging
import math
import random
import re
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, TypeVar, cast
from urllib import robotparser
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag


REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_URL = "https://fctt.cat/competicions-estatals/"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "resources" / "actas-incremental-content"
DEFAULT_LOG_FILE = REPO_ROOT / "logs" / "download_actas_content_incremental.log"
DEFAULT_METRICS_FILE = REPO_ROOT / "metrics" / "download_actas_content_incremental_metrics.json"
TERRITORIES = ("Barcelona", "Girona", "Lleida", "Tarragona")
DEFAULT_PHASE = "1a Fase"
STATUS_META = "acta-content-status"
HASH_META = "acta-content-hash"
ISSUES_META = "acta-content-issues"
# fctt.cat answers 404 and 500 intermittently for pages that exist, so both are retried.
RETRYABLE_STATUS = {403, 404, 408, 425, 429, 500, 502, 503, 504}
RATE_LIMIT_ERRORS = {"HTTP 429", "HTTP 503"}
# Full browser user agents: fctt.cat serves empty league pages to short or bot-like ones.
USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
)
BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "ca,es;q=0.8,en;q=0.5",
}
PHASE_PATTERNS = (
    (r"play\s*-?\s*off\s+(?:de\s+)?t[ií]tol", "Play Off Títol"),
    (r"play\s*-?\s*off(?:\s+(?:d'|de\s+)?ascens)?", "Play Off Ascens"),
    (r"\bt[ií]tol\b", "TITOL"),
    (r"\bascens\b", "ASCENS"),
    (r"\bdescens\b", "DESCENS"),
    (r"\b([1-4])\s*a\s+fase\b", "{0}a Fase"),
)
SCORE_RE = re.compile(r"(\d+)\s*-\s*(\d+)")

# Metrics: rolling windows kept in the JSON file and the knobs of the adaptive retry policy.
METRICS_VERSION = 1
MAX_RUNS = 100
MAX_REQUEST_LOG = 3000
MAX_FAILURE_LOG = 500
MAX_DAY_HISTORY = 10
MIN_RETRY_SAMPLES = 10  # Retry attempts needed before the observed success rate is trusted.
TARGET_FAILURE_RATE = 0.05  # Retry until at most this share of failing requests stays failed.
MAX_EXTRA_RETRIES = 2  # Adaptive retries never exceed --retry by more than this.

T = TypeVar("T")


class ContentError(Exception):
    """A response arrived but its content is not usable (empty page, not a PDF...)."""


class IncompleteContent(ContentError):
    """A page arrived but failed validation; ``result`` is kept in case no retry does better."""

    def __init__(self, result: Any, issues: list[str]):
        super().__init__(f"incomplete content: {issues[0]}" + (f" (+{len(issues) - 1} more)" if len(issues) > 1 else ""))
        self.result = result
        self.issues = issues


@dataclass(frozen=True)
class League:
    territory: str
    title: str
    category: str
    group: str
    phase: str | None  # None when the card title does not name a phase.
    url: str


@dataclass(frozen=True)
class Match:
    match_id: str
    played: bool
    acta_url: str | None


# --------------------------------------------------------------------------- arguments


def current_season(today: date | None = None) -> str:
    today = today or date.today()
    start = today.year if today.month >= 8 else today.year - 1
    return f"{start}-{start + 1}"


def parse_match_days(value: str) -> set[int]:
    days: set[int] = set()
    for part in filter(None, (piece.strip() for piece in value.split(","))):
        bounds = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
        if not bounds:
            raise argparse.ArgumentTypeError(f"invalid match day: {part!r} (use 3, 1,4 or 2-5)")
        first, last = int(bounds.group(1)), int(bounds.group(2) or bounds.group(1))
        days.update(range(min(first, last), max(first, last) + 1))
    return days


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", default=current_season(), help="Season, e.g. 2026-2027 (default: current season)")
    parser.add_argument("--territory", help=f"Territory: {', '.join(TERRITORIES)} (default: all)")
    parser.add_argument("--category", help="Category, e.g. 'RTB PREFERENT' or 'PREFERENT' (default: all)")
    parser.add_argument("--group", help="Group, e.g. G1 or 1 (default: all)")
    parser.add_argument("--phase", help="Phase, e.g. '1a Fase' (default: all)")
    parser.add_argument("--match_day", type=parse_match_days, help="Match day(s): 3, 1,4 or 2-5 (default: all)")
    parser.add_argument("--format", choices=("html", "pdf", "both"), default="both", help="Content to download (default: both)")
    parser.add_argument("--output_dir", type=Path, default=DEFAULT_OUTPUT_DIR, help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--log_file", type=Path, default=DEFAULT_LOG_FILE, help=f"Log file (default: {DEFAULT_LOG_FILE})")
    parser.add_argument("--force", action="store_true", help="Re-download content even if it already exists")
    parser.add_argument("--retry", type=int, default=3, help="Retries for failed downloads (default: 3)")
    parser.add_argument(
        "--skip_pdf", action=argparse.BooleanOptionalAction, default=True,
        help="Skip downloading PDF actas (default: on; use --no-skip_pdf to download them)",
    )
    parser.add_argument("--delay", type=float, default=1.0, help="Minimum seconds between requests (default: 1.0)")
    parser.add_argument("--backoff", type=float, default=2.0, help="Base seconds for exponential retry backoff (default: 2.0)")
    parser.add_argument("--timeout", type=float, default=60.0, help="Request timeout in seconds (default: 60)")
    parser.add_argument(
        "--metrics_file", type=Path, default=DEFAULT_METRICS_FILE,
        help=f"Success/failure metrics JSON, read and updated on each run (default: {DEFAULT_METRICS_FILE})",
    )
    parser.add_argument(
        "--adaptive", action=argparse.BooleanOptionalAction, default=True,
        help="Tune retries and backoff from the metrics of previous runs (default: on)",
    )
    args = parser.parse_args(argv)
    if not re.fullmatch(r"\d{4}-\d{4}", args.season):
        parser.error("--season must look like 2026-2027")
    if args.retry < 0:
        parser.error("--retry must be >= 0")
    return args


# --------------------------------------------------------------------------- helpers


def fold(text: str) -> str:
    """Lower-case, accent-free, single-spaced text for comparisons."""
    text = unicodedata.normalize("NFD", text.replace("ª", "a"))
    text = "".join(character for character in text if unicodedata.category(character) != "Mn")
    return re.sub(r"\s+", " ", text).strip().casefold()


def clean_name(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    return value.rstrip(". ") or "unknown"


def normalise_group(value: str) -> str:
    match = re.fullmatch(r"(?:g|grup)?\s*(\d+)", value.strip(), re.I)
    return f"G{match.group(1)}" if match else value.strip().upper()


def node_text(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def write_atomically(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / (destination.name + ".part")
    try:
        temporary.write_bytes(content)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def configure_logging(log_file: Path) -> logging.Logger:
    logger = logging.getLogger("download_actas_content_incremental")
    logger.setLevel(logging.INFO)
    if not logger.handlers:  # main() may run more than once in the same process.
        log_file.parent.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console)
    return logger


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- metrics


@dataclass
class RequestRecord:
    """One logical download: every attempt made for a URL until it succeeded or gave up."""

    kind: str  # index, league, jornada or pdf
    key: str
    url: str
    attempts: int = 0
    duration_s: float = 0.0
    # ok, incomplete (best page kept after failed validation), failed, http-error, disallowed
    outcome: str = "failed"
    errors: list[str] = field(default_factory=list)

    @property
    def retries(self) -> int:
        return max(0, self.attempts - 1)


def error_class(message: str) -> str:
    """Group error messages for the error distribution (``HTTP 500``, ``timeout``...)."""
    lowered = message.casefold()
    if match := re.match(r"http (\d{3})", lowered):
        return f"HTTP {match.group(1)}"
    for needle, name in (
        ("incomplete content", "incomplete content"), ("empty page", "empty page"), ("without matches", "empty page"),
        ("not a pdf", "not a PDF"), ("timed out", "timeout"), ("timeout", "timeout"),
        ("connection", "connection error"), ("ssl", "SSL error"),
    ):
        if needle in lowered:
            return name
    return "other"


def new_kind_stats() -> dict[str, Any]:
    return {
        "requests": 0, "successes": 0, "incomplete": 0, "failures": 0, "attempts": 0, "retries": 0,
        "retry_successes": 0, "attempts_to_success": {}, "errors": {},
        "duration_s": {"count": 0, "sum": 0.0, "sum_sq": 0.0, "min": None, "max": None},
    }


class Metrics:
    """Success/failure metrics persisted across runs and the retry policy learnt from them.

    The JSON file holds lifetime totals per request kind (attempt histogram, error
    distribution, duration moments), rolling logs of recent requests and failures, per-target
    and per-match-day history, and a summary of the last runs.
    """

    def __init__(self, path: Path, logger: logging.Logger):
        self.path = path
        self.logger = logger
        self.data = self._load()
        self.run_counters: Counter = Counter()
        self.run_requests = 0
        self.run_retries = 0
        self.started_at = now_iso()
        self.started = time.monotonic()

    def _empty(self) -> dict[str, Any]:
        return {
            "schema_version": METRICS_VERSION, "created_at": now_iso(), "updated_at": None,
            "totals": {}, "request_kinds": {}, "targets": {}, "match_days": {},
            "runs": [], "recent_requests": [], "recent_failures": [],
        }

    def _load(self) -> dict[str, Any]:
        empty = self._empty()
        if not self.path.exists():
            return empty
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            backup = self.path.with_suffix(".corrupt.json")
            self.logger.warning("Metrics file %s is unreadable (%s); moved to %s and starting fresh", self.path, exc, backup)
            self.path.replace(backup)
            return empty
        if not isinstance(data, dict) or data.get("schema_version") != METRICS_VERSION:
            self.logger.warning("Metrics file %s has an unknown schema; starting fresh", self.path)
            return empty
        for name, value in empty.items():
            data.setdefault(name, value)
        return data

    # ---- recording

    def record_request(self, record: RequestRecord) -> None:
        self.run_requests += 1
        self.run_retries += record.retries
        stats = self.data["request_kinds"].setdefault(record.kind, new_kind_stats())
        stats["requests"] += 1
        stats["attempts"] += record.attempts
        stats["retries"] += record.retries
        if record.outcome == "ok":
            stats["successes"] += 1
            histogram = stats["attempts_to_success"]
            histogram[str(record.attempts)] = histogram.get(str(record.attempts), 0) + 1
            if record.attempts > 1:
                stats["retry_successes"] += 1
        elif record.outcome == "incomplete":
            stats["incomplete"] += 1
        else:
            stats["failures"] += 1
        for error in record.errors:
            name = error_class(error)
            stats["errors"][name] = stats["errors"].get(name, 0) + 1
        duration = stats["duration_s"]
        duration["count"] += 1
        duration["sum"] += record.duration_s
        duration["sum_sq"] += record.duration_s ** 2
        duration["min"] = record.duration_s if duration["min"] is None else min(duration["min"], record.duration_s)
        duration["max"] = record.duration_s if duration["max"] is None else max(duration["max"], record.duration_s)

        target = self.data["targets"].setdefault(f"{record.kind}:{record.key}", {
            "url": record.url, "requests": 0, "failures": 0, "retries": 0, "consecutive_failures": 0,
        })
        target["requests"] += 1
        target["retries"] += record.retries
        target["last_seen"] = now_iso()
        target["last_outcome"] = record.outcome
        if record.outcome in ("ok", "incomplete"):
            target["consecutive_failures"] = 0
        else:
            target["failures"] += 1
            target["consecutive_failures"] += 1
            target["last_error"] = record.errors[-1] if record.errors else record.outcome

        entry = {"at": now_iso(), **asdict(record), "duration_s": round(record.duration_s, 3)}
        self._append("recent_requests", entry, MAX_REQUEST_LOG)
        if record.outcome != "ok":
            self._append("recent_failures", entry, MAX_FAILURE_LOG)

    def record_match_day(self, key: str, outcome: str, retries: int = 0, duration_s: float = 0.0,
                         error: str | None = None, issues: list[str] | None = None) -> None:
        """Record a match day outcome: new, updated, unchanged, future, skipped, incomplete or failed."""
        self.run_counters[f"match days {outcome}"] += 1
        day = self.data["match_days"].setdefault(key, {
            "downloads": 0, "failures": 0, "skipped": 0, "incomplete": 0, "retries": 0, "history": [],
        })
        if outcome in ("new", "updated", "unchanged", "future"):
            day["downloads"] += 1
        elif outcome == "skipped":
            day["skipped"] += 1
        elif outcome == "incomplete":
            day["incomplete"] += 1
        elif outcome == "failed":
            day["failures"] += 1
        day["retries"] += retries
        day["last_outcome"] = outcome
        day["last_retries"] = retries
        day["last_duration_s"] = round(duration_s, 3)
        day["updated_at"] = now_iso()
        if error:
            day["last_error"] = error
        day["last_issues"] = issues or []
        signature = hashlib.sha1("\n".join(sorted(issues)).encode("utf-8")).hexdigest()[:12] if issues else None
        day["history"] = (day["history"] + [{
            "at": now_iso(), "outcome": outcome, "retries": retries,
            "duration_s": round(duration_s, 3), "issues_signature": signature,
        }])[-MAX_DAY_HISTORY:]

    def count(self, name: str, amount: int = 1) -> None:
        self.run_counters[name] += amount

    def _append(self, name: str, entry: dict[str, Any], limit: int) -> None:
        self.data[name] = (self.data[name] + [entry])[-limit:]

    # ---- learning

    def retry_success_rate(self, kind: str) -> tuple[float, int] | None:
        """Share of retry attempts that succeeded for ``kind`` over the recent request window.

        Each retry is modelled as an independent trial (a geometric distribution), so the
        success rate tells how many retries are needed to recover most failing requests.
        """
        recent = [entry for entry in self.data["recent_requests"] if entry["kind"] == kind]
        retry_attempts = sum(max(0, entry["attempts"] - 1) for entry in recent)
        if retry_attempts < MIN_RETRY_SAMPLES:
            return None
        recovered = sum(1 for entry in recent if entry["outcome"] == "ok" and entry["attempts"] > 1)
        return recovered / retry_attempts, retry_attempts

    def advised_retries(self, kind: str, base: int) -> int:
        """Retries so that at most ``TARGET_FAILURE_RATE`` of failing requests stay failed.

        Bounded to [1, base + MAX_EXTRA_RETRIES] so the server is never hammered; ``--retry 0``
        is always honoured.
        """
        estimate = self.retry_success_rate(kind)
        if base == 0 or estimate is None:
            return base
        rate, _ = estimate
        if rate >= 0.999:
            needed = 1
        elif rate <= 0.01:
            needed = 1  # Retries barely ever help: keep a single one.
        else:
            needed = math.ceil(math.log(TARGET_FAILURE_RATE) / math.log(1 - rate))
        return max(1, min(base + MAX_EXTRA_RETRIES, needed))

    def rate_limited(self) -> bool:
        """True when recent failures are dominated by rate limiting (HTTP 429/503)."""
        errors = [error_class(error) for entry in self.data["recent_failures"] for error in entry["errors"]]
        errors += [error_class(error) for entry in self.data["recent_requests"][-500:]
                   if entry["outcome"] == "ok" for error in entry["errors"]]
        if len(errors) < 10:
            return False
        return sum(error in RATE_LIMIT_ERRORS for error in errors) / len(errors) > 0.2

    def persistently_incomplete(self, key: str) -> bool:
        """True when the last two runs ended with the same incomplete content for this match day."""
        history = self.data["match_days"].get(key, {}).get("history", [])
        last = history[-2:]
        return (len(last) == 2 and all(item["outcome"] == "incomplete" for item in last)
                and last[0]["issues_signature"] == last[1]["issues_signature"])

    def problem_report(self, limit: int = 5) -> list[str]:
        """Targets and match days that failed most often, for the run log."""
        lines = []
        targets = sorted(
            ((name, value) for name, value in self.data["targets"].items() if value["failures"]),
            key=lambda item: (item[1]["consecutive_failures"], item[1]["failures"]), reverse=True,
        )
        for name, value in targets[:limit]:
            lines.append(f"{name}: {value['failures']}/{value['requests']} failed "
                         f"({value['consecutive_failures']} in a row), last error: {value.get('last_error')}")
        days = sorted(
            ((name, value) for name, value in self.data["match_days"].items() if value["failures"] or value["incomplete"]),
            key=lambda item: item[1]["failures"] + item[1]["incomplete"], reverse=True,
        )
        for name, value in days[:limit]:
            lines.append(f"{name}: {value['failures']} failed, {value['incomplete']} incomplete, "
                         f"{value['retries']} retries; last: {value['last_outcome']}")
        return lines

    # ---- persistence

    def save(self, args: argparse.Namespace, policy: dict[str, Any]) -> None:
        totals = Counter(self.data["totals"])
        totals.update(self.run_counters)
        totals.update({"runs": 1, "requests": self.run_requests, "retries": self.run_retries})
        self.data["totals"] = dict(sorted(totals.items()))
        run = {
            "started_at": self.started_at,
            "finished_at": now_iso(),
            "duration_s": round(time.monotonic() - self.started, 1),
            "arguments": {name: (str(value) if isinstance(value, Path) else sorted(value) if isinstance(value, set) else value)
                          for name, value in vars(args).items()},
            "policy": policy,
            "requests": self.run_requests,
            "retries": self.run_retries,
            "counters": dict(sorted(self.run_counters.items())),
        }
        self._append("runs", run, MAX_RUNS)
        self.data["updated_at"] = now_iso()
        write_atomically(self.path, json.dumps(self.data, ensure_ascii=False, indent=1).encode("utf-8"))
        self.logger.info("Metrics saved to %s", self.path)


# --------------------------------------------------------------------------- HTTP


class Fetcher:
    """Polite HTTP client: robots.txt, rate limit, retries with backoff and rotating user agents."""

    def __init__(self, retries: dict[str, int], default_retries: int, delay: float, backoff: float,
                 timeout: float, logger: logging.Logger, metrics: Metrics):
        self.retries = retries
        self.default_retries = default_retries
        self.delay = max(0.0, delay)
        self.backoff = max(0.0, backoff)
        self.timeout = timeout
        self.logger = logger
        self.metrics = metrics
        self.session = requests.Session()
        self.session.headers.update(BASE_HEADERS)
        self.user_agents = itertools.cycle(random.sample(USER_AGENTS, len(USER_AGENTS)))
        self.robots: dict[str, robotparser.RobotFileParser | None] = {}
        self.last_request = 0.0
        self.last: RequestRecord | None = None

    def _throttle(self) -> None:
        wait = self.last_request + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last_request = time.monotonic()

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.robots:
            parser: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
            try:
                self._throttle()
                response = self.session.get(
                    origin + "/robots.txt", headers={"User-Agent": USER_AGENTS[0]}, timeout=self.timeout
                )
                if response.status_code >= 400:
                    parser = None  # No robots.txt: everything is allowed.
                else:
                    cast(robotparser.RobotFileParser, parser).parse(response.text.splitlines())
                    crawl_delay = cast(robotparser.RobotFileParser, parser).crawl_delay("*")
                    if crawl_delay and float(crawl_delay) > self.delay:
                        self.logger.info("Honouring %s robots.txt crawl delay of %ss", origin, crawl_delay)
                        self.delay = float(crawl_delay)
            except requests.RequestException as exc:
                self.logger.warning("Could not read %s/robots.txt (%s); assuming allowed", origin, exc)
                parser = None
            self.robots[origin] = parser
        parser = self.robots[origin]
        return parser is None or parser.can_fetch("*", url)

    def get(self, url: str, check: Callable[[requests.Response], T], kind: str, key: str | None = None,
            retries: int | None = None) -> T | None:
        """GET ``url`` and return ``check(response)``, retrying failures; None when it keeps failing.

        When ``check`` keeps rejecting the page as incomplete, the last page is returned anyway
        (``self.last.outcome == "incomplete"``) so the caller can keep the best content found.
        Every call is recorded in the metrics and left in ``self.last``.
        """
        record = RequestRecord(kind, key or url, url)
        self.last = record
        started = time.monotonic()
        try:
            return self._get(url, check, record, self.retries.get(kind, self.default_retries) if retries is None else retries)
        finally:
            record.duration_s = time.monotonic() - started
            self.metrics.record_request(record)

    def _get(self, url: str, check: Callable[[requests.Response], T], record: RequestRecord, retries: int) -> T | None:
        if not self.allowed(url):
            self.logger.error("Disallowed by robots.txt, skipping: %s", url)
            record.outcome = "disallowed"
            return None
        attempts = retries + 1
        for attempt in range(1, attempts + 1):
            record.attempts = attempt
            retry_after = 0.0
            self._throttle()
            try:
                response = self.session.get(url, headers={"User-Agent": next(self.user_agents)}, timeout=self.timeout)
                if response.status_code in RETRYABLE_STATUS:
                    retry_after = parse_retry_after(response.headers.get("Retry-After"))
                    raise ContentError(f"HTTP {response.status_code}")
                if response.status_code >= 400:
                    self.logger.error("HTTP %d (not retried): %s", response.status_code, url)
                    record.errors.append(f"HTTP {response.status_code}")
                    record.outcome = "http-error"
                    return None
                result = check(response)
                record.outcome = "ok"
                return result
            except (requests.RequestException, ContentError) as exc:
                record.errors.append(str(exc)[:300])
                if attempt == attempts:
                    if isinstance(exc, IncompleteContent):
                        self.logger.error("Still incomplete after %d attempt(s), keeping the last page: %s (%s)",
                                          attempts, url, "; ".join(exc.issues))
                        record.outcome = "incomplete"
                        return cast(T, exc.result)
                    self.logger.error("Failed after %d attempt(s): %s (%s)", attempts, url, exc)
                    record.outcome = "failed"
                    return None
                wait = max(retry_after, self.backoff * 2 ** (attempt - 1) + random.uniform(0, self.backoff))
                self.logger.warning("Attempt %d/%d failed for %s (%s); retrying in %.1fs", attempt, attempts, url, exc, wait)
                time.sleep(wait)
        return None


def parse_retry_after(value: str | None) -> float:
    try:
        return min(float(value or 0), 300.0)
    except ValueError:
        return 0.0


def html_check(*selectors: str) -> Callable[[requests.Response], BeautifulSoup]:
    """Accept an HTML response only when it contains one of ``selectors``."""

    def check(response: requests.Response) -> BeautifulSoup:
        soup = BeautifulSoup(response.content, "html.parser")
        if not any(soup.select_one(selector) for selector in selectors):
            raise ContentError("page without the expected content (the site returned an empty page)")
        return soup

    return check


def pdf_check(response: requests.Response) -> bytes:
    content = response.content
    if not content.lstrip()[:5].startswith(b"%PDF"):
        content_type = response.headers.get("Content-Type", "no content type")
        raise ContentError(f"response is not a PDF ({content_type}, {len(content)} bytes)")
    return content


# --------------------------------------------------------------------------- discovery


def discover_leagues(soup: BeautifulSoup, page_url: str) -> list[League]:
    """Return the league cards listed under each territorial heading."""
    territory_re = re.compile(r"representacio territorial de (\w+)")
    leagues: list[League] = []
    territory: str | None = None
    for element in soup.find_all(["h2", "div"]):
        if element.name == "h2":
            match = territory_re.search(fold(element.get_text(" ", strip=True)))
            territory = match.group(1).capitalize() if match else None
            continue
        if territory is None or "jet-engine-listing-overlay-wrap" not in (element.get("class") or []):
            continue
        link = element.find("a", href=True)
        url = cast(str, element.get("data-url") or (link["href"] if link else ""))
        heading = element.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)) if heading else ""
        if not url or not title:
            continue
        category, group, phase = split_card_title(title)
        leagues.append(League(territory, title, category, group, phase, urljoin(page_url, url)))
    return list(dict.fromkeys(leagues))


def phase_from_text(text: str) -> tuple[str | None, str]:
    """Return the phase named in ``text`` (or None) and ``text`` without it."""
    for pattern, phase in PHASE_PATTERNS:
        match = re.search(pattern, text, re.I)
        if match:
            rest = re.sub(r"\s+", " ", (text[:match.start()] + text[match.end():]).strip(" -"))
            return phase.format(*match.groups()), rest.strip()
    return None, text


def split_card_title(title: str) -> tuple[str, str, str | None]:
    """Split a card title such as ``RTB PREFERENT G1`` into category, group and phase."""
    phase, rest = phase_from_text(title)
    match = re.fullmatch(r"(.+?)\s+(?:G|GRUP\s*)(\d+)", rest, re.I)
    if match:
        return match.group(1).strip(), f"G{match.group(2)}", phase
    # Leagues with a single group (Girona, Tarragona, Lleida) have no group suffix.
    return rest.strip(), "G1", phase


def league_matches_filters(league: League, args: argparse.Namespace) -> bool:
    if args.territory and fold(league.territory) != fold(args.territory):
        return False
    if args.category:
        wanted = fold(args.category)
        short = re.sub(r"^rt[bglt] ", "", fold(league.category))
        if wanted not in {fold(league.category), short, fold(league.title)}:
            return False
    if args.group and league.group != normalise_group(args.group):
        return False
    return True


def page_season(soup: BeautifulSoup) -> str | None:
    main = soup.find("main")
    for css_class in (main.get("class") or []) if isinstance(main, Tag) else []:
        match = re.fullmatch(r"temporades-(\d{4}-\d{4})", css_class)
        if match:
            return match.group(1)
    title = soup.select_one(".br-apic-league-title")
    match = re.search(r"(\d{4})\s*/\s*(\d{4})", title.get_text(" ", strip=True)) if title else None
    return f"{match.group(1)}-{match.group(2)}" if match else None


def league_page_title(soup: BeautifulSoup) -> str:
    title = soup.select_one(".br-apic-league-title") or soup.select_one("h1.entry-title")
    return re.sub(r"\s+", " ", title.get_text(" ", strip=True)) if title else ""


def match_days(soup: BeautifulSoup) -> list[int]:
    days = {int(cast(str, button["data-jornada"])) for button in soup.select(".jornada-btn[data-jornada]")
            if cast(str, button["data-jornada"]).isdigit()}
    for anchor in soup.select(".jornada-results-title a[href]"):
        match = re.search(r"[?&]jornada=(\d+)", cast(str, anchor["href"]))
        if match:
            days.add(int(match.group(1)))
    return sorted(days)


@dataclass
class ScheduledDay:
    """A jornada as listed on the league page: its heading and match containers."""

    heading: Tag | None
    containers: list[Tag]


def league_schedule(soup: BeautifulSoup) -> dict[int, ScheduledDay]:
    """Group the league page's match containers by the jornada heading that precedes them."""
    schedule: dict[int, ScheduledDay] = {}
    current: ScheduledDay | None = None
    for element in soup.select(".jornada-results-title, .match-container"):
        if "jornada-results-title" in (element.get("class") or []):
            match = re.search(r"(\d+)", element.get_text(" ", strip=True))
            current = schedule.setdefault(int(match.group(1)), ScheduledDay(element, [])) if match else None
        elif current is not None:
            current.containers.append(element)
    return schedule


def match_datetime(container: Tag) -> datetime | None:
    """Parse a match container's ``dd/mm/yyyy · hh:mm`` date (time optional)."""
    found = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\D+(\d{1,2}):(\d{2}))?", node_text(container.select_one(".match-datetime")))
    if not found:
        return None
    day, month, year, hour, minute = found.groups()
    try:
        return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0))
    except ValueError:
        return None


def is_future_day(scheduled: ScheduledDay | None, now: datetime | None = None) -> bool:
    """True when every match of the jornada is dated after ``now`` (none has started yet)."""
    if not scheduled or not scheduled.containers:
        return False
    now = now or datetime.now()
    dates = [match_datetime(container) for container in scheduled.containers]
    return all(value is not None and value > now for value in dates)


# --------------------------------------------------------------------------- jornada content


def parse_matches(containers: list[Tag], page_url: str) -> list[Match]:
    matches = []
    for position, container in enumerate(containers, start=1):
        acta = container.select_one("a.acta-link[href]") or next(
            (anchor for anchor in container.find_all("a", href=True)
             if re.search(r"/imprimir/acta|\.pdf(?:$|[?#])", cast(str, anchor["href"]), re.I)),
            None,
        )
        acta_url = urljoin(page_url, cast(str, acta["href"])) if acta else None
        played = bool(
            acta_url or container.select_one(".match-results-table")
            or SCORE_RE.search(node_text(container.select_one(".match-score")))
        )
        partido = re.search(r"/partido/(\d+)", acta_url or "")
        team_ids = [
            found.group(1)
            for anchor in container.select(".team-home a[href], .team-away a[href]")
            if (found := re.search(r"team_name_id=(\d+)", cast(str, anchor["href"])))
        ]
        match_id = partido.group(1) if partido else ("-".join(team_ids) if len(team_ids) == 2 else str(position))
        matches.append(Match(clean_name(match_id), played, acta_url))
    return matches


def is_complete(matches: list[Match], issues: list[str]) -> bool:
    return bool(matches) and not issues and all(match.played and match.acta_url for match in matches)


# --------------------------------------------------------------------------- validation


def venue(container: Tag) -> str:
    text = node_text(container.select_one(".match-info, .field-info"))
    text = re.sub(r"descarregar acta.*$", "", text, flags=re.I)
    return re.sub(r"^\s*terreny de joc\s*:?", "", text, flags=re.I).strip()


def validate_players(row: Tag, label: str) -> list[str]:
    """Every player of a results row must be linked with a numeric ``codi_jugador`` and a name."""
    issues = []
    cells = row.select("td.player-info")
    if len(cells) != 2:
        return [f"{label}: expected 2 player cells, found {len(cells)}"]
    for side, cell in zip(("left", "right"), cells):
        anchors = cell.find_all("a")
        if not anchors:
            text = node_text(cell)
            issues.append(f"{label} {side}: player {text!r} has no player link" if text else f"{label} {side}: no player")
            continue
        for anchor in anchors:
            query = parse_qs(urlparse(cast(str, anchor.get("href", ""))).query)
            code = (query.get("codi_jugador") or [""])[0]
            name = node_text(anchor)
            if not code.isdigit():
                issues.append(f"{label} {side}: player {name!r} without a codi_jugador link")
            if not name:
                issues.append(f"{label} {side}: player {code or '?'} without a name")
            listed = (query.get("jugador_nom") or [""])[0]
            if name and listed and fold(listed) != fold(name):
                issues.append(f"{label} {side}: player name {name!r} differs from the linked {listed!r}")
    return issues


def validate_match(container: Tag, match: Match) -> list[str]:
    """Validate one match: full acta when played, minimal info (date, time, teams, venue) otherwise."""
    label = f"match {match.match_id}"
    issues = []
    home, away = node_text(container.select_one(".team-home")), node_text(container.select_one(".team-away"))
    if not home or not away:
        issues.append(f"{label}: missing team names")
    if not match.played:
        when = node_text(container.select_one(".match-datetime"))
        if not match_datetime(container):
            issues.append(f"{label}: missing date")
        elif not re.search(r"\d{1,2}:\d{2}", when):
            issues.append(f"{label}: missing time")
        if not venue(container):
            issues.append(f"{label}: missing venue")
        return issues

    table = container.select_one(".match-results-table")
    rows = [row for row in table.select("tr") if row.select_one("td.position")] if table else []
    if not rows:
        return issues + [f"{label}: played ({node_text(container.select_one('.match-score')) or 'no score'}) but without its results table"]
    for number, row in enumerate(rows, start=1):
        issues += validate_players(row, f"{label} game {number}")
    final = SCORE_RE.search(node_text(container.select_one(".match-score")))
    running = [SCORE_RE.search(node_text(row.select_one("td.global"))) for row in rows]
    last = next((score for score in reversed(running) if score), None)
    if final and last:
        final_score, last_score = final.groups(), last.groups()
        if last_score not in (final_score, final_score[::-1]):
            issues.append(f"{label}: results table ends at {'-'.join(last_score)}, final score is {'-'.join(final_score)}")
    return issues


def validate_day(containers: list[Tag], matches: list[Match], expected: int | None) -> list[str]:
    issues = []
    if expected is not None and len(containers) != expected:
        issues.append(f"{len(containers)} matches listed, the league page schedules {expected}")
    for container, match in zip(containers, matches):
        issues += validate_match(container, match)
    return issues


def jornada_check(page_url: str, expected: int | None, tolerate_incomplete: bool) -> Callable[[requests.Response], BeautifulSoup]:
    """Accept a jornada page with matches; reject (to retry) one that fails validation."""

    def check(response: requests.Response) -> BeautifulSoup:
        soup = BeautifulSoup(response.content, "html.parser")
        containers = soup.select(".match-container")
        if not containers:
            raise ContentError("page without matches (the site returned an empty page)")
        issues = validate_day(containers, parse_matches(containers, page_url), expected)
        if issues and not tolerate_incomplete:
            raise IncompleteContent(soup, issues)
        return soup

    return check


# --------------------------------------------------------------------------- storage


def build_document(league: League, season: str, phase: str, day: int, page_url: str, heading: str,
                   fragments: list[Tag], complete: bool, source: str, issues: list[str]) -> tuple[bytes, str]:
    """Return the jornada HTML document and the hash of its match content."""
    for fragment in fragments:
        for anchor in fragment.find_all("a", href=True):
            anchor["href"] = urljoin(page_url, cast(str, anchor["href"]))
    body = "\n".join(str(fragment) for fragment in fragments)
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    meta = {
        STATUS_META: "complete" if complete else "partial",
        HASH_META: content_hash,
        ISSUES_META: " | ".join(issues),
        "season": season,
        "territory": league.territory,
        "category": league.category,
        "group": league.group,
        "phase": phase,
        "match-day": str(day),
        "source-url": page_url,
        # "jornada-page", or "league-page" for a future jornada (minimal match info only).
        "content-source": source,
        "downloaded-at": now_iso(),
    }
    title = f"{league.category} / {league.group} / {phase} / Jornada {day}"
    document = "\n".join([
        "<!DOCTYPE html>",
        '<html lang="ca"><head><meta charset="utf-8">',
        *(f'<meta name="{name}" content="{html.escape(value)}">' for name, value in meta.items()),
        f"<title>{html.escape(title)}</title></head>",
        "<body>",
        f"<h1>{html.escape(heading or league.title)}</h1>",
        f'<section class="jornada" data-jornada="{day}">',
        body,
        "</section>",
        "</body></html>",
        "",
    ])
    return document.encode("utf-8"), content_hash


def read_saved(path: Path) -> tuple[BeautifulSoup | None, dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return None, {}
    soup = BeautifulSoup(path.read_bytes(), "html.parser")
    meta = {cast(str, tag["name"]): cast(str, tag.get("content", "")) for tag in soup.find_all("meta", attrs={"name": True})}
    return soup, meta


def pdf_path(day_dir: Path, match: Match) -> Path:
    return day_dir / f"{match.match_id}.pdf"


def missing_pdfs(day_dir: Path, matches: list[Match]) -> list[Match]:
    """Played matches with a PDF acta that is not downloaded yet."""
    return [
        match for match in matches
        if match.played and match.acta_url
        and not (pdf_path(day_dir, match).exists() and pdf_path(day_dir, match).stat().st_size > 0)
    ]


# --------------------------------------------------------------------------- processing


@dataclass
class Context:
    fetcher: Fetcher
    metrics: Metrics
    args: argparse.Namespace
    logger: logging.Logger
    adaptive: bool


def process_match_day(ctx: Context, league: League, phase: str, day: int, league_dir: Path,
                      scheduled: ScheduledDay | None, league_title: str) -> None:
    args, logger, metrics = ctx.args, ctx.logger, ctx.metrics
    label = f"{league.territory} / {league.category} / {league.group} / {phase} / J{day}"
    key = f"{args.season}/{league.category}/{league.group}/{phase}/J{day}"
    want_html = args.format in ("html", "both")
    want_pdf = args.format in ("pdf", "both") and not args.skip_pdf
    html_file = league_dir / f"jornada_{day:02d}.html"
    day_dir = league_dir / f"jornada_{day:02d}"
    started = time.monotonic()

    saved_soup, saved_meta = read_saved(html_file)
    if not args.force and saved_soup and saved_meta.get(STATUS_META) == "complete":
        saved_matches = parse_matches(saved_soup.select(".match-container"), saved_meta.get("source-url", league.url))
        if not want_pdf or not missing_pdfs(day_dir, saved_matches):
            logger.info("%s: complete, skipped", label)
            metrics.record_match_day(key, "skipped")
            return

    page_url = f"{league.url.rstrip('/')}/?jornada={day}"
    expected = len(scheduled.containers) if scheduled and scheduled.containers else None
    retries = 0
    if is_future_day(scheduled):
        # Nothing has been played yet, so there are no results to wait for: the league page
        # already lists the minimal match info and the jornada page is neither requested nor retried.
        scheduled = cast(ScheduledDay, scheduled)
        containers, heading, source, title = scheduled.containers, scheduled.heading, "league-page", league_title
        logger.info("%s: future match day, keeping minimal match info from the league page", label)
    else:
        tolerate = ctx.adaptive and not args.force and metrics.persistently_incomplete(key)
        if tolerate:
            logger.info("%s: same incomplete content in the last runs, validation issues are not retried", label)
        soup = ctx.fetcher.get(page_url, jornada_check(page_url, expected, tolerate), "jornada", key)
        record = cast(RequestRecord, ctx.fetcher.last)
        retries = record.retries
        if soup is None:
            logger.error("%s: match day not available after retries, skipped (%s)", label, page_url)
            metrics.record_match_day(key, "failed", retries, time.monotonic() - started,
                                     record.errors[-1] if record.errors else record.outcome)
            return
        containers = soup.select(".match-container")
        heading = soup.select_one(".jornada-results-title")
        source, title = "jornada-page", league_page_title(soup) or league_title
        if heading and not re.search(rf"\b{day}\b", heading.get_text(" ", strip=True)):
            logger.warning("%s: page heading %r does not match the requested jornada", label, heading.get_text(" ", strip=True))

    matches = parse_matches(containers, page_url)
    issues = validate_day(containers, matches, expected)
    complete = is_complete(matches, issues)
    for issue in issues:
        logger.error("%s: validation: %s", label, issue)
    played = sum(match.played for match in matches)
    outcome = "future" if source == "league-page" else "incomplete" if issues else "unchanged"

    if want_html:
        fragments = ([heading] if heading else []) + containers
        document, content_hash = build_document(
            league, args.season, phase, day, page_url, title, fragments, complete, source, issues
        )
        status = "complete" if complete else "partial"
        if not args.force and saved_meta.get(HASH_META) == content_hash and saved_meta.get(STATUS_META) == status:
            logger.info("%s: unchanged (%d matches, %d played)", label, len(matches), played)
        else:
            write_atomically(html_file, document)
            if outcome == "unchanged":
                outcome = "updated" if saved_soup else "new"
            logger.info("%s: saved %s (%d matches, %d played, %s)", label, html_file, len(matches), played, status)
    metrics.record_match_day(key, outcome, retries, time.monotonic() - started, issues=issues)

    if want_pdf:
        # Guardrail: only played matches with a published acta link get a PDF.
        targets = [m for m in matches if m.played and m.acta_url] if args.force else missing_pdfs(day_dir, matches)
        for match in targets:
            content = ctx.fetcher.get(cast(str, match.acta_url), pdf_check, "pdf", f"{key}/{match.match_id}")
            if content is None:
                logger.error("%s: PDF acta %s not available, skipped (%s)", label, match.match_id, match.acta_url)
                metrics.count("pdfs failed")
                continue
            write_atomically(pdf_path(day_dir, match), content)
            metrics.count("pdfs downloaded")
            logger.info("%s: saved %s", label, pdf_path(day_dir, match))


def process_league(ctx: Context, league: League) -> None:
    args, logger, metrics = ctx.args, ctx.logger, ctx.metrics
    label = f"{league.territory} / {league.title}"
    soup = ctx.fetcher.get(league.url, html_check(".jornada-btn", ".jornada-results-title"), "league", league.url)
    if soup is None:
        logger.error("%s: league page without match days after retries, skipped (%s)", label, league.url)
        metrics.count("leagues failed")
        return
    season = page_season(soup)
    if season and season != args.season:
        logger.warning("%s: page is for season %s, not %s; skipped", label, season, args.season)
        metrics.count("leagues skipped (season)")
        return
    phase = league.phase or phase_from_text(league_page_title(soup))[0] or DEFAULT_PHASE
    if args.phase and fold(phase) != fold(args.phase):
        return
    days = match_days(soup)
    if args.match_day:
        days = [day for day in days if day in args.match_day]
    if not days:
        logger.info("%s: no match days to download", label)
        return
    metrics.count("leagues processed")
    league_dir = (
        args.output_dir / clean_name(args.season) / clean_name(league.category)
        / clean_name(league.group) / clean_name(phase)
    )
    schedule = league_schedule(soup)
    logger.info("%s: %d match day(s) -> %s", label, len(days), league_dir)
    for day in days:
        try:
            process_match_day(ctx, league, phase, day, league_dir, schedule.get(day), league_page_title(soup))
        except Exception as exc:  # Keep processing the remaining match days.
            metrics.record_match_day(f"{args.season}/{league.category}/{league.group}/{phase}/J{day}", "failed",
                                     error=f"unexpected error: {exc}")
            logger.exception("%s / J%d: unexpected error: %s", label, day, exc)


def retry_policy(args: argparse.Namespace, metrics: Metrics, logger: logging.Logger) -> dict[str, Any]:
    """Retries per request kind and backoff for this run, learnt from previous runs' metrics."""
    policy: dict[str, Any] = {"adaptive": args.adaptive, "retries": {}, "backoff": args.backoff, "delay": args.delay}
    for kind in ("index", "league", "jornada", "pdf"):
        retries = metrics.advised_retries(kind, args.retry) if args.adaptive else args.retry
        policy["retries"][kind] = retries
        estimate = metrics.retry_success_rate(kind)
        if args.adaptive and estimate:
            logger.info("Adaptive retries for %s pages: %d (%.0f%% of %d past retries succeeded)",
                        kind, retries, estimate[0] * 100, estimate[1])
    if args.adaptive and metrics.rate_limited():
        policy["backoff"], policy["delay"] = args.backoff * 2, args.delay * 1.5
        logger.info("Recent failures are mostly rate limiting: backoff %.1fs, delay %.1fs", policy["backoff"], policy["delay"])
    return policy


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = configure_logging(args.log_file)
    metrics = Metrics(args.metrics_file, logger)
    policy = retry_policy(args, metrics, logger)
    for line in metrics.problem_report():
        logger.info("Known problem: %s", line)
    fetcher = Fetcher(policy["retries"], args.retry, policy["delay"], policy["backoff"], args.timeout, logger, metrics)
    ctx = Context(fetcher, metrics, args, logger, args.adaptive)
    logger.info("Downloading actas content for season %s (format=%s, skip_pdf=%s, force=%s)",
                args.season, args.format, args.skip_pdf, args.force)
    if args.season != current_season():
        logger.warning("fctt.cat only lists the current season (%s); leagues from other seasons are skipped", current_season())

    try:
        index = fetcher.get(INDEX_URL, html_check(".jet-engine-listing-overlay-wrap"), "index")
        if index is None:
            logger.error("Could not load the league index %s; every territory is skipped", INDEX_URL)
            metrics.count("index failed")
            return 2
        leagues = [league for league in discover_leagues(index, INDEX_URL) if league_matches_filters(league, args)]
        if not leagues:
            logger.error("No league matches the territory/category/group filters")
            return 2
        logger.info("Found %d league(s) to process", len(leagues))

        for league in leagues:
            try:
                process_league(ctx, league)
            except Exception as exc:  # Keep processing the remaining leagues.
                metrics.count("leagues failed")
                logger.exception("%s / %s: unexpected error: %s", league.territory, league.title, exc)
    finally:
        counters = metrics.run_counters
        summary = ", ".join(f"{count} {name}" for name, count in sorted(counters.items())) or "nothing to do"
        logger.info("Summary: %s; %d request(s), %d retry(ies)", summary, metrics.run_requests, metrics.run_retries)
        metrics.save(args, policy)

    failed = counters["leagues failed"] + counters["match days failed"] + counters["pdfs failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
