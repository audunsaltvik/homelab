"""Resale scraper (resale.fotball.no).

Confirmed 2026-08-06: listings are readable anonymously. Login is required to
buy, not to look, so this monitor holds no credentials and no session.

Caveat worth knowing when this breaks: at the time of writing there were zero
resale tickets in the entire NFF system, so only the *empty* response shape
could be observed. The parser is therefore written as "is this recognisably
the empty state?" - anything else counts as availability and notifies. That
fails toward a false alarm rather than toward silence, which is the right way
round for a monitor whose whole job is to not miss an opening.
"""

import logging
from dataclasses import dataclass

from .. import endpoints
from ..httpclient import HttpClient

logger = logging.getLogger(__name__)


class ParseError(RuntimeError):
    pass


@dataclass
class ResaleStatus:
    performance_id: str
    state: str  # available | sold_out | unknown
    item_count: int
    price_text: str
    link: str


def _price_text(items: list[dict]) -> str:
    """Best-effort price summary; field names are unverified against live data."""
    prices = []
    for item in items:
        for key in ("price", "amount", "displayPrice", "minPrice"):
            value = item.get(key)
            if isinstance(value, (int, float)) and value > 0:
                prices.append(float(value))
                break
    if not prices:
        return ""
    low, high = min(prices), max(prices)
    if low == high:
        return f"{low:.0f} NOK"
    return f"{low:.0f}-{high:.0f} NOK"


def parse_items(payload: dict, performance_id: str) -> ResaleStatus:
    link = endpoints.RESALE_ITEM_PAGE_URL.format(performance_id=performance_id)

    if not isinstance(payload, dict) or endpoints.RESALE_ITEMS_KEY not in payload:
        raise ParseError(
            f"resale response for performanceId={performance_id} has no "
            f"{endpoints.RESALE_ITEMS_KEY!r} key - API shape changed"
        )

    items = payload.get(endpoints.RESALE_ITEMS_KEY) or []
    if not isinstance(items, list):
        raise ParseError(
            f"{endpoints.RESALE_ITEMS_KEY!r} is {type(items).__name__}, expected list"
        )

    return ResaleStatus(
        performance_id=performance_id,
        state="available" if items else "sold_out",
        item_count=len(items),
        price_text=_price_text(items),
        link=link,
    )


def fetch_status(client: HttpClient, performance_id: str) -> ResaleStatus:
    url = endpoints.RESALE_ITEMS_URL.format(performance_id=performance_id)
    response = client.get(url, accept="application/json")

    # SecuTix answers 404 with an HTML "no resale tickets for this match" page
    # on some routes. That is an answer, not a failure.
    if response.status_code == 404:
        logger.info("resale returned 404 for performanceId=%s (no tickets)", performance_id)
        return ResaleStatus(
            performance_id=performance_id,
            state="sold_out",
            item_count=0,
            price_text="",
            link=endpoints.RESALE_ITEM_PAGE_URL.format(performance_id=performance_id),
        )

    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ParseError(
            f"resale response for performanceId={performance_id} is not JSON: {exc}"
        ) from exc
    return parse_items(payload, performance_id)
