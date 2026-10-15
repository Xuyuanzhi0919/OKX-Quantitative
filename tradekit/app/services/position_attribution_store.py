from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.attribution import PositionAttributionUpdate


class PositionAttributionStore:
    def __init__(self, path: Path):
        self.path = path

    def list(self) -> list[dict[str, Any]]:
        return list(self._read().values())

    def get(self, position_key: str) -> dict[str, Any] | None:
        return self._read().get(position_key)

    def get_many(self, position_keys: list[str]) -> dict[str, dict[str, Any]]:
        data = self._read()
        return {key: data[key] for key in position_keys if key in data}

    def upsert(self, position_key: str, payload: PositionAttributionUpdate) -> dict[str, Any]:
        data = self._read()
        now = datetime.now(timezone.utc).isoformat()
        existing = data.get(position_key, {})
        item = {
            "position_key": position_key,
            "kind": payload.kind,
            "note": payload.note,
            "strategy_id": payload.strategy_id,
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        data[position_key] = item
        self._write(data)
        return item

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)
