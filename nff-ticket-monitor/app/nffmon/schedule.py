"""Adaptive polling rate on top of a fixed CronJob schedule.

A CronJob cannot change its own schedule, so the adaptivity lives here. The
CronJob fires every 5 minutes and this module decides what that run does:

  outside a sale window -> poll only if NORMAL_INTERVAL_SECONDS has elapsed,
                           otherwise exit immediately (a sub-second no-op pod)
  inside a sale window  -> loop internally at HOT_INTERVAL_SECONDS until the
                           window closes or MAX_RUN_SECONDS is reached, so the
                           next cron run picks up seamlessly

Why HOT_WINDOW_BEFORE_SECONDS must exceed the cron period: with a 5-minute
schedule and a 5-minute pre-window, the first run that sees the window could
land exactly at sale time. Ten minutes guarantees at least one run enters the
window with time to spare.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class HotWindow:
    match_label: str
    phase_name: str
    starts_at: datetime
    window_start: datetime
    window_end: datetime


def load_windows(
    schedule_state: dict,
    before_seconds: int,
    after_seconds: int,
    tz,
) -> list[HotWindow]:
    windows: list[HotWindow] = []
    for match in schedule_state.get("matches", []):
        label = match.get("label", "?")
        for phase in match.get("phases", []):
            raw = phase.get("starts_at")
            if not raw:
                continue
            try:
                starts_at = datetime.fromisoformat(raw)
            except ValueError:
                logger.warning("unparseable phase start %r for %s", raw, label)
                continue
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=tz)
            windows.append(
                HotWindow(
                    match_label=label,
                    phase_name=phase.get("name", "?"),
                    starts_at=starts_at,
                    window_start=starts_at - timedelta(seconds=before_seconds),
                    window_end=starts_at + timedelta(seconds=after_seconds),
                )
            )
    return windows


def active_window(windows: list[HotWindow], now: datetime) -> HotWindow | None:
    for window in windows:
        if window.window_start <= now <= window.window_end:
            return window
    return None


def should_poll_now(last_poll_iso: str | None, normal_interval: int, now: datetime) -> bool:
    if not last_poll_iso:
        return True
    try:
        last = datetime.fromisoformat(last_poll_iso)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=now.tzinfo)
    return now - last >= timedelta(seconds=normal_interval)
