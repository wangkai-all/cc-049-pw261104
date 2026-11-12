"""Build the multi-table export: subset views, final FK re-check, ZIP stream."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .traversal import TraversalResult
from .workspace import Workspace


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def _build_subset_views(ws: Workspace, result: TraversalResult) -> dict[str, str]:
    """Create per-table temp key tables + views.

    Every registered table gets a view, including tables with zero selected
    rows: without an empty view the integrity check would fall back to the
    full source table and report false orphans against the subset.
    Views reference the temp key tables, so the latter must survive until the
    whole export finishes; callers invoke _cleanup_subset() afterwards.
    """
    reg = ws.require_registry()
    views: dict[str, str] = {}
    for spec in reg.tables:
        table = spec.name
        recs = result.records.get(table, {})
        pk_cols = ws.pk_of(table)
        key_values = [list(k) for k in recs.keys()]
        types = ws._col_types(table, pk_cols)  # noqa: SLF001
        key_table = f"_subset_keys_{table}"
        ws._make_key_table(key_table, pk_cols, types, key_values)  # noqa: SLF001
        view = f"_subset_{table}"
        join = " AND ".join(
            f't."{c}" IS NOT DISTINCT FROM k."{c}"' for c in pk_cols
        )
        ws.con.execute(
            f"CREATE OR REPLACE TEMP VIEW {view} AS "
            f'SELECT t.* FROM "{table}" t JOIN {key_table} k ON {join}'
        )
        views[table] = view
    return views


def _cleanup_subset(ws: Workspace) -> None:
    reg = ws.require_registry()
    for spec in reg.tables:
        ws.con.execute(f'DROP VIEW IF EXISTS "_subset_{spec.name}"')
        ws.con.execute(f'DROP TABLE IF EXISTS "_subset_keys_{spec.name}"')


def build_zip(ws: Workspace, result: TraversalResult,
              plan: dict[str, Any], req: dict[str, Any]) -> bytes:
    """Re-check FK integrity on the export subset, then zip per-table CSVs."""
    views = _build_subset_views(ws, result)
    try:
        violations = ws.check_integrity(subset_views=views)
        if violations:
            # never export a broken subset; caller turns this into a 409 payload
            raise IntegrityError(violations)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # only emit CSVs for tables that actually contain selected rows
            for table, view in views.items():
                if table not in result.records:
                    continue
                tmp = ws.data_dir / f"_export_{table}.csv"
                ws.export_csv(table, view, tmp)
                zf.write(tmp, arcname=f"{table}.csv")
                tmp.unlink(missing_ok=True)

            per_table = {
                table: {
                    "sampled": sum(1 for r in recs.values() if r["_meta"]["origin"] == "sampled"),
                    "parent_completion": sum(
                        1 for r in recs.values() if r["_meta"]["origin"] == "parent_completion"),
                    "child_pull": sum(
                        1 for r in recs.values() if r["_meta"]["origin"] == "child_pull"),
                    "total": len(recs),
                }
                for table, recs in result.records.items()
            }
            manifest = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "start_table": plan["start_table"],
                "seed": plan["seed"],
                "group_field": plan["group_field"],
                "requested_total": plan["requested_total"],
                "selected_count": plan["selected_count"],
                "config": req,
                "per_table": per_table,
                "waves": result.waves,
                "integrity": "ok",
            }
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default),
            )
        return buffer.getvalue()
    finally:
        _cleanup_subset(ws)


class IntegrityError(Exception):
    def __init__(self, violations: list):
        self.violations = violations
        super().__init__("导出子集存在孤立外键，已阻止导出")
