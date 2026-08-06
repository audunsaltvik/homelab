"""Configuration, read from the environment the Helm chart injects.

Every setting is required and read without a fallback value. A missing key
should crash the pod on startup rather than silently run with a guess that
differs from what values.yaml says.
"""

import json
import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo


class ConfigError(RuntimeError):
    pass


def _req(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise ConfigError(f"required environment variable {name} is unset or empty")
    return value


def _req_int(name: str) -> int:
    raw = _req(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _req_bool(name: str) -> bool:
    raw = _req(name).strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    raise ConfigError(f"{name} must be a boolean, got {raw!r}")


def _opt(name: str) -> str:
    """For values that are genuinely optional (Uptime Kuma is opt-in)."""
    return os.environ.get(name, "")


@dataclass(frozen=True)
class WatchEntry:
    """One entry from values.yaml `watch:`."""

    product_id: int
    label: str
    # Glob patterns against the performance name, e.g. "Norge vs *" to keep
    # home matches only. Empty include list means "every match under product".
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    # Which sources to poll for this product.
    sources: list[str] = field(default_factory=lambda: ["primary", "resale"])
    # Optional pin: only watch these specific performance ids.
    performance_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_chat_id: str
    uptime_kuma_push_url: str

    state_dir: str
    timezone: ZoneInfo

    user_agent: str
    request_timeout_seconds: int
    # Minimum gap between two requests to the same host. Serialised by
    # construction - the monitor never fires concurrent requests at a domain.
    min_request_interval_seconds: float
    max_retries: int
    backoff_base_seconds: float
    backoff_max_seconds: float

    announce_enabled: bool
    announce_home_only: bool

    watch: list[WatchEntry]

    # Availability pacing. The CronJob schedule is fixed, so the process
    # self-gates to get an adaptive rate out of it.
    normal_interval_seconds: int
    # Resale gets its own, faster cadence: listings appear at unpredictable
    # times and get bought within minutes, unlike scheduled primary onsales.
    resale_interval_seconds: int
    hot_interval_seconds: int
    hot_window_before_seconds: int
    hot_window_after_seconds: int
    max_run_seconds: int

    notify_cooldown_seconds: int
    parse_failure_alert_cooldown_seconds: int

    @property
    def announcements_state_path(self) -> str:
        return os.path.join(self.state_dir, "announcements.json")

    @property
    def sale_schedule_path(self) -> str:
        return os.path.join(self.state_dir, "sale_schedule.json")

    @property
    def availability_state_path(self) -> str:
        return os.path.join(self.state_dir, "availability.json")


def _parse_watch(raw: str) -> list[WatchEntry]:
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"WATCH_JSON is not valid JSON: {exc}") from exc
    if not isinstance(items, list):
        raise ConfigError("WATCH_JSON must be a list")

    entries = []
    for item in items:
        if "productId" not in item:
            raise ConfigError(f"watch entry missing productId: {item!r}")
        if "label" not in item:
            raise ConfigError(f"watch entry missing label: {item!r}")
        entries.append(
            WatchEntry(
                product_id=int(item["productId"]),
                label=str(item["label"]),
                include=[str(p) for p in item.get("include", [])],
                exclude=[str(p) for p in item.get("exclude", [])],
                sources=[str(s) for s in item.get("sources", ["primary", "resale"])],
                performance_ids=[int(p) for p in item.get("performanceIds", [])],
            )
        )
    return entries


def load() -> Config:
    return Config(
        telegram_bot_token=_req("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_req("TELEGRAM_CHAT_ID"),
        uptime_kuma_push_url=_opt("UPTIME_KUMA_PUSH_URL"),
        state_dir=_req("STATE_DIR"),
        timezone=ZoneInfo(_req("TZ")),
        user_agent=_req("USER_AGENT"),
        request_timeout_seconds=_req_int("REQUEST_TIMEOUT_SECONDS"),
        min_request_interval_seconds=float(_req("MIN_REQUEST_INTERVAL_SECONDS")),
        max_retries=_req_int("MAX_RETRIES"),
        backoff_base_seconds=float(_req("BACKOFF_BASE_SECONDS")),
        backoff_max_seconds=float(_req("BACKOFF_MAX_SECONDS")),
        announce_enabled=_req_bool("ANNOUNCE_ENABLED"),
        announce_home_only=_req_bool("ANNOUNCE_HOME_ONLY"),
        watch=_parse_watch(_req("WATCH_JSON")),
        normal_interval_seconds=_req_int("NORMAL_INTERVAL_SECONDS"),
        resale_interval_seconds=_req_int("RESALE_INTERVAL_SECONDS"),
        hot_interval_seconds=_req_int("HOT_INTERVAL_SECONDS"),
        hot_window_before_seconds=_req_int("HOT_WINDOW_BEFORE_SECONDS"),
        hot_window_after_seconds=_req_int("HOT_WINDOW_AFTER_SECONDS"),
        max_run_seconds=_req_int("MAX_RUN_SECONDS"),
        notify_cooldown_seconds=_req_int("NOTIFY_COOLDOWN_SECONDS"),
        parse_failure_alert_cooldown_seconds=_req_int(
            "PARSE_FAILURE_ALERT_COOLDOWN_SECONDS"
        ),
    )
