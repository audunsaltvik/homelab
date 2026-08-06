"""Telegram notifications, parse-failure alarms and the Uptime Kuma heartbeat.

Design bias: a silent failure is worse than a noisy one. If a parser stops
finding matches, that is a notification too - otherwise the monitor looks
healthy right up until the moment tickets go on sale and nothing arrives.
"""

import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Python's locale-aware date formatting would need a Norwegian locale present
# in the image; hardcoding the twelve month names is smaller and cannot break
# on a slim base image that ships no locales.
NO_WEEKDAYS = [
    "mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag",
]
NO_MONTHS = [
    None, "januar", "februar", "mars", "april", "mai", "juni",
    "juli", "august", "september", "oktober", "november", "desember",
]


def format_datetime_no(value: datetime) -> str:
    """"onsdag 19. august kl. 12:00" - an ISO string is unreadable on a phone."""
    return (
        f"{NO_WEEKDAYS[value.weekday()]} {value.day}. "
        f"{NO_MONTHS[value.month]} kl. {value:%H:%M}"
    )


def _escape(text: str) -> str:
    """Escape the characters that break Telegram's legacy Markdown parser.

    Team names and category labels come from NFF, so they can contain anything.
    An unbalanced underscore silently drops the whole message.
    """
    for char in ("_", "*", "[", "]", "`"):
        text = text.replace(char, "\\" + char)
    return text


class Notifier:
    def __init__(self, bot_token: str, chat_id: str, uptime_kuma_push_url: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.uptime_kuma_push_url = uptime_kuma_push_url

    def send(self, message: str) -> bool:
        url = TELEGRAM_API.format(token=self.bot_token)
        try:
            response = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("telegram send failed: %s", exc)
            return False
        logger.info("telegram notification sent")
        return True

    # --- ticket availability -------------------------------------------------

    def send_availability(
        self,
        *,
        label: str,
        opponent: str,
        kickoff_text: str,
        venue: str,
        source: str,
        quantity: str,
        price: str,
        link: str,
    ) -> bool:
        source_line = {
            "primary": "🟢 Nysalg (billett.fotball.no)",
            "resale": "🔁 Videresalg (resale.fotball.no)",
        }.get(source, source)

        lines = [
            "🎟️ *Billetter tilgjengelig!*",
            "",
            f"⚽ {_escape(label)}",
        ]
        if opponent:
            lines.append(f"🆚 {_escape(opponent)}")
        lines += [
            f"📅 {_escape(kickoff_text)}",
            f"📍 {_escape(venue)}",
            f"🔎 {source_line}",
        ]
        if quantity:
            lines.append(f"🎫 {_escape(quantity)}")
        if price:
            lines.append(f"💰 {_escape(price)}")
        lines += ["", f"🔗 {link}"]
        return self.send("\n".join(lines))

    # --- announcements -------------------------------------------------------

    def send_announcement(
        self, headline: str, body_lines: list[str], link: str = ""
    ) -> bool:
        lines = [f"📣 *{_escape(headline)}*", ""] + body_lines
        if link:
            lines += ["", f"🔗 {link}"]
        return self.send("\n".join(lines))

    # --- failures ------------------------------------------------------------

    def send_parse_failure(self, source: str, detail: str, consecutive: int) -> bool:
        return self.send(
            "\n".join(
                [
                    "⚠️ *Parsing feilet*",
                    "",
                    f"Kilde: {_escape(source)}",
                    f"Feil: {_escape(detail)}",
                    f"Sammenhengende feil: {consecutive}",
                    "",
                    "Markupen kan ha endret seg. Sjekk selectors i `endpoints.py`.",
                ]
            )
        )

    # --- heartbeat -----------------------------------------------------------

    def ping_uptime_kuma(self, status: str, msg: str) -> None:
        if not self.uptime_kuma_push_url:
            return
        try:
            # Strip any query the push URL already carries so ours takes effect.
            base = self.uptime_kuma_push_url.split("?")[0]
            requests.get(base, params={"status": status, "msg": msg, "ping": ""}, timeout=10)
        except requests.RequestException as exc:
            logger.warning("uptime kuma ping failed: %s", exc)


def should_alert(last_alert_iso: str | None, cooldown_seconds: int, now: datetime) -> bool:
    """Rate-limit repeated parse-failure alarms to one per cooldown period."""
    if not last_alert_iso:
        return True
    try:
        last = datetime.fromisoformat(last_alert_iso)
    except ValueError:
        return True
    return now - last >= timedelta(seconds=cooldown_seconds)
