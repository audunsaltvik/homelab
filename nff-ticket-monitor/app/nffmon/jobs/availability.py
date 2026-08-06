"""Watcher B - availability guard.

Notifies only on a state *transition* into "tickets exist", never on every
run, and folds bursts together so a resale seller listing tickets one at a
time produces one message instead of forty.
"""

import fnmatch
import logging
import time
from datetime import datetime, timedelta

from .. import schedule, state
from ..config import Config, WatchEntry
from ..httpclient import FetchError, HttpClient
from ..notify import Notifier, should_alert
from ..sources import primary, resale

logger = logging.getLogger(__name__)

EMPTY_STATE = {
    "schema": state.SCHEMA_VERSION,
    "last_poll_at": None,
    "performances": {},
    "parse_health": {},
}

EMPTY_SOURCE = {
    "state": "unknown",
    "since": None,
    "last_seen": None,
    "last_notified_at": None,
    "item_count": 0,
    "pending": None,
}


def _matches_filter(name: str, entry: WatchEntry) -> bool:
    if entry.include and not any(fnmatch.fnmatch(name, p) for p in entry.include):
        return False
    if entry.exclude and any(fnmatch.fnmatch(name, p) for p in entry.exclude):
        return False
    return True


def _cooldown_elapsed(last_iso: str | None, cooldown: int, now: datetime) -> bool:
    if not last_iso:
        return True
    try:
        last = datetime.fromisoformat(last_iso)
    except ValueError:
        return True
    return now - last >= timedelta(seconds=cooldown)


def _merge(payload: dict, parked: dict) -> dict:
    """Fold a parked notification into a newer one.

    Keeps the highest count seen during the cooldown rather than whichever
    poll happened to be last - if a seller listed seven tickets and five were
    bought before the cooldown expired, "7 tickets appeared" is the useful
    message. The display string is regenerated from the merged count so it can
    never disagree with the number it was derived from.
    """
    merged = dict(payload)
    merged["quantity_n"] = max(payload.get("quantity_n", 0), parked.get("quantity_n", 0))
    if merged["quantity_n"] > 0:
        merged["quantity"] = f"{merged['quantity_n']} billett(er)"
    return merged


class Gate:
    """Per match+source notification gate.

    A notification-worthy event inside the cooldown is not dropped, it is
    parked in `pending` and merged into the next send. That is what turns a
    drip of single resale listings into one summary message.
    """

    def __init__(self, notifier: Notifier, cooldown_seconds: int):
        self.notifier = notifier
        self.cooldown = cooldown_seconds

    def offer(self, source_state: dict, payload: dict, now: datetime) -> bool:
        if not _cooldown_elapsed(source_state.get("last_notified_at"), self.cooldown, now):
            source_state["pending"] = _merge(payload, source_state.get("pending") or {})
            logger.info("notification parked in cooldown: %s", payload.get("label"))
            return False

        parked = source_state.get("pending") or {}
        payload = _merge(payload, parked)
        ok = self.notifier.send_availability(
            label=payload["label"],
            opponent=payload["opponent"],
            kickoff_text=payload["kickoff_text"],
            venue=payload["venue"],
            source=payload["source"],
            quantity=payload["quantity"],
            price=payload["price"],
            link=payload["link"],
        )
        if ok:
            source_state["last_notified_at"] = now.isoformat()
            source_state["pending"] = None
        else:
            # Send failed - keep it parked so the next poll retries.
            source_state["pending"] = payload
        return ok

    def flush(self, source_state: dict, now: datetime) -> bool:
        """Send a parked notification once its cooldown has expired."""
        payload = source_state.get("pending")
        if not payload:
            return False
        if not _cooldown_elapsed(source_state.get("last_notified_at"), self.cooldown, now):
            return False
        return self.offer(source_state, payload, now)


def _record_failure(
    stored: dict, notifier: Notifier, cfg: Config, source: str, detail: str, now: datetime
) -> None:
    health = stored.setdefault("parse_health", {}).setdefault(
        source, {"consecutive_failures": 0, "last_alert_at": None}
    )
    health["consecutive_failures"] += 1
    logger.error("%s failed: %s", source, detail)
    if should_alert(health.get("last_alert_at"), cfg.parse_failure_alert_cooldown_seconds, now):
        notifier.send_parse_failure(source, detail, health["consecutive_failures"])
        health["last_alert_at"] = now.isoformat()


def _clear_failure(stored: dict, source: str) -> None:
    health = stored.setdefault("parse_health", {}).setdefault(
        source, {"consecutive_failures": 0, "last_alert_at": None}
    )
    health["consecutive_failures"] = 0


def _resale_payload(node: dict, status, label: str) -> dict:
    return {
        "label": f"{node.get('product_label', '')} — {node.get('label', '')}".strip(" —"),
        "opponent": label,
        "kickoff_text": node.get("kickoff_text", ""),
        "venue": node.get("venue", ""),
        "source": "resale",
        "quantity": f"{status.item_count} billett(er)",
        "quantity_n": status.item_count,
        "price": status.price_text,
        "link": status.link,
    }


def _poll_primary(
    cfg: Config, client: HttpClient, notifier: Notifier, stored: dict, gate: Gate
) -> tuple[int, int]:
    """Refresh the match list from billett.fotball.no and diff primary sale state.

    This is also the only thing that discovers new performanceIds, so a resale-
    only cycle depends on a primary cycle having run at least once.
    """
    now = datetime.now(cfg.timezone)
    performances_state = stored.setdefault("performances", {})
    checked = 0
    notified = 0

    for entry in cfg.watch:
        try:
            performances = primary.fetch_performances(client, entry.product_id, cfg.timezone)
            _clear_failure(stored, "primary")
        except (FetchError, primary.ParseError) as exc:
            _record_failure(
                stored, notifier, cfg, "primary", f"productId={entry.product_id}: {exc}", now
            )
            continue

        for perf in performances:
            if entry.performance_ids and int(perf.performance_id) not in entry.performance_ids:
                continue
            if not _matches_filter(perf.name, entry):
                continue

            checked += 1
            node = performances_state.setdefault(perf.performance_id, {"sources": {}})
            node.update(
                {
                    "label": perf.name,
                    "product_id": perf.product_id,
                    "product_label": entry.label,
                    "kickoff": perf.kickoff.isoformat() if perf.kickoff else None,
                    "kickoff_text": perf.kickoff_text,
                    "venue": perf.venue,
                    "opponent": perf.opponent,
                    "watch_resale": "resale" in entry.sources,
                }
            )
            sources = node.setdefault("sources", {})

            if "primary" not in entry.sources:
                continue

            src = sources.setdefault("primary", dict(EMPTY_SOURCE))
            previous = src.get("state", "unknown")
            src["last_seen"] = now.isoformat()
            if perf.state != previous:
                src["state"] = perf.state
                src["since"] = now.isoformat()
                logger.info("primary %s: %s -> %s", perf.name, previous, perf.state)

            # "unknown" is not availability; only a real transition into
            # available is worth waking someone up for.
            if perf.state == "available" and previous != "available":
                if gate.offer(
                    src,
                    {
                        "label": f"{entry.label} — {perf.name}",
                        "opponent": perf.opponent,
                        "kickoff_text": perf.kickoff_text,
                        "venue": perf.venue,
                        "source": "primary",
                        "quantity": "",
                        "quantity_n": 0,
                        "price": perf.min_price_text,
                        "link": perf.link,
                    },
                    now,
                ):
                    notified += 1
            elif gate.flush(src, now):
                notified += 1

    stored["last_primary_poll_at"] = now.isoformat()
    return checked, notified


def _poll_resale(
    cfg: Config, client: HttpClient, notifier: Notifier, stored: dict, gate: Gate
) -> tuple[int, int]:
    """Check resale for every known match, without touching billett.fotball.no.

    Resale listings are put up by other supporters at unpredictable times and
    get bought within minutes, so this runs on its own faster cadence. It reads
    performanceIds straight from state, which is what makes the extra frequency
    cost one request per match instead of a full catalogue walk.
    """
    now = datetime.now(cfg.timezone)
    performances_state = stored.setdefault("performances", {})
    watched_products = {e.product_id for e in cfg.watch}
    checked = 0
    notified = 0

    for performance_id, node in performances_state.items():
        if not node.get("watch_resale", True):
            continue
        # Drop matches whose product was removed from values.yaml without
        # requiring the state file to be edited by hand.
        if node.get("product_id") not in watched_products:
            continue
        # A match that has already kicked off cannot be resold.
        kickoff = node.get("kickoff")
        if kickoff:
            try:
                if datetime.fromisoformat(kickoff) < now:
                    continue
            except ValueError:
                pass

        src = node.setdefault("sources", {}).setdefault("resale", dict(EMPTY_SOURCE))
        try:
            status = resale.fetch_status(client, performance_id)
            _clear_failure(stored, "resale")
        except (FetchError, resale.ParseError) as exc:
            _record_failure(
                stored, notifier, cfg, "resale", f"performanceId={performance_id}: {exc}", now
            )
            continue

        checked += 1
        previous = src.get("state", "unknown")
        previous_count = src.get("item_count", 0)
        src["last_seen"] = now.isoformat()
        if status.state != previous:
            src["state"] = status.state
            src["since"] = now.isoformat()
            logger.info(
                "resale %s: %s -> %s", node.get("label", performance_id), previous, status.state
            )
        src["item_count"] = status.item_count

        # Notify when resale goes from nothing to something, and also when the
        # pile grows - more tickets can mean better seats.
        grew = status.state == "available" and status.item_count > previous_count
        if status.state == "available" and (previous != "available" or grew):
            if gate.offer(src, _resale_payload(node, status, node.get("opponent", "")), now):
                notified += 1
        elif gate.flush(src, now):
            notified += 1

    stored["last_resale_poll_at"] = now.isoformat()
    return checked, notified


def run(cfg: Config, client: HttpClient, notifier: Notifier) -> int:
    stored = state.read_json(cfg.availability_state_path, EMPTY_STATE)
    schedule_state = state.read_json(
        cfg.sale_schedule_path, {"schema": state.SCHEMA_VERSION, "matches": []}
    )
    windows = schedule.load_windows(
        schedule_state,
        cfg.hot_window_before_seconds,
        cfg.hot_window_after_seconds,
        cfg.timezone,
    )
    gate = Gate(notifier, cfg.notify_cooldown_seconds)

    started = time.monotonic()
    polls = 0
    total_checked = 0
    total_notified = 0

    while True:
        now = datetime.now(cfg.timezone)
        window = schedule.active_window(windows, now)

        if window is not None:
            # Inside a sale window both sources run on every tick - that is the
            # moment the fast cadence exists for.
            do_primary = do_resale = True
            if polls == 0:
                logger.info(
                    "HOT: %s / %s starts %s (window %s - %s)",
                    window.match_label,
                    window.phase_name,
                    window.starts_at.isoformat(),
                    window.window_start.isoformat(),
                    window.window_end.isoformat(),
                )
        elif polls > 0:
            logger.info("sale window closed; exiting after %d polls", polls)
            break
        else:
            do_primary = schedule.should_poll_now(
                stored.get("last_primary_poll_at"), cfg.normal_interval_seconds, now
            )
            do_resale = schedule.should_poll_now(
                stored.get("last_resale_poll_at"), cfg.resale_interval_seconds, now
            )
            # Resale reads performanceIds out of state, so it needs a primary
            # sweep to have populated them at least once.
            if do_resale and not stored.get("performances"):
                do_primary = True

            if not (do_primary or do_resale):
                logger.info(
                    "no sale window active; primary polled under %ds ago and "
                    "resale under %ds ago; exiting",
                    cfg.normal_interval_seconds,
                    cfg.resale_interval_seconds,
                )
                return 0

        logger.info("polling primary=%s resale=%s", do_primary, do_resale)
        checked = notified = 0
        if do_primary:
            c, n = _poll_primary(cfg, client, notifier, stored, gate)
            checked += c
            notified += n
        if do_resale:
            c, n = _poll_resale(cfg, client, notifier, stored, gate)
            checked += c
            notified += n
        stored["last_poll_at"] = now.isoformat()
        total_checked += checked
        total_notified += notified
        polls += 1
        # Persisted every iteration so a pod killed mid-window does not replay
        # notifications it already sent.
        state.write_json(cfg.availability_state_path, stored)

        if window is None:
            break

        elapsed = time.monotonic() - started
        if elapsed + cfg.hot_interval_seconds >= cfg.max_run_seconds:
            logger.info("run budget reached; next CronJob run continues the window")
            break
        time.sleep(cfg.hot_interval_seconds)

    logger.info(
        "availability: %d polls, %d match-checks, %d notifications",
        polls,
        total_checked,
        total_notified,
    )
    failures = sum(
        h.get("consecutive_failures", 0) for h in stored.get("parse_health", {}).values()
    )
    if failures:
        notifier.ping_uptime_kuma("down", f"{failures} source failures")
        return 1
    notifier.ping_uptime_kuma(
        "up", f"OK - {total_checked} checks, {total_notified} notifications"
    )
    return 0
