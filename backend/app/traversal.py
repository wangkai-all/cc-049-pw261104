"""Graph traversal: start-table sample -> parent completion -> optional children.

Dedup: each (table, primary key) is kept once; many children referencing the
same parent therefore produce one parent row.
Cycles: visited records are remembered by (table name, primary key tuple), so
a self-reference or an FK cycle terminates and back-edges are counted.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .keying import business_key, encode_key, key_tuple
from .models import ForeignKeySpec, SampleRequest
from .workspace import Workspace


class TraversalResult:
    def __init__(self) -> None:
        # table -> key_tuple -> annotated row
        self.records: dict[str, dict[tuple, dict[str, Any]]] = defaultdict(dict)
        self.back_edges: list[dict[str, str]] = []
        self.waves: list[dict[str, Any]] = []

    def seen(self, table: str, key: tuple) -> bool:
        return key in self.records[table]

    def add(self, table: str, pk_cols: list[str], row: dict[str, Any], *,
            origin: str, reason: str, depth: int) -> tuple:
        key = key_tuple(business_key(row, pk_cols))
        if key in self.records[table]:
            return key, False
        enriched = dict(row)
        enriched["_meta"] = {
            "business_key": business_key(row, pk_cols),
            "business_key_json": encode_key(business_key(row, pk_cols)),
            "origin": origin,       # sampled | parent_completion | child_pull
            "reason": reason,
            "depth": depth,
        }
        self.records[table][key] = enriched
        return key, True


def _incoming_fks(fks: list[ForeignKeySpec], table: str) -> list[ForeignKeySpec]:
    """FKs where `table` is the child (point to parents)."""
    return [fk for fk in fks if fk.table == table]


def _outgoing_fks(fks: list[ForeignKeySpec], table: str) -> list[ForeignKeySpec]:
    """FKs where some other table references `table` (children point at it)."""
    return [fk for fk in fks if fk.ref_table == table and fk.table != table]


def traverse(ws: Workspace, req: SampleRequest, plan: dict[str, Any]) -> TraversalResult:
    reg = ws.require_registry()
    fks = reg.foreign_keys
    child_policy = {p.table: p.policy for p in req.child_policies}
    result = TraversalResult()

    start = req.start_table
    start_pk = ws.pk_of(start)
    start_keys = [key_tuple(c["business_key"]) for c in plan["selected_keys"]]
    start_rows = ws.fetch_by_keys(start, start_pk, start_keys)
    reasons = {c["business_key_json"]: c["reason"] for c in plan["selected_keys"]}
    for row in start_rows:
        bk = encode_key(business_key(row, start_pk))
        result.add(
            start, start_pk, row,
            origin="sampled",
            reason=reasons.get(bk, "起点抽样入选"),
            depth=0,
        )
    result.waves.append({"wave": 0, "added": {start: len(start_rows)}, "note": "起点抽样"})

    depth = 0
    while True:
        depth += 1
        added_this_wave: dict[str, int] = defaultdict(int)
        # snapshot so rows added during this wave start a new wave
        frontier = {t: list(recs.keys()) for t, recs in result.records.items()}

        for table, keys in list(frontier.items()):
            if not keys:
                continue
            pk_cols = ws.pk_of(table)

            # 1) parent completion: walk every outgoing FK of this table ----
            for fk in _incoming_fks(fks, table):
                rows = result.records[table]
                fk_values = {
                    key_tuple(business_key(r, fk.columns))
                    for r in rows.values()
                    if all(r.get(c) is not None for c in fk.columns)
                }
                if not fk_values:
                    continue
                parent_pk = ws.pk_of(fk.ref_table)
                parents = ws.fetch_by_fk(fk, list(fk_values), want_source=False)
                for prow in parents:
                    pkey, inserted = result.add(
                        fk.ref_table, parent_pk, prow,
                        origin="parent_completion",
                        reason=f"被 {table} 的外键 {fk.name} 引用，递归补齐父记录",
                        depth=depth,
                    )
                    if inserted:
                        added_this_wave[fk.ref_table] += 1
                    else:
                        result.back_edges.append(
                            {"from": f"{table}({fk.name})", "to": f"{fk.ref_table}{list(pkey)}"}
                        )

            # 2) optional children: only when policy == 'all' ---------------
            if child_policy.get(table, "none") == "all":
                for fk in _outgoing_fks(fks, table):
                    children = ws.fetch_by_fk(fk, keys, want_source=True)
                    child_pk = ws.pk_of(fk.table)
                    for crow in children:
                        _, inserted = result.add(
                            fk.table, child_pk, crow,
                            origin="child_pull",
                            reason=f"父表 {table} 选择「全部带出」，按外键 {fk.name} 带出子记录",
                            depth=depth,
                        )
                        if inserted:
                            added_this_wave[fk.table] += 1

        if not added_this_wave:
            break
        result.waves.append(
            {"wave": depth, "added": dict(added_this_wave),
             "note": "父记录补齐" + "/子表带出"}
        )

    return result
