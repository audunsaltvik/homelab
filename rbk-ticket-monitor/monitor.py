#!/usr/bin/env python3
"""
RBK Ticket Monitor - Monitors RBK ticket page and sends Telegram notifications
when new matches are available.
"""
import os
import json
import time
import logging
import hashlib
from datetime import datetime
from typing import Set, Dict, Any
import requests
from bs4 import BeautifulSoup

# Configuration from environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '300'))  # Default: 5 minutes
STATE_FILE = os.getenv('STATE_FILE', '/data/state.json')
CHECK_WOMENS_MATCHES = os.getenv('CHECK_WOMENS_MATCHES', 'true').lower() in ('true', '1', 'yes')
UPTIME_KUMA_PUSH_URL = os.getenv('UPTIME_KUMA_PUSH_URL', '')
RBK_URL = 'https://billett.rbk.no/section/kampbilletter-76ym'

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TicketMonitor:
    def __init__(self):
        self.state_file = STATE_FILE
        self.known_matches: Set[str] = self.load_state()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })

    def load_state(self) -> Set[str]:
        """Load known matches from state file."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    return set(data.get('matches', []))
        except Exception as e:
            logger.error(f"Error loading state: {e}")
        return set()

    def save_state(self):
        """Save known matches to state file."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump({
                    'matches': list(self.known_matches),
                    'last_updated': datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def fetch_matches(self) -> Dict[str, Dict[str, Any]]:
        """Fetch and parse matches from RBK ticket page."""
        try:
            logger.info(f"Fetching {RBK_URL}")
            response = self.session.get(RBK_URL, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            matches = {}

            # Find all event links
            match_links = soup.find_all('a', href=lambda x: x and '/event/' in x)

            for link_elem in match_links:
                try:
                    # Get the URL
                    href = link_elem.get('href', '')
                    if not href or '/event/' not in href:
                        continue

                    if not href.startswith('http'):
                        href = f"https://billett.rbk.no{href}"

                    # Try to extract structured information
                    # Look for text elements within the link
                    text_parts = []
                    for text in link_elem.stripped_strings:
                        text_parts.append(text)

                    if not text_parts:
                        continue

                    # Build a readable title
                    # Typically: Date, Match title, Venue
                    title = ' - '.join(text_parts[:3]) if len(text_parts) >= 3 else ' - '.join(text_parts)

                    # If title is still messy, try to extract match name from URL
                    if len(title) < 10 or not any(char.isspace() for char in title):
                        # Extract from URL: /event/rosenborg-brann-ax9b0h -> Rosenborg-Brann
                        url_parts = href.split('/event/')[-1].split('-')
                        # Take the meaningful parts (skip the ID at the end)
                        match_name = ' '.join(url_parts[:-1]).title()
                        title = match_name if match_name else title

                    # Create unique ID from URL (more stable than title)
                    match_id = hashlib.md5(href.encode()).hexdigest()

                    # Filter women's matches if disabled
                    if not CHECK_WOMENS_MATCHES:
                        if 'Toppserien' in title or 'Kvinner' in title or 'kvinner' in title:
                            logger.debug(f"Skipping women's match: {title}")
                            continue

                    if title and len(title) > 3:
                        matches[match_id] = {
                            'title': title,
                            'link': href,
                            'discovered': datetime.now().isoformat()
                        }

                except Exception as e:
                    logger.debug(f"Error parsing element: {e}")
                    continue

            logger.info(f"Found {len(matches)} potential matches")
            return matches

        except Exception as e:
            logger.error(f"Error fetching matches: {e}")
            return {}

    def send_telegram_notification(self, match_info: Dict[str, Any]):
        """Send Telegram notification for new match."""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.warning("Telegram credentials not configured")
            return

        try:
            title = match_info['title']
            link = match_info['link']

            message = (
                f"🎟️ *Nye RBK billetter tilgjengelig!*\n\n"
                f"📅 {title}\n\n"
                f"🔗 [Kjøp billetter her]({link})\n\n"
                f"⚽ Lykke til på Lerkendal!"
            )

            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': False
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Telegram notification sent for: {title}")

        except Exception as e:
            logger.error(f"Error sending Telegram notification: {e}")

    def ping_uptime_kuma(self, status: str = 'up', msg: str = 'OK'):
        if not UPTIME_KUMA_PUSH_URL:
            return
        try:
            # Strip any pre-filled query params from the URL, then add our own
            base_url = UPTIME_KUMA_PUSH_URL.split('?')[0]
            requests.get(base_url, params={'status': status, 'msg': msg, 'ping': ''}, timeout=10)
        except Exception as e:
            logger.warning(f"Uptime Kuma ping failed: {e}")

    def check_for_new_matches(self):
        """Check for new matches and send notifications."""
        matches = self.fetch_matches()

        if not matches:
            logger.warning("No matches found - page structure might have changed")
            self.ping_uptime_kuma(status='down', msg='No matches found - page may have changed')
            return

        # Find new matches
        current_match_ids = set(matches.keys())
        new_match_ids = current_match_ids - self.known_matches

        if new_match_ids:
            logger.info(f"Found {len(new_match_ids)} new match(es)")
            for match_id in new_match_ids:
                match_info = matches[match_id]
                logger.info(f"New match: {match_info['title']}")
                self.send_telegram_notification(match_info)

            # Update known matches
            self.known_matches.update(new_match_ids)
            self.save_state()
        else:
            logger.info("No new matches found")

        self.ping_uptime_kuma(status='up', msg=f"OK - {len(matches)} matches tracked")

    def run(self):
        """Main monitoring loop."""
        logger.info("Starting RBK Ticket Monitor")
        logger.info(f"Checking every {CHECK_INTERVAL} seconds")
        logger.info(f"Monitoring URL: {RBK_URL}")
        logger.info(f"Women's matches (Toppserien): {'ENABLED' if CHECK_WOMENS_MATCHES else 'DISABLED'}")

        # Initial check
        try:
            self.check_for_new_matches()
        except Exception as e:
            logger.error(f"Error during initial check: {e}")

        # Main loop
        while True:
            try:
                time.sleep(CHECK_INTERVAL)
                self.check_for_new_matches()
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(60)  # Wait a bit before retrying


if __name__ == '__main__':
    monitor = TicketMonitor()
    monitor.run()
