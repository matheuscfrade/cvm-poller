from __future__ import annotations

import json
from pathlib import Path

from cvm_poller.parse import IpeLink


class SeenStore:
    def __init__(self, path: Path):
        self.path = path
        self._urls = set(self._load())

    def filter_new(self, links: list[IpeLink]) -> list[IpeLink]:
        return [link for link in links if link.url not in self._urls]

    def mark_seen(self, links: list[IpeLink]) -> None:
        for link in links:
            if link.url:
                self._urls.add(link.url)
        self._save()

    def _load(self) -> list[str]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return list(payload.get("urls", []))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"urls": sorted(self._urls)}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
