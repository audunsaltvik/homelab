"""Watcher A - announcement guard.

Polls the NFF announcement page hourly, diffs it against the previous run, and
notifies on: a fixture appearing, a sale phase being published, or a published
sale time moving. It also writes sale_schedule.json, which is the only thing
the availability watcher reads from this job.
"""

import logging
from datetime import datetime

from .. import endpoints, state
from ..config import Config
from ..httpclient import FetchError, HttpClient
from ..notify import Notifier, format_datetime_no, should_alert
from ..sources import announcements

logger = logging.getLogger(__name__)

EMPTY_STATE = {"schema": state.SCHEMA_VERSION, "last_run": None, "matches": {}, "health": {}}

STATUS_LABELS = {
    "sold_out": "🔴 Utsolgt",
    "info_pending": "⏳ Billettinformasjon kommer",
    "announced": "🟢 Salgsdatoer publisert",
}


def _phase_map(phases: list[dict]) -> dict[str, dict]:
    return {p["name"]: p for p in phases}


def _phase_label(name: str) -> str:
    return endpoints.ANN_PHASE_LABELS.get(name, name)


def _when(iso: str) -> str:
    """Render a stored ISO timestamp the way a person reads it."""
    try:
        return format_datetime_no(datetime.fromisoformat(iso))
    except (TypeError, ValueError):
        # Never let a formatting problem swallow the notification itself.
        return iso


def _diff_and_notify(
    notifier: Notifier, previous: dict, current: list, now: datetime
) -> int:
    """Emit one Telegram message per meaningful change. Returns messages sent."""
    sent = 0
    for match in current:
        before = previous.get(match.key)
        phases = [p.to_dict() for p in match.phases]

        if before is None:
            body = [f"⚽ {match.title}"]
            if match.status == "sold_out":
                body.append("🔴 Utsolgt")
            elif match.status == "info_pending":
                body.append("⏳ Billettinformasjon kommer")
            for phase in phases:
                body.append(f"🕐 {_when(phase['starts_at'])} — {phase['description']}")
            notifier.send_announcement("Ny kamp lagt ut", body, endpoints.ANNOUNCEMENTS_URL)
            sent += 1
            continue

        old_phases = _phase_map(before.get("phases", []))
        new_phases = _phase_map(phases)

        added = [name for name in new_phases if name not in old_phases]
        moved = [
            name
            for name in new_phases
            if name in old_phases
            and new_phases[name]["starts_at"] != old_phases[name]["starts_at"]
        ]

        if added:
            body = [f"⚽ {match.title}"] + [
                f"🕐 {_when(new_phases[n]['starts_at'])} — {new_phases[n]['description']}"
                for n in added
            ]
            notifier.send_announcement(
                "Ny salgsdato publisert", body, endpoints.ANNOUNCEMENTS_URL
            )
            sent += 1

        if moved:
            body = [f"⚽ {match.title}"] + [
                f"🕐 {_phase_label(n)}\n"
                f"     {_when(old_phases[n]['starts_at'])}\n"
                f"  →  {_when(new_phases[n]['starts_at'])}"
                for n in moved
            ]
            notifier.send_announcement(
                "Salgsdato endret", body, endpoints.ANNOUNCEMENTS_URL
            )
            sent += 1

        if before.get("status") != match.status:
            notifier.send_announcement(
                "Status endret",
                [
                    f"⚽ {match.title}",
                    f"{STATUS_LABELS.get(before.get('status'), before.get('status'))}"
                    f" → {STATUS_LABELS.get(match.status, match.status)}",
                ],
                endpoints.ANNOUNCEMENTS_URL,
            )
            sent += 1

    return sent


def run(cfg: Config, client: HttpClient, notifier: Notifier) -> int:
    if not cfg.announce_enabled:
        logger.info("announcement watcher disabled by ANNOUNCE_ENABLED=false")
        return 0

    now = datetime.now(cfg.timezone)
    stored = state.read_json(cfg.announcements_state_path, EMPTY_STATE)
    health = stored.setdefault("health", {})

    try:
        matches = announcements.fetch(client, cfg.timezone)
    except (FetchError, announcements.ParseError) as exc:
        health["consecutive_failures"] = health.get("consecutive_failures", 0) + 1
        logger.error("announcement fetch/parse failed: %s", exc)
        if should_alert(
            health.get("last_alert_at"), cfg.parse_failure_alert_cooldown_seconds, now
        ):
            notifier.send_parse_failure(
                "www.fotball.no (kunngjøringer)", str(exc), health["consecutive_failures"]
            )
            health["last_alert_at"] = now.isoformat()
        state.write_json(cfg.announcements_state_path, stored)
        notifier.ping_uptime_kuma("down", f"announce parse failed: {exc}")
        return 1

    health["consecutive_failures"] = 0

    if cfg.announce_home_only:
        # Away fixtures are sold by the opposing federation, so their sale
        # dates cannot drive our hot window either - drop them before both the
        # diff and the schedule so the two stay consistent.
        kept = [m for m in matches if m.is_home_match]
        logger.info(
            "home-only filter: keeping %d of %d fixtures", len(kept), len(matches)
        )
        matches = kept

    sent = _diff_and_notify(notifier, stored.get("matches", {}), matches, now)

    stored["matches"] = {m.key: m.to_dict() for m in matches}
    stored["last_run"] = now.isoformat()
    state.write_json(cfg.announcements_state_path, stored)

    # The contract with the availability watcher. Rewritten in full each run so
    # a phase removed upstream also disappears from the hot-window schedule.
    state.write_json(
        cfg.sale_schedule_path,
        {
            "schema": state.SCHEMA_VERSION,
            "updated_at": now.isoformat(),
            "source": endpoints.ANNOUNCEMENTS_URL,
            "matches": [
                {
                    "key": m.key,
                    "label": m.label,
                    "kickoff_date": m.kickoff_date.isoformat() if m.kickoff_date else None,
                    "phases": [p.to_dict() for p in m.phases],
                }
                for m in matches
            ],
        },
    )

    logger.info("announce: %d fixtures tracked, %d notifications sent", len(matches), sent)
    notifier.ping_uptime_kuma("up", f"OK - {len(matches)} fixtures, {sent} notifications")
    return 0
