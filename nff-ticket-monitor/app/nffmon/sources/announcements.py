"""Parser for the NFF announcement page (www.fotball.no).

This is where new fixtures and their sale dates are published, weeks ahead of
the tickets actually existing in the SecuTix catalogue. The sale dates parsed
here are what drive the availability watcher's hot window.

Note: robots.txt on www.fotball.no disallows all non-allowlisted agents. That
is a deliberate, operator-accepted exception configured via ANNOUNCE_ENABLED;
httpclient logs every fetch of a disallowed URL.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .. import endpoints
from ..httpclient import HttpClient

logger = logging.getLogger(__name__)


class ParseError(RuntimeError):
    pass


NORWEGIAN_MONTHS = {
    "januar": 1,
    "februar": 2,
    "mars": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "desember": 12,
}

# "Onsdag 19. august kl 12:00:" - the weekday is optional and the time
# separator is either ":" or "." because the page uses both.
PHASE_DATE_RE = re.compile(
    r"(?:(?P<weekday>\w+)\s+)?"
    r"(?P<day>\d{1,2})\.\s*(?P<month>[a-zæøå]+)"
    r"\s+kl\.?\s*(?P<hour>\d{1,2})[:.](?P<minute>\d{2})",
    re.IGNORECASE,
)

# "NORGE - WALES 14. november" -> teams + day + month
TITLE_RE = re.compile(
    r"^(?P<teams>.+?)\s+(?P<day>\d{1,2})\.\s*(?P<month>[a-zæøå]+)\s*$",
    re.IGNORECASE,
)

YEAR_RE = re.compile(r"(\d{4})")


@dataclass
class SalePhase:
    name: str
    starts_at: datetime
    description: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "starts_at": self.starts_at.isoformat(),
            "description": self.description,
        }


@dataclass
class AnnouncedMatch:
    key: str
    title: str
    label: str
    kickoff_date: date | None
    status: str  # sold_out | info_pending | announced
    phases: list[SalePhase] = field(default_factory=list)

    @property
    def home_team(self) -> str:
        return self.label.split(endpoints.ANN_TEAM_SEPARATOR)[0].strip()

    @property
    def is_home_match(self) -> bool:
        """True for fixtures played in Norway, i.e. "NORGE - X"."""
        return self.home_team.lower().startswith(endpoints.ANN_HOME_TEAM)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "label": self.label,
            "kickoff_date": self.kickoff_date.isoformat() if self.kickoff_date else None,
            "status": self.status,
            "phases": [p.to_dict() for p in self.phases],
        }


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _slug(text: str) -> str:
    decomposed = (
        text.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a")
    )
    decomposed = unicodedata.normalize("NFKD", decomposed)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_only)).strip("-")


def _classify_phase(description: str) -> str:
    haystack = description.lower()
    for name, needles in endpoints.ANN_PHASE_PATTERNS:
        if all(needle in haystack for needle in needles):
            return name
    return endpoints.ANN_PHASE_FALLBACK


def _parse_phases(body, section_year: int, kickoff: date | None, tz: ZoneInfo) -> list[SalePhase]:
    """Pull sale phases out of a match body.

    A phase is a <strong> holding the date/time followed by loose text or
    <span>s holding the description, up to the next such <strong>.
    """
    phases: list[SalePhase] = []
    strongs = body.select(endpoints.ANN_PHASE_STRONG_SELECTOR)

    for strong in strongs:
        match = PHASE_DATE_RE.search(_normalise(strong.get_text()))
        if not match:
            continue

        month = NORWEGIAN_MONTHS.get(match.group("month").lower())
        if month is None:
            logger.warning("unknown Norwegian month %r in phase", match.group("month"))
            continue

        description_parts = []
        for sibling in strong.next_siblings:
            if getattr(sibling, "name", None) == "strong" and PHASE_DATE_RE.search(
                _normalise(sibling.get_text())
            ):
                break
            text = sibling if isinstance(sibling, str) else sibling.get_text()
            description_parts.append(text)
        description = _normalise("".join(description_parts)).lstrip(": ").strip()

        starts_at = datetime(
            section_year,
            month,
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            tzinfo=tz,
        )
        # Sale dates carry no year on the page. They always precede kickoff, so
        # a computed date landing after kickoff means the sale belongs to the
        # previous calendar year (a December onsale for a January fixture).
        if kickoff is not None:
            kickoff_end = datetime.combine(kickoff, time.max, tzinfo=tz)
            if starts_at > kickoff_end:
                starts_at = starts_at.replace(year=section_year - 1)

        phases.append(
            SalePhase(
                name=_classify_phase(description),
                starts_at=starts_at,
                description=description or "(ingen beskrivelse)",
            )
        )

    return phases


def parse(html: str, tz: ZoneInfo) -> list[AnnouncedMatch]:
    soup = BeautifulSoup(html, "lxml")

    section = soup.select_one(endpoints.ANN_SECTION_SELECTOR)
    if section is None:
        raise ParseError(
            f"no element matched {endpoints.ANN_SECTION_SELECTOR!r} - page layout changed"
        )

    heading_el = section.select_one(endpoints.ANN_SECTION_HEADING_SELECTOR)
    heading = _normalise(heading_el.get_text()) if heading_el else ""
    year_match = YEAR_RE.search(heading)
    if not year_match:
        raise ParseError(f"no year in section heading {heading!r} - cannot date fixtures")
    section_year = int(year_match.group(1))

    matches: list[AnnouncedMatch] = []
    for element in section.select(endpoints.ANN_MATCH_SELECTOR):
        title_el = element.select_one(endpoints.ANN_MATCH_TITLE_SELECTOR)
        body_el = element.select_one(endpoints.ANN_MATCH_BODY_SELECTOR)
        if title_el is None or body_el is None:
            continue

        title = _normalise(title_el.get_text())
        if not title:
            continue

        title_match = TITLE_RE.match(title)
        label = title
        kickoff_date = None
        if title_match:
            label = _normalise(title_match.group("teams")).title()
            month = NORWEGIAN_MONTHS.get(title_match.group("month").lower())
            if month is not None:
                kickoff_date = date(section_year, month, int(title_match.group("day")))

        body_text = _normalise(body_el.get_text()).lower()
        if endpoints.ANN_MARKER_SOLD_OUT in body_text:
            status = "sold_out"
        elif endpoints.ANN_MARKER_INFO_PENDING in body_text:
            status = "info_pending"
        else:
            status = "announced"

        phases = _parse_phases(body_el, section_year, kickoff_date, tz)
        key = _slug(label)
        if kickoff_date:
            key = f"{key}-{kickoff_date.isoformat()}"

        matches.append(
            AnnouncedMatch(
                key=key,
                title=title,
                label=label,
                kickoff_date=kickoff_date,
                status=status,
                phases=phases,
            )
        )

    if not matches:
        raise ParseError(
            "announcement section found but no fixtures parsed - markup changed"
        )
    return matches


def fetch(client: HttpClient, tz: ZoneInfo) -> list[AnnouncedMatch]:
    response = client.get(endpoints.ANNOUNCEMENTS_URL)
    response.raise_for_status()
    return parse(response.text, tz)
