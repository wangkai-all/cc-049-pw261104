"""Workspace state: DuckDB connection, CSV ingestion, registry, integrity checks.

A single in-memory DuckDB database lives for the server process and is guarded
by one lock (FastAPI may run sync endpoints in a threadpool).
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

import duckdb

from .models import ForeignKeySpec, RegistryRequest, Violation

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"非法标识符: {name!r}（仅允许字母/下划线开头，字母数字下划线）")
    return f'"{name}"'


class Workspace:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(database=":memory:")
        self.lock = threading.RLock()
        self.registry: Optional[RegistryRequest] = None

    # ------------------------------------------------------------------ reset
    def reset(self) -> None:
        with self.lock:
            tables = self.con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
            for (name,) in tables:
                self.con.execute(f"DROP TABLE IF EXISTS {quote_ident(name)}")
            self.registry = None
            for f in self.data_dir.glob("*.csv"):
                f.unlink()

    # ------------------------------------------------------------- CSV upload
    def load_csv(self, table_name: str, source_path: str) -> int:
        """Ingest a CSV into a (replaced) DuckDB table. Returns row count."""
        q = quote_ident(table_name)
        with self.lock:
            self.registry = None  # schema changed -> previous registry is stale
            self.con.execute(
                f"CREATE OR REPLACE TABLE {q} AS SELECT * FROM read_csv_auto(?, header=true)",
                [source_path],
            )
            dest = self.data_dir / f"{table_name}.csv"
            self.con.execute(
                f"COPY {q} TO ? (HEADER, DELIMITER ',')", [str(dest)]
            )
            return self.con.execute(f"SELECT count(*) FROM {q}").fetchone()[0]

    def list_tables(self) -> list[str]:
        return [
            r[0]
            for r in self.con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main' ORDER BY table_name"
            ).fetchall()
        ]

    def columns_of(self, table: str) -> list[tuple[str, str]]:
        return self.con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema='main' AND table_name=? ORDER BY ordinal_position",
            [table],
        ).fetchall()

    def row_count(self, table: str) -> int:
        return self.con.execute(
            f"SELECT count(*) FROM {quote_ident(table)}"
        ).fetchone()[0]

    def all_rows(self, table: str) -> list[dict[str, Any]]:
        cols = [c for c, _ in self.columns_of(table)]
        cur = self.con.execute(f"SELECT * FROM {quote_ident(table)}")
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # -------------------------------------------------------------- registry
    def set_registry(self, req: RegistryRequest) -> None:
        with self.lock:
            existing = set(self.list_tables())
            for spec in req.tables:
                if spec.name not in existing:
                    raise ValueError(f"表 {spec.name} 不存在，请先上传 CSV")
                cols = {c for c, _ in self.columns_of(spec.name)}
                missing = [c for c in spec.primary_key if c not in cols]
                if missing:
                    raise ValueError(f"表 {spec.name} 的主键列不存在: {missing}")
                # composite PK must actually be unique
                pk = ", ".join(quote_ident(c) for c in spec.primary_key)
                total, distinct = self.con.execute(
                    f"SELECT count(*), count(DISTINCT ROW({pk})) FROM {quote_ident(spec.name)}"
                ).fetchone()
                if total != distinct:
                    raise ValueError(f"表 {spec.name} 的主键 {spec.primary_key} 存在重复值，不能作为主键")

            known_tables = {s.name for s in req.tables}
            normalized: list[ForeignKeySpec] = []
            for i, fk in enumerate(req.foreign_keys):
                if fk.table not in known_tables or fk.ref_table not in known_tables:
                    raise ValueError(f"外键 {fk.name or i} 引用了未登记的表")
                src_cols = dict(self.columns_of(fk.table))
                ref_cols = dict(self.columns_of(fk.ref_table))
                for c in fk.columns:
                    if c not in src_cols:
                        raise ValueError(f"外键列 {fk.table}.{c} 不存在")
                for c in fk.ref_columns:
                    if c not in ref_cols:
                        raise ValueError(f"被引用列 {fk.ref_table}.{c} 不存在")
                if len(fk.columns) != len(fk.ref_columns):
                    raise ValueError(f"外键 {fk.name or i} 两侧列数不一致")
                name = fk.name or f"fk_{fk.table}_{'_'.join(fk.columns)}__{fk.ref_table}"
                normalized.append(
                    ForeignKeySpec(
                        name=name,
                        table=fk.table,
                        columns=fk.columns,
                        ref_table=fk.ref_table,
                        ref_columns=fk.ref_columns,
                    )
                )
            req.foreign_keys = normalized
            self.registry = req

    def require_registry(self) -> RegistryRequest:
        if self.registry is None:
            raise ValueError("尚未登记主键/外键，请先在「关系登记」页保存")
        return self.registry

    def pk_of(self, table: str) -> list[str]:
        reg = self.require_registry()
        for spec in reg.tables:
            if spec.name == table:
                return list(spec.primary_key)
        raise ValueError(f"未登记的表: {table}")

    def foreign_keys(self) -> list[ForeignKeySpec]:
        return self.require_registry().foreign_keys

    # ---------------------------------------------------- key-driven row fetch
    def _col_types(self, table: str, cols: list[str]) -> list[str]:
        meta = dict(self.columns_of(table))
        return [meta[c] for c in cols]

    def _make_key_table(self, name: str, cols: list[str], types: list[str],
                        key_values: list[tuple]) -> None:
        self.con.execute(f"DROP TABLE IF EXISTS {quote_ident(name)}")
        ddl = ", ".join(f"{quote_ident(c)} {t}" for c, t in zip(cols, types))
        self.con.execute(f"CREATE TEMP TABLE {quote_ident(name)} ({ddl})")
        if key_values:
            self.con.executemany(
                f"INSERT INTO {quote_ident(name)} VALUES ({', '.join('?' * len(cols))})",
                [tuple(v) for v in key_values],
            )

    def fetch_by_keys(self, table: str, key_cols: list[str],
                      key_values: list[tuple]) -> list[dict[str, Any]]:
        """Rows of `table` whose key columns match any value in key_values."""
        if not key_values:
            return []
        types = self._col_types(table, key_cols)
        self._make_key_table("_probe_keys", key_cols, types, key_values)
        qt = quote_ident(table)
        join = " AND ".join(
            f"t.{quote_ident(c)} IS NOT DISTINCT FROM k.{quote_ident(c)}"
            for c in key_cols
        )
        cur = self.con.execute(
            f"SELECT t.* FROM {qt} t JOIN _probe_keys k ON {join}"
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        self.con.execute("DROP TABLE IF EXISTS _probe_keys")
        return rows

    def fetch_by_fk(self, fk: ForeignKeySpec, parent_key_values: list[tuple],
                    want_source: bool) -> list[dict[str, Any]]:
        """Fetch child rows (want_source=True) matching parent keys, or parent
        rows (want_source=False) referenced by child keys."""
        if want_source:
            probe_table, probe_cols, target_table, target_cols = (
                fk.ref_table, fk.ref_columns, fk.table, fk.columns)
        else:
            probe_table, probe_cols, target_table, target_cols = (
                fk.table, fk.columns, fk.ref_table, fk.ref_columns)
        types = self._col_types(probe_table, probe_cols)
        self._make_key_table("_probe_keys", probe_cols, types, parent_key_values)
        qt = quote_ident(target_table)
        join = " AND ".join(
            f"t.{quote_ident(tc)} IS NOT DISTINCT FROM k.{quote_ident(pc)}"
            for tc, pc in zip(target_cols, probe_cols)
        )
        # nullable FK: a row whose whole key is NULL must not be pulled
        not_null = " AND ".join(f"t.{quote_ident(c)} IS NOT NULL" for c in target_cols)
        cur = self.con.execute(
            f"SELECT DISTINCT t.* FROM {qt} t JOIN _probe_keys k ON {join} "
            f"WHERE {not_null}"
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        self.con.execute("DROP TABLE IF EXISTS _probe_keys")
        return rows

    # ------------------------------------------------------------- integrity
    def check_integrity(self, subset_views: Optional[dict[str, str]] = None,
                        limit_per_fk: int = 200) -> list[Violation]:
        """Anti-join every registered FK.

        subset_views maps table name -> temp view holding only exported rows;
        when omitted the check runs against the full source data.
        """
        reg = self.require_registry()
        views = subset_views or {}
        violations: list[Violation] = []
        for fk in reg.foreign_keys:
            src = quote_ident(views.get(fk.table) or fk.table)
            ref = quote_ident(views.get(fk.ref_table) or fk.ref_table)
            match = " AND ".join(
                f"s.{quote_ident(c)} IS NOT DISTINCT FROM r.{quote_ident(rc)}"
                for c, rc in zip(fk.columns, fk.ref_columns)
            )
            not_null = " AND ".join(
                f"s.{quote_ident(c)} IS NOT NULL" for c in fk.columns
            )
            sql = (
                f"SELECT DISTINCT {', '.join('s.' + quote_ident(c) for c in fk.columns)} "
                f"FROM {src} s WHERE {not_null} AND NOT EXISTS "
                f"(SELECT 1 FROM {ref} r WHERE {match}) LIMIT {int(limit_per_fk) + 1}"
            )
            cur = self.con.execute(sql)
            bad = cur.fetchall()
            if not bad:
                continue
            truncated = len(bad) > limit_per_fk
            bad = bad[:limit_per_fk]
            missing = [dict(zip(fk.columns, row)) for row in bad]
            total_sql = (
                f"SELECT count(*) FROM (SELECT DISTINCT {', '.join('s.' + quote_ident(c) for c in fk.columns)} "
                f"FROM {src} s WHERE {not_null} AND NOT EXISTS "
                f"(SELECT 1 FROM {ref} r WHERE {match}))"
            )
            total = self.con.execute(total_sql).fetchone()[0]
            violations.append(
                Violation(
                    foreign_key=fk.name or "fk",
                    source_table=fk.table,
                    source_columns=fk.columns,
                    ref_table=fk.ref_table,
                    ref_columns=fk.ref_columns,
                    missing_keys=missing,
                    count=total,
                    **({"note": f"仅展示前 {limit_per_fk} 个缺失键"} if truncated else {}),  # type: ignore[arg-type]
                )
            )
        return violations

    def export_csv(self, table: str, view_name: str, dest: Path) -> None:
        self.con.execute(
            f"COPY {quote_ident(view_name)} TO ? (HEADER, DELIMITER ',')",
            [str(dest)],
        )


_ws: Optional[Workspace] = None


def get_workspace() -> Workspace:
    global _ws
    if _ws is None:
        _ws = Workspace(Path(os.environ.get("SAMPLER_DATA_DIR", "data")))
    return _ws
