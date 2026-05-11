from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..domain.licenses import NewsItem


@dataclass
class NotificationState:
    storage_path: Path

    def _load(self) -> set[str]:
        if not self.storage_path.exists():
            return set()
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            return set(map(str, data.get("read_news_ids", [])))
        except Exception:
            return set()

    def unread(self, items: list[NewsItem]) -> list[NewsItem]:
        read = self._load()
        return [item for item in items if item.news_id not in read]

    def mark_read(self, news_id: str) -> None:
        read = self._load()
        read.add(news_id)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps({"read_news_ids": sorted(read)}, ensure_ascii=False, indent=2), encoding="utf-8")
