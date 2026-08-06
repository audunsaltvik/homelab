"""Entry point. One image, one command argument picks the job."""

import argparse
import json
import logging
import sys

from . import config, endpoints
from .httpclient import HttpClient
from .jobs import announce, availability
from .notify import Notifier
from .sources import primary


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _client(cfg: config.Config) -> HttpClient:
    return HttpClient(
        user_agent=cfg.user_agent,
        timeout_seconds=cfg.request_timeout_seconds,
        min_interval_seconds=cfg.min_request_interval_seconds,
        max_retries=cfg.max_retries,
        backoff_base_seconds=cfg.backoff_base_seconds,
        backoff_max_seconds=cfg.backoff_max_seconds,
    )


def _cmd_list_products(cfg: config.Config) -> int:
    """Print productIds for values.yaml. Not run in-cluster; a helper for you."""
    products = primary.fetch_catalog(_client(cfg))
    for product in sorted(products, key=lambda p: str(p.get("firstPerformanceDate"))):
        print(
            f"{product.get('productId')}  "
            f"qty={product.get('availableQuantity')!s:>6}  "
            f"{product.get('name')}  "
            f"[{product.get('venue')}]  "
            f"first={product.get('firstPerformanceDate')}"
        )
    return 0


def _cmd_check(cfg: config.Config) -> int:
    """Dry inspection of every watched product. Sends nothing."""
    client = _client(cfg)
    for entry in cfg.watch:
        print(f"# {entry.label} (productId={entry.product_id})")
        for perf in primary.fetch_performances(client, entry.product_id, cfg.timezone):
            print(
                f"  {perf.performance_id}  {perf.state:<10} {perf.name:<30} "
                f"{perf.kickoff_text}  {perf.min_price_text}  resale_hint={perf.has_resale_hint}"
            )
    return 0


def _cmd_robots(cfg: config.Config) -> int:
    """Report robots.txt verdict for every URL this monitor touches."""
    client = _client(cfg)
    urls = [
        endpoints.ANNOUNCEMENTS_URL,
        endpoints.PRIMARY_CATALOG_URL,
        endpoints.PRIMARY_PERFORMANCES_URL.format(product_id=0),
        endpoints.RESALE_ITEMS_URL.format(performance_id=0),
    ]
    disallowed = 0
    for url in urls:
        allowed = client.is_allowed(url)
        disallowed += 0 if allowed else 1
        print(f"{'ALLOWED   ' if allowed else 'DISALLOWED'}  {url}")
    return 1 if disallowed else 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="nffmon")
    parser.add_argument(
        "command",
        choices=["announce", "availability", "list-products", "check", "robots"],
    )
    args = parser.parse_args(argv)

    try:
        cfg = config.load()
    except config.ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    if args.command == "list-products":
        return _cmd_list_products(cfg)
    if args.command == "check":
        return _cmd_check(cfg)
    if args.command == "robots":
        return _cmd_robots(cfg)

    notifier = Notifier(
        cfg.telegram_bot_token, cfg.telegram_chat_id, cfg.uptime_kuma_push_url
    )
    client = _client(cfg)

    if args.command == "announce":
        return announce.run(cfg, client, notifier)
    return availability.run(cfg, client, notifier)


if __name__ == "__main__":
    sys.exit(main())
