"""Every URL, CSS selector and text marker the monitor depends on.

Single source of truth on purpose: these are the parts that break when NFF
redesigns something. Keeping them in one file means a markup change is a diff
in one place instead of a hunt through the scrapers.

Verified against live responses 2026-08-06.
"""

# --- Hosts -------------------------------------------------------------------

HOST_ANNOUNCEMENTS = "https://www.fotball.no"
HOST_PRIMARY = "https://billett.fotball.no"
HOST_RESALE = "https://resale.fotball.no"


# --- Source 1: announcement page (www.fotball.no) ----------------------------

ANNOUNCEMENTS_URL = (
    f"{HOST_ANNOUNCEMENTS}/tema/billetter/billettinformasjon-herrelandslaget/"
)

# The page wraps the fixture list in a section whose heading carries the year
# ("Kommende landskamper 2026"). We need that year because the individual match
# titles only say "14. november" with no year of their own.
ANN_SECTION_SELECTOR = "section.a_digitalMatchInfoBlock"
ANN_SECTION_HEADING_SELECTOR = "div.heading"
ANN_MATCH_SELECTOR = "div.a_expandableField"
ANN_MATCH_TITLE_SELECTOR = "div.title"
ANN_MATCH_BODY_SELECTOR = "div.expandableField"

# Status wording inside a match body. Matched case-insensitively on the
# whitespace-normalised text, so "UTSOLGT" and "Utsolgt " both hit.
ANN_MARKER_SOLD_OUT = "utsolgt"
ANN_MARKER_INFO_PENDING = "billettinformasjon kommer"

# Sale phases are rendered as "<strong>Onsdag 19. august kl 12:00:</strong>
# <span>Forhåndssalg for gullmedlemmer ... pulje 1</span>". Note that NFF is
# inconsistent about the time separator - one line on the live page uses
# "kl 12.00" with a dot - so both are accepted.
ANN_PHASE_STRONG_SELECTOR = "strong"

# Substrings that classify a sale phase into a stable machine name. Order
# matters: the first entry whose substrings all appear wins.
ANN_PHASE_PATTERNS = [
    ("gull_pulje_1", ("gullmedlem", "pulje 1")),
    ("gull_pulje_2", ("gullmedlem", "pulje 2")),
    ("gull", ("gullmedlem",)),
    ("solv", ("sølvmedlem",)),
    ("apent_salg", ("åpent salg",)),
]
ANN_PHASE_FALLBACK = "annet"

# Human names for the machine phase keys, used where a message would otherwise
# show a bare identifier like "gull_pulje_1".
ANN_PHASE_LABELS = {
    "gull_pulje_1": "Gullmedlem pulje 1",
    "gull_pulje_2": "Gullmedlem pulje 2",
    "gull": "Gullmedlem",
    "solv": "Sølvmedlem",
    "apent_salg": "Åpent salg",
    "annet": "Salgsstart",
}

# The men's national team plays at Ullevaal as "NORGE - X"; an away fixture
# reads "X - NORGE". Home side is whatever precedes this separator.
ANN_TEAM_SEPARATOR = " - "
ANN_HOME_TEAM = "norge"


# --- Source 2: primary sale (billett.fotball.no) -----------------------------

# Product catalogue. A "product" is a category (e.g. "Nations League -
# A-herrer"), not a single match - individual matches live underneath it as
# performances. Used to discover product ids without hardcoding them.
PRIMARY_CATALOG_URL = f"{HOST_PRIMARY}/list/resale/resaleProductCatalog.json?lang=no"

# Performances (= individual matches) for one product. Returns an HTML
# fragment, not JSON. One request covers every match under the product, which
# is why polling stays cheap even at 60s during an onsale.
PRIMARY_PERFORMANCES_URL = (
    f"{HOST_PRIMARY}/ajax/event/date/performances?productId={{product_id}}&lang=no"
)

# Human-facing page for a match, used for the deep link in Telegram messages.
PRIMARY_EVENT_PAGE_URL = f"{HOST_PRIMARY}/selection/event/date?productId={{product_id}}"

PRIMARY_PERFORMANCE_SELECTOR = "li.performance"

# A product between seasons legitimately has zero matches, and that must not be
# mistaken for a broken parser. The endpoint always emits this marker element,
# so: marker present + no performances = genuinely empty; marker absent = the
# response is not the fragment we expect any more.
PRIMARY_FRAGMENT_MARKER_SELECTOR = "#newPerformanceDate"
PRIMARY_EMPTY_MARKER_TEXT = "no visits available"
# The performance element's id attribute *is* the performanceId - the stable
# per-match key, and the same id resale.fotball.no is queried with.
PRIMARY_PERFORMANCE_ID_ATTR = "id"

# Availability is carried by class names on the performance element.
PRIMARY_CLASS_AVAILABLE = "available"
PRIMARY_CLASS_SOLD_OUT = "sold_out"
# NFF tags sold-out matches it considers worth checking on the resale platform.
PRIMARY_CLASS_HAS_RESALE = "check_resale_availability"

# Full date including year lives in the screen-reader-only span:
# "Date and time: torsdag, 24 september 2026 - 20:45". The visible markup is
# abbreviated ("to 24 sep 20:45") and carries no year, so parse the a11y text.
PRIMARY_DATETIME_SELECTOR = ".date_time .accessibility-visually-hidden"
PRIMARY_DATETIME_RE = (
    r"(?P<day>\d{1,2})\s+(?P<month>[a-zæøå]+)\s+(?P<year>\d{4})"
    r"\s*-\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})"
)

PRIMARY_VENUE_SELECTOR = ".venue_group_match .site"
PRIMARY_TEAM_HOME_SELECTOR = ".teams .team.home .name"
PRIMARY_TEAM_AWAY_SELECTOR = ".teams .team.opposite .name"
# Both team spans carry the clean name in title=, without the surrounding logo
# markup that get_text() would pick up.
PRIMARY_TEAM_NAME_ATTR = "title"

PRIMARY_RESALE_LINK_SELECTOR = "a[href*='resale.fotball.no']"
PRIMARY_SELECT_BUTTON_SELECTOR = ".performance-select-btn"

# Cheapest ticket. The span renders "240.00 NOK" as text and carries
# data-amount="240000" - thousandths of NOK, not hundredths. Dividing by 100
# would report a 10x overprice, so the rendered text is used for display and
# the attribute only for numeric comparisons.
PRIMARY_MIN_PRICE_SELECTOR = "[data-amount]"
PRIMARY_MIN_PRICE_ATTR = "data-amount"
PRIMARY_MIN_PRICE_DIVISOR = 1000

# Available performances put the seat-selection URL in an onclick handler;
# that is the most direct deep link we can hand the user.
PRIMARY_ONCLICK_URL_RE = r"document\.location\.href\s*=\s*'([^']+)'"


# --- Source 3: resale (resale.fotball.no) ------------------------------------

# Per-match resale listings. Anonymous - login is only needed to buy, not to
# see what is on offer. Confirmed 2026-08-06: returns 200 with an empty
# resaleItems array when nobody is reselling.
RESALE_ITEMS_URL = (
    f"{HOST_RESALE}/selection/resale/resaleItems.json"
    "?performanceId={performance_id}&lang=no"
)
RESALE_ITEMS_KEY = "resaleItems"

# Human-facing resale page for a match, for the Telegram deep link.
RESALE_ITEM_PAGE_URL = (
    f"{HOST_RESALE}/selection/resale/item"
    "?performanceId={performance_id}&checkResaleAvailability=true"
)
