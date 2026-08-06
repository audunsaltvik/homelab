"""State persistence on the shared PVC.

The two CronJobs never write the same file. The announcement watcher owns
announcements.json and sale_schedule.json; the availability watcher owns
availability.json and only reads the schedule. Splitting ownership this way
removes the need for locking between two jobs that can overlap.

Writes go through a temp file plus rename so a pod killed mid-write leaves the
previous state intact instead of a truncated file.
"""

import json
import logging
import os
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def read_json(path: str, default: dict[str, Any]) -> dict[str, Any]:
    if not os.path.exists(path):
        logger.info("no state at %s; starting from empty state", path)
        return dict(default)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        # A corrupt state file must not wedge the monitor forever. Starting
        # over costs at most one duplicate notification.
        logger.error("state at %s is unreadable (%s); starting from empty state", path, exc)
        return dict(default)

    if data.get("schema") != SCHEMA_VERSION:
        logger.warning(
            "state at %s has schema %r, expected %r; starting from empty state",
            path,
            data.get("schema"),
            SCHEMA_VERSION,
        )
        return dict(default)
    return data


def write_json(path: str, data: dict[str, Any]) -> None:
    data["schema"] = SCHEMA_VERSION
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)

    # Temp file must share the filesystem with the target for rename to be atomic.
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
    )
    try:
        with handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except Exception:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
