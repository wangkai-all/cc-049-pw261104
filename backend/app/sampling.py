"""Deterministic stratified sampling of the start table.

Rules implemented (see project spec):
* every candidate is ranked by BLAKE2b over (seed, table, stable business key),
  so the same data + seed + config yields the same selected business keys, and
  reordering the input CSV cannot change the result;
* each group first receives its minimum quota (smallest sort value wins);
* remaining slots are filled from the global pool of unselected rows;
* sum(quotas) > total => configuration conflict;
* a group (or the table) with fewer rows than needed is reported as a deficit.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .keying import business_key, encode_key, sort_value
from .models import SampleRequest
from .workspace import Workspace


def build_sample_plan(ws: Workspace, req: SampleRequest) -> dict[str, Any]:
    reg = ws.require_registry()
    if req.start_table not in {t.name for t in reg.tables}:
        raise ValueError(f"起点表 {req.start_table} 未登记")
    pk_cols = ws.pk_of(req.start_table)
    if req.group_field:
        available = {c for c, _ in ws.columns_of(req.start_table)}
        if req.group_field not in available:
            raise ValueError(f"分组字段 {req.group_field} 不在表 {req.start_table} 中")

    rows = ws.all_rows(req.start_table)
    # ---- rank every row deterministically --------------------------------
    candidates: list[dict[str, Any]] = []
    for row in rows:
        key = business_key(row, pk_cols)
        group = row.get(req.group_field) if req.group_field else None
        candidates.append(
            {
                "business_key": key,
                "business_key_json": encode_key(key),
                "group": group,
                "sort_value": sort_value(req.seed, req.start_table, key),
            }
        )
    candidates.sort(key=lambda c: (c["sort_value"], c["business_key_json"]))

    quota_sum = sum(req.quotas.values())
    conflict = quota_sum > req.total
    if conflict:
        raise ValueError(
            f"配置冲突：各组最低配额之和 {quota_sum} 超过起点总数 {req.total}，请调增总数或降低配额"
        )

    # quota keys arrive as JSON strings; normalize group values the same way
    # so numeric/boolean group columns still match
    str_quotas = {str(k): v for k, v in req.quotas.items()}

    # unknown groups in quotas are tolerated but flagged for the UI
    present_groups = {str(c["group"]) for c in candidates} if req.group_field else set()

    # ---- phase 1: per-group minimum quotas --------------------------------
    selected: dict[str, dict[str, Any]] = {}
    groups_summary: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"group": None, "total_rows": 0, "quota": 0, "selected": 0, "deficit": 0}
    )
    if req.group_field:
        by_group: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for c in candidates:
            by_group[c["group"]].append(c)
            groups_summary[c["group"]]["group"] = c["group"]
            groups_summary[c["group"]]["total_rows"] += 1
        for group, members in by_group.items():
            groups_summary[group]["quota"] = req.quotas.get(group, 0)

        # groups that have a quota but no rows at all -> hard deficit, still listed
        for g, q in str_quotas.items():
            if g not in {str(x) for x in by_group}:
                groups_summary[g].update(
                    {"group": g, "total_rows": 0, "quota": q, "deficit": q}
                )

        for group in sorted(by_group, key=lambda g: ("" if g is None else str(g))):
            quota = str_quotas.get(str(group), 0)
            chosen = by_group[group][:quota]
            groups_summary[group]["deficit"] = max(0, quota - len(chosen))
            for c in chosen:
                selected[c["business_key_json"]] = {
                    **c,
                    "phase": "quota",
                    "reason": f"满足分组 {group!r} 的最低配额（按种子 {req.seed} 的稳定排序值入选）",
                }
                groups_summary[group]["selected"] += 1
    else:
        groups_summary[None].update(
            {"group": None, "total_rows": len(candidates), "quota": 0, "selected": 0}
        )

    # ---- phase 2: fill remaining slots globally ----------------------------
    remaining = req.total - len(selected)
    fill_rows: list[dict[str, Any]] = []
    for c in candidates:
        if remaining <= 0:
            break
        if c["business_key_json"] in selected:
            continue
        fill_rows.append(c)
        remaining -= 1

    for c in fill_rows:
        selected[c["business_key_json"]] = {
            **c,
            "phase": "fill",
            "reason": "配额满足后，从剩余记录按稳定排序值补足起点总数",
        }
        if req.group_field and c["group"] in groups_summary:
            groups_summary[c["group"]]["selected"] += 1

    total_available = len(candidates)
    deficit = max(0, req.total - total_available)
    unknown_groups = sorted(set(str_quotas) - present_groups) if req.group_field else []

    plan_rows = sorted(
        selected.values(), key=lambda c: (c["sort_value"], c["business_key_json"])
    )
    return {
        "start_table": req.start_table,
        "primary_key": pk_cols,
        "group_field": req.group_field,
        "seed": req.seed,
        "requested_total": req.total,
        "selected_count": len(plan_rows),
        "source_row_count": total_available,
        "deficit": deficit,
        "deficit_message": (
            f"源数据不足：还需 {deficit} 条起点记录（全表仅 {total_available} 条）"
            if deficit
            else None
        ),
        "unknown_groups": unknown_groups,
        "groups": sorted(groups_summary.values(), key=lambda g: str(g["group"])),
        "selected_keys": plan_rows,
    }
