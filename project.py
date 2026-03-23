from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Project:
    source: str
    project_id: str
    title: str
    description: str
    url: str

    price_from: int | None = None
    price_to: int | None = None

    category_id: int | None = None
    parent_category_id: int | None = None

    client_username: str | None = None
    client_hired_percent: int | None = None

    offers: int = 0
    time_left_seconds: int | None = None

    score: int | None = None
    score_reason: str = ""

    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def budget_text(self) -> str:
        if self.price_from is None and self.price_to is None:
            return "бюджет не указан"
        if self.price_to and self.price_from and self.price_to > self.price_from:
            return f"от {self.price_from} ₽ до {self.price_to} ₽"
        if self.price_from is not None:
            return f"до {self.price_from} ₽"
        return f"до {self.price_to} ₽"

    @property
    def hours_left(self) -> int | None:
        if self.time_left_seconds is None:
            return None
        return self.time_left_seconds // 3600
