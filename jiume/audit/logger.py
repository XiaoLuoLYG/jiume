"""Append-only JSONL audit logging for twin actions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from jiume.paths import get_twin_root


def append_audit_event(twin_id: str, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {
        "type": event_type,
        "twin_id": twin_id,
        "payload": payload or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = get_twin_root(twin_id) / "audit" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read_audit_events(twin_id: str, limit: int = 100) -> list[dict[str, Any]]:
    path = get_twin_root(twin_id) / "audit" / "events.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    events: list[dict[str, Any]] = []
    for line in lines[-max(1, min(limit, 500)):]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events
