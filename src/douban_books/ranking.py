from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def integrated_score(rating: float | None, votes: int | None, delta: float = 2.5) -> float | None:
    if rating is None:
        return None
    if votes is None or votes <= 0:
        return 0.0
    return (rating - delta) * math.log(votes)


def rank_books(rows: Sequence[Mapping[str, Any]], delta: float = 2.5) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["score"] = integrated_score(item.get("rating"), item.get("votes"), delta)
        ranked.append(item)
    ranked.sort(
        key=lambda item: (
            item["score"] is not None,
            item["score"] if item["score"] is not None else float("-inf"),
            item.get("votes") if item.get("votes") is not None else -1,
            -int(item["douban_id"]),
        ),
        reverse=True,
    )
    return ranked

