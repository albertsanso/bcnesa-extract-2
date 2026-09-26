#!/usr/bin/env python3
"""Download RTBTT match reports (actas) for a season."""

from __future__ import annotations

import argparse
import html
import itertools
import logging
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, cast
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_BASE_URL = "https://rtbtt.com"
DEFAULT_PHASE = "all"
OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "resources" / "actas-html"
USER_AGENT = "rtbtt-actas-downloader/1.0"
PLAY_OFF_TITLE = "Play Off T" + chr(0xED) + "tol"
PLACEHOLDER_MARKER = b'<meta name="acta-status" content="not-published">'
STATUSES = ("downloaded", "skipped", "unpublished", "errors")


@dataclass(frozen=True)
class ReportLink:
    category: str
    group: str
    phase: str
    url: str
    match_id: str
    # False when the match is listed but its acta has not been published yet.
    published: bool = True
    # HTML of the match listing, saved in place of an unpublished acta.
    snapshot: str = ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True, help="Season, for example 2024-2025")
    parser.add_argument("--category", help="Category to download")
    parser.add_argument("--group", help="Group to download, for example G1")
    parser.add_argument("--phase", default=DEFAULT_PHASE, help=f"Phase (default: {DEFAULT_PHASE})")
    parser.add_argument("--force", action="store_true", help="Re-download existing files")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Website base URL")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between requests in seconds")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT, help=f"Output directory (default: {OUTPUT_ROOT})")
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
        javascript = cast(str, anchor.get("href", ""))
        match = re.search(r"loadurl\(['\"]([^'\"]+)", javascript, re.I)
        if not match:
            return None
        href = match.group(1)
    return normalise_url(cast(str, href), base_url)


def index_slug(target: str) -> str | None:
    """Return the slug of a group index URL, or None if the URL is not one.

    Up to 2025-2026 indexes were ``actesYYYY/.../NAME.html`` pages on rtbtt.com;
    from 2026-2027 they are FCTT league pages such as ``fctt.cat/lligues/rtb-pref-2/``.
    """
    parsed = urlparse(target)
    path_parts = [part for part in unquote(parsed.path).split("/") if part]
    if not path_parts:
        return None
    if re.search(r"\.html$", path_parts[-1], re.I):
        if path_parts[0].casefold().startswith(("actes", "lligues")):
            return path_parts[-1][:-len(".html")]
        return None
    if len(path_parts) == 2 and path_parts[0].casefold() == "lligues" and path_parts[1].casefold().startswith("rtb-"):
        return path_parts[1]
    return None


def table_context(anchor: Tag) -> tuple[str | None, int | None, str]:
    """Return the row's category label, the anchor's column and that column's header.

    Column 1 is the league (``Lliga``) column; later columns hold the additional phases
    (``2a FASE``, ``3a FASE``). Columns account for ``colspan`` so empty merged cells do
    not shift the phase columns.
    """
    cell = anchor.find_parent("td")
    row = cell.find_parent("tr") if cell else None
    if not cell or not row:
        return None, None, ""
    cells = row.find_all(["td", "th"], recursive=False)
    if len(cells) < 2 or cell not in cells or cells[0] is cell:
        return None, None, ""
    column = sum(cell_span(previous) for previous in cells[:cells.index(cell)])
    return category_from_label(cells[0].get_text(" ", strip=True)), column, column_header(row, column)


def cell_span(cell: Tag) -> int:
    try:
        return max(1, int(cast(str, cell.get("colspan", 1))))
    except ValueError:
        return 1


def column_header(row: Tag, column: int) -> str:
    """Return the header text of ``column`` from the nearest preceding ``Categoria`` row."""
    for header_row in row.find_previous_siblings("tr"):
        cells = header_row.find_all(["td", "th"], recursive=False)
        if not cells or cells[0].get_text(" ", strip=True).casefold() != "categoria":
            continue
        position = 0
        for cell in cells:
            span = cell_span(cell)
            if position <= column < position + span:
                return re.sub(r"\s+", " ", cell.get_text(" ", strip=True))
            position += span
        return ""
    return ""


def phase_from_column(header: str, category: str | None) -> str | None:
    """Fallback phase for a link whose label and URL do not name its phase."""
    folded = header.casefold()
    if re.search(r"\b3a?\s*fase\b", folded):
        # The third phase column only holds the play-off.
        return PLAY_OFF_TITLE if category_is_vet_1a(category) else "Play Off Ascens"
    if re.search(r"\b2a?\s*fase\b", folded):
        return "2a Fase"
    return None


def expected_phases(category: str) -> list[str]:
    """Phases every competition is expected to have, in season order."""
    if category_is_vet_1a(category):
        return ["1a Fase", "TITOL", "DESCENS", PLAY_OFF_TITLE]
    return ["1a Fase", "ASCENS", "DESCENS", "Play Off Ascens"]


def report_index_links(
    session: requests.Session, season: str, base_url: str, delay: float, logger: logging.Logger
) -> list[tuple[str, str, str, str]]:
    """Return category, group, phase, URL entries from the season's actas page."""
    page_url = normalise_url(f"actes_{season_code(season)}.html", base_url)
    soup = fetch(session, page_url)
    entries: list[tuple[str, str, str, str]] = []
    for anchor in soup.find_all("a"):
        target = link_target(anchor, base_url)
        slug = index_slug(target) if target else None
        if not target or not slug:
            continue
        row_category, column, header = table_context(anchor)
        category = row_category or category_from_slug(slug)
        if not category:
            logger.warning("Skipping index link with unknown category: %s", target)
            continue
        label = anchor.get_text(" ", strip=True)
        # FCTT slugs do not encode the group reliably (rtb-seg-a-2 is G1), so prefer the label.
        group_match = re.search(r"\b(G\s*\d+)\b", label, re.I) or re.search(r"(?:^|_)(G\s*\d+)(?:$|_)", slug, re.I)
        group = group_match.group(1).replace(" ", "").upper() if group_match else ""
        if column == 1:
            phase = "1a Fase"
        else:
            phase = phase_from_slug(slug, category) or phase_name(label, category)
            if column and phase == "1a Fase":
                # Links after the Lliga column are later phases; "1a" in an FCTT slug is
                # usually the category (rtb-vet-1a-...) and "Actes" is a generic label.
                phase = phase_name(label, category)
                phase = "" if phase == "1a Fase" else phase
            if phase not in known_phases():
                phase = phase_from_column(header, category) or phase
        if phase not in known_phases():
            if column and column > 1:
                # Unlabelled second-phase groups (for example "A", "B") are still a later phase.
                group = group or clean_name(label)
                phase = "2a Fase"
            else:
                phase = "1a Fase"
        entries.append((category, group, phase, target))
    time.sleep(max(0, delay))
    logger.info("Found %d report index links at %s", len(entries), page_url)
    return unique_entries(entries)


def category_from_label(label: str) -> str | None:
    """Normalise a season-table row header such as ``Vet 2a A`` to ``Vet 2a "A"``."""
    label = re.sub(r"\s+", " ", label).strip()
    if not label or label.casefold() in {"categoria", "actes:"}:
        return None
    qualified = re.fullmatch(r"(.+?) \"?([A-D])\"?", label)
    if qualified:
        return f'{qualified.group(1)} "{qualified.group(2)}"'
    return label


def category_from_slug(slug: str) -> str | None:
    fctt = re.fullmatch(r"rtb-(.+?)(?:-\d+)*", slug, re.I)
    if fctt:
        return category_from_fctt_slug(fctt.group(1))

    prefix_slug = slug.split("_", 1)[0].casefold()
    if prefix_slug in {"actes", "lligues"}:
        slug = slug.split("_", 1)[1] if "_" in slug else ""
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
        segona_qualifier = re.search(r"(?:SEGONA|TERCERA)_([AB])(?:_|$)", upper_slug)
        if segona_qualifier:
            category += f' "{segona_qualifier.group(1)}"'
    elif category == "Veterans":
        veteran_qualifier = re.search(r"VET_(\d+)(?:_([AB]))?", upper_slug)
        if veteran_qualifier:
            category = f"Vet {veteran_qualifier.group(1)}a"
            if veteran_qualifier.group(2):
                category += f' "{veteran_qualifier.group(2)}"'
    return category


def category_from_fctt_slug(slug: str) -> str | None:
    """Map an FCTT league slug body (``pref``, ``seg-a``, ``vet-2aa``...) to a category."""
    slug = slug.casefold()
    names = {"pref": "Preferent", "prim": "Primera", "seg": "Segona", "ter": "Tercera", "quar": "Quarta"}
    match = re.fullmatch(r"(pref|prim|seg|ter|quar)(?:-([a-d]))?", slug)
    if match:
        category = names[match.group(1)]
        return category + (f' "{match.group(2).upper()}"' if match.group(2) else "")
    match = re.fullmatch(r"(\d)a-com", slug)
    if match:
        return f"{match.group(1)}a Comarcal"
    match = re.fullmatch(r"vet-(\d)a([a-d])?", slug)
    if match:
        return f"Vet {match.group(1)}a" + (f' "{match.group(2).upper()}"' if match.group(2) else "")
    return None


def category_is_vet_1a(category: str | None) -> bool:
    return bool(category and re.fullmatch(r"vet\s*1a(?:\s+\"[AB]\")?", category.strip(), re.I))


def phase_name(label: str, category: str | None = None) -> str:
    folded = re.sub(r"\s+", " ", label).strip().casefold()
    folded = "".join(
        character
        for character in unicodedata.normalize("NFD", folded)
        if unicodedata.category(character) != "Mn"
    )
    folded = folded.replace("ª", "a")
    folded = re.sub(r"[_-]+", " ", folded)
    if folded in {"lliga", "lliga 1a fase", "actes", "1a fase", "1a fase lliga"}:
        return "1a Fase"
    if "play" in folded and "off" in folded or "poff" in folded:
        return PLAY_OFF_TITLE if category_is_vet_1a(category) else "Play Off Ascens"
    if "titol" in folded or "ttol" in folded:
        return "TITOL"
    if "ascens" in folded:
        return "ASCENS"
    if "descens" in folded:
        return "DESCENS"
    if re.search(r"\b3a?\s+fase\b", folded):
        return "3a Fase"
    if re.search(r"\b2a?\s+fase\b", folded):
        return "2a Fase"
    return label.strip() or "Other"


def phase_from_slug(slug: str, category: str | None = None) -> str | None:
    """Extract an explicit phase from an index slug for any competition."""
    category = category or category_from_slug(slug)
    folded = re.sub(r"[_-]+", " ", slug).casefold()
    folded = "".join(
        character
        for character in unicodedata.normalize("NFD", folded)
        if unicodedata.category(character) != "Mn"
    )
    if re.search(r"\bplay\s*offs?\b|\bpoff\b", folded):
        return PLAY_OFF_TITLE if category_is_vet_1a(category) else "Play Off Ascens"
    for marker, phase in (("titol", "TITOL"), ("ttol", "TITOL"), ("ascens", "ASCENS"), ("descens", "DESCENS")):
        if re.search(rf"\b{marker}\b", folded):
            return phase
    if re.search(r"\b(?:1a|1a fase|lliga)\b", folded):
        return "1a Fase"
    return None


def known_phases() -> set[str]:
    return {"1a Fase", "2a Fase", "3a Fase", "TITOL", "ASCENS", "DESCENS", "Play Off Títol", "Play Off Ascens"}


def unique_entries(entries: Iterable[tuple[str, str, str, str]]) -> list[tuple[str, str, str, str]]:
    seen: set[tuple[str, str, str, str]] = set()
    result = []
    for entry in entries:
        if entry not in seen:
            seen.add(entry)
            result.append(entry)
    return result


def select_index_links(
    indexes: Iterable[tuple[str, str, str, str]],
    category: str | None,
    group: str | None,
    phase: str,
) -> list[tuple[str, str, str, str]]:
    """Filter indexes, with ``all`` selecting every discovered phase."""
    return [
        entry for entry in indexes
        if (not category or entry[0].casefold() == category.casefold())
        and (not group or entry[1].casefold() == group.casefold())
        and (phase.casefold() == "all" or entry[2].casefold() == phase.casefold())
    ]


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
    if soup.select_one(".match-container"):
        reports = parse_fctt_reports(soup, category, group, phase, index_url)
    else:
        reports = parse_pdf_index_reports(soup, category, group, phase, index_url, base_url)
    time.sleep(max(0, delay))
    return list(
        {
            (report.category, report.group, report.phase, report.match_id): report
            for report in reports
        }.values()
    )


def parse_fctt_reports(
    soup: BeautifulSoup, category: str, group: str, phase: str, index_url: str
) -> list[ReportLink]:
    """Parse an FCTT league page, which lists every jornada's matches on one page.

    Every ``.match-container`` yields a report, so matches that have not been played or
    whose acta is not published yet are kept (with ``published=False``) and saved as a
    placeholder instead of being skipped.
    """
    reports: list[ReportLink] = []
    positions: dict[str, int] = {}
    for container in soup.select(".match-container"):
        jornada = container_jornada(container)
        positions[jornada] = position = positions.get(jornada, 0) + 1
        team_ids = [
            match.group(1)
            for anchor in container.select(".team-home a, .team-away a")
            if (match := re.search(r"team_name_id=(\d+)", cast(str, anchor.get("href", ""))))
        ]
        # The PDF converter reads the jornada from the trailing number of the file name.
        prefix = "-".join(team_ids) if len(team_ids) == 2 else str(position)
        href = acta_href(container)
        reports.append(ReportLink(
            category,
            group or "Other",
            phase,
            urljoin(index_url, href) if href else "",
            clean_name(f"{prefix}_{jornada}"),
            published=bool(href),
            snapshot=str(container),
        ))
    return reports


def container_jornada(container: Tag) -> str:
    """Return the jornada number of a match, from its heading or, failing that, its links."""
    heading = container.find_previous(class_="jornada-results-title")
    match = re.search(r"(\d+)", heading.get_text(" ", strip=True)) if heading else None
    if not match:
        attribute = cast(str, container.get("data-jornada", ""))
        match = re.search(r"(\d+)", attribute) or next(
            (
                found
                for anchor in container.find_all("a", href=True)
                if (found := re.search(r"[?&]jornada=(\d+)", cast(str, anchor["href"])))
            ),
            None,
        )
    return match.group(1) if match else "0"


def acta_href(container: Tag) -> str | None:
    """Return the acta link of a match container, or None when it is not published."""
    candidates = [
        anchor
        for anchor in container.find_all("a", href=True)
        if not re.search(r"team_name_id=|[?&]jornada=|^(?:#|javascript:|mailto:)", cast(str, anchor["href"]), re.I)
    ]
    for anchor in candidates:
        if re.search(r"\.(?:pdf|html?)(?:$|[?#])|acta|acte|informe", f"{anchor['href']} {anchor.get_text(' ', strip=True)}", re.I):
            return cast(str, anchor["href"])
    # A link on the score is the acta on layouts that do not label it.
    for anchor in candidates:
        if anchor.find_parent(class_="match-score"):
            return cast(str, anchor["href"])
    return None


def parse_pdf_index_reports(
    soup: BeautifulSoup, category: str, group: str, phase: str, index_url: str, base_url: str
) -> list[ReportLink]:
    """Parse a legacy rtbtt.com index page that links one PDF per jornada."""
    reports: list[ReportLink] = []
    for anchor in soup.find_all("a"):
        href = cast(str, anchor.get("href", ""))
        if not re.search(r"\.pdf(?:$|[?#])", href, re.I):
            continue
        target = report_pdf_url(href, index_url, base_url)
        filename = Path(urlparse(target).path).name
        match = re.search(r"(?:jornada|acta)[_ -]?(\d+)", filename, re.I)
        match_id = match.group(1) if match else anchor.get_text(" ", strip=True)
        if not match_id:
            match_id = str(len(reports) + 1)
        reports.append(ReportLink(category, group or "Other", phase, target, clean_name(match_id)))
    return reports


def acta_stem(root: Path, season: str, report: ReportLink) -> Path:
    """Return the acta path without extension: season/category/group/phase/acta_<id>."""
    return (
        root / clean_name(season) / clean_name(report.category) / clean_name(report.group)
        / clean_name(report.phase) / f"acta_{report.match_id}"
    )


def with_suffix(stem: Path, suffix: str) -> Path:
    # Path.with_suffix would treat dots inside match ids as an extension.
    return stem.parent / (stem.name + suffix)


def is_placeholder(path: Path) -> bool:
    if path.suffix != ".html" or not path.exists():
        return False
    with path.open("rb") as handle:
        return PLACEHOLDER_MARKER in handle.read(1024)


def published_acta(stem: Path) -> Path | None:
    """Return an already downloaded (non-placeholder) acta for ``stem``, if any."""
    for suffix in (".pdf", ".html"):
        path = with_suffix(stem, suffix)
        if path.exists() and path.stat().st_size > 0 and not is_placeholder(path):
            return path
    return None


def acta_format(first_chunk: bytes, content_type: str) -> str | None:
    """Detect whether a response is a PDF or an HTML acta."""
    head = first_chunk.lstrip()[:512].lower()
    if head.startswith(b"%pdf") or "pdf" in content_type:
        return ".pdf"
    if "html" in content_type or head.startswith((b"<!doctype html", b"<html")) or b"<body" in head:
        return ".html"
    return None


def write_atomically(destination: Path, chunks: Iterable[bytes]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = with_suffix(destination, ".part")
    try:
        with temporary.open("wb") as output:
            for chunk in chunks:
                if chunk:
                    output.write(chunk)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def save_unpublished(report: ReportLink, stem: Path, reason: str) -> str:
    """Save a placeholder HTML acta for a match whose acta is empty or not published.

    Placeholders are refreshed on every run (the match date or venue may change) and are
    replaced once the real acta is downloaded. An acta that was already downloaded is kept.
    """
    if published_acta(stem):
        return "skipped"
    title = html.escape(f"{report.category} / {report.group} / {report.phase} / acta_{report.match_id}")
    source = f'<p>Source: <a href="{html.escape(report.url)}">{html.escape(report.url)}</a></p>' if report.url else ""
    document = "\n".join([
        '<!DOCTYPE html>',
        '<html><head><meta charset="utf-8">' + PLACEHOLDER_MARKER.decode() + f"<title>{title}</title></head>",
        f"<body><h1>{title}</h1>",
        f"<p>Acta status: {html.escape(reason)}</p>",
        source,
        report.snapshot,
        "</body></html>",
        "",
    ])
    write_atomically(with_suffix(stem, ".html"), [document.encode("utf-8")])
    return "unpublished"


def download_report(
    session: requests.Session, report: ReportLink, stem: Path, force: bool, delay: float
) -> str:
    """Download a published acta as ``stem.pdf`` or ``stem.html`` depending on its format."""
    if not report.published:
        return save_unpublished(report, stem, "not published")
    if not force and published_acta(stem):
        return "skipped"
    response = session.get(report.url, stream=True, timeout=(10, 120))
    try:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        chunks = response.iter_content(1024 * 64)
        first_chunk = next(chunks, b"")
        if not first_chunk.strip():
            return save_unpublished(report, stem, "empty acta")
        suffix = acta_format(first_chunk, content_type)
        if not suffix:
            raise ValueError(f"response is neither a PDF nor HTML ({content_type or 'no content type'})")
        write_atomically(with_suffix(stem, suffix), itertools.chain([first_chunk], chunks))
    finally:
        response.close()
    # Drop the placeholder, or a stale acta in the other format, now that the real one exists.
    other = with_suffix(stem, ".html" if suffix == ".pdf" else ".pdf")
    other.unlink(missing_ok=True)
    time.sleep(max(0, delay))
    return "downloaded"


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("download_actas")
    logger.setLevel(logging.INFO)
    if not logger.handlers:  # main() may run more than once in the same process.
        handler = logging.FileHandler("download_actas.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.addHandler(logging.StreamHandler())
    return logger


def log_missing_phases(indexes: Iterable[tuple[str, str, str, str]], logger: logging.Logger) -> None:
    """Report expected phases that the season page does not link yet."""
    found: dict[str, set[str]] = {}
    for category, _, phase, _ in indexes:
        found.setdefault(category, set()).add(phase)
    for category, phases in found.items():
        missing = [phase for phase in expected_phases(category) if phase not in phases]
        if "1a Fase" in missing:
            logger.error("%s: no 1a Fase index found on the season page", category)
        elif missing:
            logger.info("%s: phases not published yet: %s", category, ", ".join(missing))


def phase_summary(results: dict[str, dict[str, int]]) -> str:
    return ", ".join(
        f"{phase} (" + ", ".join(f"{result[status]} {status}" for status in STATUSES) + ")"
        for phase, result in sorted(results.items())
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = configure_logging()
    try:
        season_code(args.season)
        base_url = args.base_url.rstrip("/") + "/"
        session = make_session()
        indexes = report_index_links(session, args.season, base_url, args.delay, logger)
        selected = select_index_links(indexes, args.category, args.group, args.phase)
        log_missing_phases(select_index_links(indexes, args.category, None, "all"), logger)
        if args.category and not any(entry[0].casefold() == args.category.casefold() for entry in indexes):
            raise ValueError(f"category not found: {args.category}")
        if not selected:
            raise ValueError("no matching category, group, or phase found")
        reports: list[ReportLink] = []
        phase_results: dict[str, dict[str, int]] = {}

        def count(phase: str, status: str) -> None:
            phase_results.setdefault(phase, dict.fromkeys(STATUSES, 0))[status] += 1

        for _, _, phase, _ in selected:
            phase_results.setdefault(phase, dict.fromkeys(STATUSES, 0))
        for category, group, phase, index_url in selected:
            try:
                found = extract_reports(session, category, group, phase, index_url, base_url, args.delay)
            except Exception as exc:  # Keep processing the remaining indexes.
                count(phase, "errors")
                logger.error("Index %s / %s / %s (%s): %s", category, group or "Other", phase, index_url, exc)
                continue
            if not found:
                logger.warning("No matches listed yet for %s / %s / %s (%s)", category, group or "Other", phase, index_url)
            reports.extend(found)
        for report in reports:
            stem = acta_stem(args.output_root, args.season, report)
            try:
                count(report.phase, download_report(session, report, stem, args.force, args.delay))
            except Exception as exc:  # Keep processing the remaining reports.
                count(report.phase, "errors")
                logger.error("%s / %s / %s / acta_%s (%s): %s", report.category, report.group, report.phase, report.match_id, report.url, exc)
        totals = {status: sum(result[status] for result in phase_results.values()) for status in STATUSES}
        print(
            "Summary: " + ", ".join(f"{totals[status]} {status}" for status in STATUSES)
            + f" ({len(reports)} reports found; phases: {phase_summary(phase_results) or 'none'})."
        )
        return 1 if totals["errors"] else 0
    except (requests.RequestException, ValueError) as exc:
        logger.error("Crawl failed: %s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
