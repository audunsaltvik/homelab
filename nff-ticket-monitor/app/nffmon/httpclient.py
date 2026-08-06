"""HTTP access with deliberate restraint.

Three rules this module exists to enforce:

1. One request at a time per host, with a floor on the gap between them. There
   is no threading anywhere in this app - serialisation is structural, not a
   setting someone can turn off by accident.
2. Failures back off exponentially and give up. A ticket monitor that retries
   hard against a site during an onsale is exactly the traffic pattern that
   gets an IP blocked, which also defeats the point of the monitor.
3. robots.txt is fetched and consulted for every host, and a disallowed fetch
   is logged loudly every single time rather than once at startup.
"""

import logging
import random
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """Raised when a URL could not be retrieved after all retries."""


class HttpClient:
    def __init__(
        self,
        user_agent: str,
        timeout_seconds: int,
        min_interval_seconds: float,
        max_retries: int,
        backoff_base_seconds: float,
        backoff_max_seconds: float,
    ):
        self.user_agent = user_agent
        self.timeout = timeout_seconds
        self.min_interval = min_interval_seconds
        self.max_retries = max_retries
        self.backoff_base = backoff_base_seconds
        self.backoff_max = backoff_max_seconds

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.7",
            }
        )

        self._last_request_at: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # --- robots.txt ----------------------------------------------------------

    def _robots_for(self, host_root: str):
        """Fetch and cache robots.txt for a scheme://host root.

        A robots.txt we cannot read is treated as "no opinion" rather than
        "disallow" - failing closed here would silently disable the whole
        monitor on a transient 500.
        """
        if host_root in self._robots:
            return self._robots[host_root]

        parser = urllib.robotparser.RobotFileParser()
        url = f"{host_root}/robots.txt"
        try:
            response = self.session.get(url, timeout=self.timeout)
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
            else:
                logger.warning(
                    "robots.txt at %s returned HTTP %s; proceeding without it",
                    url,
                    response.status_code,
                )
                parser = None
        except requests.RequestException as exc:
            logger.warning("could not fetch robots.txt at %s: %s", url, exc)
            parser = None

        self._robots[host_root] = parser
        return parser

    def is_allowed(self, url: str) -> bool:
        parts = urlparse(url)
        host_root = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots_for(host_root)
        if parser is None:
            return True
        # Checked against "*" rather than our own UA: we are not on any
        # allowlist, so the wildcard group is the rule that applies to us.
        return parser.can_fetch("*", url)

    # --- fetching ------------------------------------------------------------

    def _throttle(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
        self._last_request_at[host] = time.monotonic()

    def get(self, url: str, accept: str = "text/html") -> requests.Response:
        """GET a URL, honouring throttle and backoff.

        Returns the response even for 404, because SecuTix uses 404 as a
        meaningful "no resale tickets for this match" answer rather than an
        error. Only transport failures and 5xx are retried.
        """
        host = urlparse(url).netloc

        if not self.is_allowed(url):
            # Logged on every request, not once: this is a standing condition
            # the operator chose to accept, and it should stay visible in logs.
            logger.warning(
                "ROBOTS-DISALLOWED %s - robots.txt for this host disallows "
                "our user-agent; fetching anyway per configuration",
                url,
            )

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle(host)
            try:
                response = self.session.get(
                    url, timeout=self.timeout, headers={"Accept": accept}
                )
            except requests.RequestException as exc:
                last_error = exc
            else:
                if response.status_code < 500:
                    return response
                last_error = FetchError(f"HTTP {response.status_code} from {url}")

            if attempt < self.max_retries:
                # Jitter so that a restart loop across both CronJobs does not
                # produce synchronised retry bursts.
                delay = min(
                    self.backoff_base * (2**attempt), self.backoff_max
                ) * random.uniform(0.8, 1.2)
                logger.warning(
                    "fetch of %s failed (%s); retry %d/%d in %.1fs",
                    url,
                    last_error,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                time.sleep(delay)

        raise FetchError(f"giving up on {url} after {self.max_retries} retries: {last_error}")

    def get_json(self, url: str):
        response = self.get(url, accept="application/json")
        response.raise_for_status()
        return response.json()
