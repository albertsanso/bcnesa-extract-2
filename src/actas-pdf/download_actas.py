#!/usr/bin/env python3
"""Download RTBTT match reports (actas) for a season."""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_BASE_URL = "http://rtbtt.com"
DEFAULT_PHASE = "1a Fase"
OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "resources" / "actas-pdf"
USER_AGENT = "rtbtt-actas-downloader/1.0"


@dataclass(frozen=True)
class ReportLink:
    category: str
    group: str
    phase: str
    url: str
    match_id: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True, help="Season, for example 2024-2025")
    parser.add_argument("--category", help="Category to download")
    parser.add_argument("--group", help="Group to download, for example G1")
    parser.add_argument("--phase", default=DEFAULT_PHASE, help=f"Phase (default: {DEFAULT_PHASE})")
    parser.add_argument("--force", action="store_true", help="Re-download existing files")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Website base URL")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between requests in seconds")
    return parser.parse_args(argv)


def season_code(season: str) -> str:
    match = re.fullmatch(r"(\d{4})[-/]?(\d{2,4})", season.strip())
    if not match:
        raise ValueError("season must look like 2024-2025")
    first, second = match.groups()
    return first[2:] + (second[-2:] if len(second) == 4 else second)


def clean_name(value: str) -> str:
    value = re.sub(r"\s+", " ", unquote(value)).strip()
    value = re.sub(r'[<>:"/\\|?*]', "_", value)
    return value.rstrip(".") or "unknown"


def normalise_url(url: str, base_url: str) -> str:
    # The site uses Windows separators in several href attributes.
    url = re.sub(r"[\x00-\x1f\x7f]", "", unquote(url)).strip().replace("\\", "/")
    base_url = re.sub(r"[\x00-\x1f\x7f]", "", unquote(base_url)).strip()
    return urljoin(base_url.rstrip("/") + "/", url)


def report_pdf_url(href: str, index_url: str, base_url: str) -> str:
    href = re.sub(r"[\x00-\x1f\x7f]", "", unquote(href)).strip().replace("\\", "/")
    # Report pages contain paths rooted at the web site even though they omit
    # the leading slash, so resolving them against the index URL would repeat
    # the directory (for example, actes2425/PREF_G1/actes2425/PREF_G1/...).
    if re.match(r"(?:actes\d{4}|lligues\d{4})/", href, re.I):
        return urljoin(base_url, href)
    return urljoin(index_url, href)


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch(session: requests.Session, url: str) -> BeautifulSoup:
    response = session.get(url, timeout=(10, 60))
    response.raise_for_status()
    return BeautifulSoup(response.content, "html.parser")


def link_target(anchor: Tag, base_url: str) -> str | None:
    href = anchor.get("href")
    if not href or href.lower().startswith(("javascript:", "mailto:", "#")):
        javascript = anchor.get("href", "")
        match = re.search(r"loadurl\(['\"]([^'\"]+)", javascript, re.I)
        if not match:
            return None
        href = match.group(1)
    return normalise_url(href, base_url)


def report_index_links(
    session: requests.Session, season: str, base_url: str, delay: float, logger: logging.Logger
) -> list[tuple[str, str, str, str]]:
    """Return category, group, phase, URL entries from the season's actas page."""
    page_url = normalise_url(f"actes_{season_code(season)}.html", base_url)
    soup = fetch(session, page_url)
    entries: list[tuple[str, str, str, str]] = []
    for anchor in soup.find_all("a"):
        target = link_target(anchor, base_url)
        if not target or not re.search(r"\.html(?:$|[?#])", target, re.I):
            continue
        path_parts = [part for part in unquote(urlparse(target).path).split("/") if part]
        if not path_parts or not path_parts[0].casefold().startswith("actes"):
            continue
        slug = path_parts[-1].removesuffix(".html")
        category = category_from_slug(slug)
        if not category:
            continue
        label = anchor.get_text(" ", strip=True)
        group_match = re.search(r"(?:^|_)(G\s*\d+)(?:$|_)", slug, re.I)
        group = group_match.group(1).replace(" ", "").upper() if group_match else ""
        phase = "1a Fase" if group else phase_name(label or slug)
        entries.append((category, group, phase, target))
    time.sleep(max(0, delay))
    logger.info("Found %d report index links at %s", len(entries), page_url)
    return unique_entries(entries)


def category_from_slug(slug: str) -> str | None:
    upper_slug = slug.upper()
    prefix = slug.split("_", 1)[0].casefold()
    names = {
        "pref": "Preferent", "primera": "Primera", "prim": "Primera",
        "segona": "Segona", "segon": "Segona", "tercera": "Tercera",
        "terc": "Tercera", "quarta": "Quarta", "quar": "Quarta",
        "vet": "Veterans",
    }
    category = names.get(prefix)
    if category in {"Segona", "Tercera"}:
        qualifier = re.search(r"(?:SEGONA|TERCERA)_(A|B)(?:_|$)", upper_slug)
        if qualifier:
            category += f' "{qualifier.group(1)}"'
    elif category == "Veterans":
        qualifier = re.search(r"VET_(\d+)(?:_(A|B))?", upper_slug)
        if qualifier:
            category = f"Vet {qualifier.group(1)}a"
            if qualifier.group(2):
                category += f' "{qualifier.group(2)}"'
    return category


def phase_name(label: str) -> str:
    folded = re.sub(r"\s+", " ", label).strip().casefold()
    if folded in {"lliga", "lliga 1a fase", "lliga 1ª fase", "actes"}:
        return "1a Fase"
    if "3a" in folded or "3ª" in folded:
        return "3a Fase"
    if "2a" in folded or "2ª" in folded or "play" in folded or "poff" in folded:
        return "2a Fase"
    return label.strip() or "Other"


def unique_entries(entries: Iterable[tuple[str, str, str, str]]) -> list[tuple[str, str, str, str]]:
    seen: set[tuple[str, str, str, str]] = set()
    result = []
    for entry in entries:
        if entry not in seen:
            seen.add(entry)
            result.append(entry)
    return result


def extract_reports(
    session: requests.Session,
    category: str,
    group: str,
    phase: str,
    index_url: str,
    base_url: str,
    delay: float,
) -> list[ReportLink]:
    soup = fetch(session, index_url)
    reports: list[ReportLink] = []
    for anchor in soup.find_all("a"):
        href = anchor.get("href", "")
        if not re.search(r"\.pdf(?:$|[?#])", href, re.I):
            continue
        target = report_pdf_url(href, index_url, base_url)
        filename = Path(urlparse(target).path).name
        match = re.search(r"(?:jornada|acta)[_ -]?(\d+)", filename, re.I)
        match_id = match.group(1) if match else anchor.get_text(" ", strip=True)
        if not match_id:
            match_id = str(len(reports) + 1)
        reports.append(ReportLink(category, group or "Other", phase, target, clean_name(match_id)))
    time.sleep(max(0, delay))
    return list(
        {
            (report.category, report.group, report.phase, report.match_id): report
            for report in reports
        }.values()
    )


def download_report(
    session: requests.Session, report: ReportLink, destination: Path, force: bool, delay: float
) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force and destination.stat().st_size > 0:
        return "skipped"
    response = session.get(report.url, stream=True, timeout=(10, 120))
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").lower()
    first_chunk = next(response.iter_content(8192), b"")
    if not first_chunk.startswith(b"%PDF") and "pdf" not in content_type:
        raise ValueError("response is not a PDF")
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with temporary.open("wb") as output:
            output.write(first_chunk)
            for chunk in response.iter_content(1024 * 64):
                if chunk:
                    output.write(chunk)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    time.sleep(max(0, delay))
    return "downloaded"


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("download_actas")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler("download_actas.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.addHandler(logging.StreamHandler())
    return logger


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = configure_logging()
    try:
        code = season_code(args.season)
        base_url = args.base_url.rstrip("/") + "/"
        session = make_session()
        indexes = report_index_links(session, args.season, base_url, args.delay, logger)
        selected = [
            entry for entry in indexes
            if (not args.category or entry[0].casefold() == args.category.casefold())
            and (not args.group or entry[1].casefold() == args.group.casefold())
            and entry[2].casefold() == args.phase.casefold()
        ]
        if args.category and not any(entry[0].casefold() == args.category.casefold() for entry in indexes):
            raise ValueError(f"category not found: {args.category}")
        if not selected:
            raise ValueError("no matching category, group, or phase found")
        reports: list[ReportLink] = []
        for category, group, phase, index_url in selected:
            reports.extend(extract_reports(session, category, group, phase, index_url, base_url, args.delay))
        downloaded = skipped = errors = 0
        for report in reports:
            path = OUTPUT_ROOT / clean_name(args.season) / clean_name(report.category) / clean_name(report.group) / clean_name(report.phase) / f"acta_{report.match_id}.pdf"
            try:
                status = download_report(session, report, path, args.force, args.delay)
                downloaded += status == "downloaded"
                skipped += status == "skipped"
            except Exception as exc:  # Keep processing the remaining reports.
                errors += 1
                logger.error("%s: %s", report.url, exc)
        print(f"Summary: {downloaded} downloaded, {skipped} skipped, {errors} errors ({len(reports)} reports found).")
        return 1 if errors else 0
    except (requests.RequestException, ValueError) as exc:
        logger.error("Crawl failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
