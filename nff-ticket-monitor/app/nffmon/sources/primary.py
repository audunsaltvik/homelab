"""Primary sale scraper (billett.fotball.no).

The performances fragment is one request per *product* and returns every match
underneath it. That is why polling every 60s during an onsale is cheap: a
Nations League home double-header costs one request, not two.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .. import endpoints
from ..httpclient import HttpClient

logger = logging.getLogger(__name__)


class ParseError(RuntimeError):
    pass


# Abbreviated Norwegian months as SecuTix writes them in the a11y date string.
MONTHS = {
    "januar": 1, "february": 2, "februar": 2, "mars": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9,
    "oktober": 10, "november": 11, "desember": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "des": 12,
}

DATETIME_RE = re.compile(endpoints.PRIMARY_DATETIME_RE, re.IGNORECASE)
ONCLICK_RE = re.compile(endpoints.PRIMARY_ONCLICK_URL_RE)


@dataclass
class Performance:
    performance_id: str
    product_id: int
    name: str  # "Norge vs Danmark"
    home_team: str
    away_team: str
    kickoff: datetime | None
    kickoff_text: str
    venue: str
    state: str  # available | sold_out | unknown
    has_resale_hint: bool
    min_price_text: str
    min_price_nok: float | None
    link: str

    @property
    def opponent(self) -> str:
        """Whichever side is not Norway, for the notification body."""
        if self.home_team.lower().startswith("norge"):
            return self.away_team
        if self.away_team.lower().startswith("norge"):
            return self.home_team
        return ""


def _text(element, attr: str | None = None) -> str:
    if element is None:
        return ""
    if attr:
        return (element.get(attr) or "").strip()
    return re.sub(r"\s+", " ", element.get_text()).strip()


def _parse_kickoff(element, tz: ZoneInfo) -> tuple[datetime | None, str]:
    node = element.select_one(endpoints.PRIMARY_DATETIME_SELECTOR)
    raw = _text(node)
    if not raw:
        return None, ""
    # Strip the "Date and time:" prefix that the a11y span carries.
    display = re.sub(r"^[^:]*:\s*", "", raw).strip()

    match = DATETIME_RE.search(raw)
    if not match:
        logger.warning("could not parse kickoff from %r", raw)
        return None, display

    month = MONTHS.get(match.group("month").lower())
    if month is None:
        logger.warning("unknown month %r in kickoff %r", match.group("month"), raw)
        return None, display

    return (
        datetime(
            int(match.group("year")),
            month,
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            tzinfo=tz,
        ),
        display,
    )


def _parse_price(element) -> tuple[str, float | None]:
    node = element.select_one(endpoints.PRIMARY_MIN_PRICE_SELECTOR)
    if node is None:
        return "", None
    text = _text(node)
    raw_amount = node.get(endpoints.PRIMARY_MIN_PRICE_ATTR)
    amount = None
    if raw_amount:
        try:
            amount = int(raw_amount) / endpoints.PRIMARY_MIN_PRICE_DIVISOR
        except ValueError:
            logger.warning("non-numeric %s=%r", endpoints.PRIMARY_MIN_PRICE_ATTR, raw_amount)
    return (f"Fra {text}" if text else ""), amount


def _parse_link(element, performance_id: str, product_id: int) -> str:
    onclick = element.get("onclick") or ""
    match = ONCLICK_RE.search(onclick)
    if match:
        path = match.group(1)
        if path.startswith("/"):
            return f"{endpoints.HOST_PRIMARY}{path}"
        return path
    # Sold-out performances have no onclick; fall back to the product page.
    return endpoints.PRIMARY_EVENT_PAGE_URL.format(product_id=product_id)


def parse_performances(html: str, product_id: int, tz: ZoneInfo) -> list[Performance]:
    soup = BeautifulSoup(html, "lxml")
    elements = soup.select(endpoints.PRIMARY_PERFORMANCE_SELECTOR)
    if not elements:
        # Distinguish "this product currently has no matches" - normal between
        # seasons - from "we no longer understand this response". Only the
        # latter is worth an alarm; the former would cry wolf for months.
        if soup.select_one(endpoints.PRIMARY_FRAGMENT_MARKER_SELECTOR) is not None:
            logger.info("productId=%s currently has no matches", product_id)
            return []
        raise ParseError(
            f"response for productId={product_id} is missing "
            f"{endpoints.PRIMARY_FRAGMENT_MARKER_SELECTOR!r} - markup changed"
        )

    performances: list[Performance] = []
    for element in elements:
        classes = element.get("class") or []
        performance_id = (element.get(endpoints.PRIMARY_PERFORMANCE_ID_ATTR) or "").strip()
        if not performance_id.isdigit():
            logger.warning("performance element without numeric id: %r", performance_id)
            continue

        if endpoints.PRIMARY_CLASS_AVAILABLE in classes:
            state = "available"
        elif endpoints.PRIMARY_CLASS_SOLD_OUT in classes:
            state = "sold_out"
        else:
            # Neither class is a genuine unknown (e.g. "not yet on sale"), and
            # must not be reported as availability.
            state = "unknown"

        home = _text(
            element.select_one(endpoints.PRIMARY_TEAM_HOME_SELECTOR),
            endpoints.PRIMARY_TEAM_NAME_ATTR,
        )
        away = _text(
            element.select_one(endpoints.PRIMARY_TEAM_AWAY_SELECTOR),
            endpoints.PRIMARY_TEAM_NAME_ATTR,
        )
        kickoff, kickoff_text = _parse_kickoff(element, tz)
        price_text, price_nok = _parse_price(element)

        performances.append(
            Performance(
                performance_id=performance_id,
                product_id=product_id,
                name=f"{home} vs {away}" if home and away else (home or away or performance_id),
                home_team=home,
                away_team=away,
                kickoff=kickoff,
                kickoff_text=kickoff_text,
                venue=_text(
                    element.select_one(endpoints.PRIMARY_VENUE_SELECTOR), "title"
                )
                or _text(element.select_one(endpoints.PRIMARY_VENUE_SELECTOR)),
                state=state,
                has_resale_hint=endpoints.PRIMARY_CLASS_HAS_RESALE in classes,
                min_price_text=price_text,
                min_price_nok=price_nok,
                link=_parse_link(element, performance_id, product_id),
            )
        )

    return performances


def fetch_performances(
    client: HttpClient, product_id: int, tz: ZoneInfo
) -> list[Performance]:
    url = endpoints.PRIMARY_PERFORMANCES_URL.format(product_id=product_id)
    response = client.get(url)
    response.raise_for_status()
    return parse_performances(response.text, product_id, tz)


def fetch_catalog(client: HttpClient) -> list[dict]:
    """Product catalogue, used by `list-products` to find ids for values.yaml."""
    data = client.get_json(endpoints.PRIMARY_CATALOG_URL)
    products: list[dict] = []
    for topic in data.get("topicWithProductsList", []):
        products.extend(topic.get("products", []))
    return products
