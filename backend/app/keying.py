"""Deterministic business-key / sort-key helpers.

Selection must be reproducible from data + seed + config regardless of input
file order, so we never rely on physical row order: every candidate is ranked
by a hash over (seed, table name, stable JSON business key).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence


def normalize_value(value: Any) -> Any:
    """Make a scalar hashable / JSON-stable. None stays None."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def business_key(row: dict[str, Any], key_columns: Sequence[str]) -> list[Any]:
    """Extract a primary/foreign key value list from a row."""
    return [normalize_value(row.get(col)) for col in key_columns]


def encode_key(values: Sequence[Any]) -> str:
    """Stable wire/identity form for a (composite) key value."""
    return json.dumps([normalize_value(v) for v in values], ensure_ascii=False, sort_keys=False)


def sort_value(seed: int, table: str, key_values: Sequence[Any]) -> str:
    """Deterministic ranking token.

    BLAKE2b keyed with the seed over the table name and the stable JSON
    business key. Returns a hex digest; comparing lexicographically gives a
    total, order-independent ranking.
    """
    payload = json.dumps(
        {"seed": seed, "table": table, "key": [normalize_value(v) for v in key_values]},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=16).hexdigest()


def key_tuple(key_values: Sequence[Any]) -> tuple:
    """Hashable tuple form (None preserved) for visited sets."""
    return tuple(normalize_value(v) for v in key_values)
