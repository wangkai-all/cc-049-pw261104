"""FastAPI application: upload, registry, sampling, preview, export."""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import demo_data
from .export import IntegrityError, build_zip
from .models import (
    CatalogResponse,
    ColumnInfo,
    ForeignKeySpec,
    RegistryRequest,
    SampleRequest,
    TableInfo,
    TableSpec,
)
from .sampling import build_sample_plan
from .traversal import traverse
from .workspace import quote_ident, get_workspace

app = FastAPI(title="多表关系抽样调试工具", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _catalog(registered: bool) -> CatalogResponse:
    ws = get_workspace()
    tables = []
    pk_map = {}
    if ws.registry:
        pk_map = {t.name: t.primary_key for t in ws.registry.tables}
    for name in ws.list_tables():
        tables.append(
            TableInfo(
                name=name,
                columns=[ColumnInfo(name=c, type=t) for c, t in ws.columns_of(name)],
                row_count=ws.row_count(name),
                primary_key=pk_map.get(name),
            )
        )
    return CatalogResponse(
        tables=tables,
        foreign_keys=ws.registry.foreign_keys if ws.registry else [],
        registered=registered and ws.registry is not None,
    )


# --------------------------------------------------------------------- demo
@app.post("/api/demo")
def load_demo(orphans: bool = False) -> CatalogResponse:
    ws = get_workspace()
    with tempfile.TemporaryDirectory(prefix="sampler-demo-") as tmp:
        paths = demo_data.generate(Path(tmp), orphans=orphans)
        with ws.lock:
            ws.reset()
            for name, p in paths.items():
                ws.load_csv(name, str(p))
            reg = RegistryRequest(
                tables=[
                    TableSpec(name="customers", primary_key=["customer_id"]),
                    TableSpec(name="employees", primary_key=["employee_id"]),
                    TableSpec(name="products", primary_key=["product_id"]),
                    TableSpec(name="orders", primary_key=["order_id"]),
                    TableSpec(name="order_items",
                              primary_key=["order_id", "line_no"]),
                    TableSpec(name="refunds",
                              primary_key=["order_id", "refund_seq"]),
                ],
                foreign_keys=[
                    ForeignKeySpec(name="fk_orders_customer", table="orders",
                                   columns=["customer_id"], ref_table="customers",
                                   ref_columns=["customer_id"]),
                    ForeignKeySpec(name="fk_orders_employee", table="orders",
                                   columns=["employee_id"], ref_table="employees",
                                   ref_columns=["employee_id"]),
                    ForeignKeySpec(name="fk_items_order", table="order_items",
                                   columns=["order_id"], ref_table="orders",
                                   ref_columns=["order_id"]),
                    ForeignKeySpec(name="fk_items_product", table="order_items",
                                   columns=["product_id"], ref_table="products",
                                   ref_columns=["product_id"]),
                    ForeignKeySpec(name="fk_refunds_order", table="refunds",
                                   columns=["order_id"], ref_table="orders",
                                   ref_columns=["order_id"]),
                    ForeignKeySpec(name="fk_employees_manager", table="employees",
                                   columns=["manager_id"], ref_table="employees",
                                   ref_columns=["employee_id"]),
                ],
            )
            ws.set_registry(reg)
    return _catalog(True)


# ------------------------------------------------------------------- upload
@app.post("/api/tables/upload")
async def upload_tables(files: list[UploadFile] = File(...)) -> CatalogResponse:
    ws = get_workspace()
    with tempfile.TemporaryDirectory(prefix="sampler-up-") as tmp:
        for f in files:
            table = Path(f.filename or "").stem
            try:
                quote_ident(table)
            except ValueError as e:
                raise HTTPException(400, str(e))
            dest = Path(tmp) / f.filename
            with dest.open("wb") as out:
                out.write(await f.read())
            try:
                ws.load_csv(table, str(dest))
            except Exception as e:  # duckdb parse errors etc.
                raise HTTPException(400, f"文件 {f.filename} 解析失败: {e}")
    return _catalog(False)


@app.post("/api/reset")
def reset() -> dict:
    get_workspace().reset()
    return {"ok": True}


@app.get("/api/catalog")
def catalog() -> CatalogResponse:
    return _catalog(True)


# ----------------------------------------------------------------- registry
@app.post("/api/registry")
def save_registry(req: RegistryRequest) -> CatalogResponse:
    ws = get_workspace()
    try:
        ws.set_registry(req)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _catalog(True)


# ------------------------------------------------------------- group values
@app.get("/api/groups")
def group_values(table: str, field: str) -> list[dict]:
    ws = get_workspace()
    try:
        qt, qf = quote_ident(table), quote_ident(field)
        rows = ws.con.execute(
            f"SELECT {qf} AS g, count(*) AS n FROM {qt} GROUP BY {qf} ORDER BY {qf}"
        ).fetchall()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"分组字段读取失败: {e}")
    return [{"group": g, "count": n} for g, n in rows]


# -------------------------------------------------------------- integrity
@app.post("/api/integrity")
def integrity() -> dict:
    ws = get_workspace()
    try:
        violations = ws.check_integrity()
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": not violations, "violations": [v.model_dump() for v in violations]}


# ------------------------------------------------------------ sample plan
@app.post("/api/sample/plan")
def sample_plan(req: SampleRequest) -> dict:
    ws = get_workspace()
    try:
        return build_sample_plan(ws, req)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------------- sample run
PREVIEW_CAP = 1000


@app.post("/api/sample/run")
def sample_run(req: SampleRequest) -> dict:
    ws = get_workspace()
    with ws.lock:
        try:
            plan = build_sample_plan(ws, req)
            result = traverse(ws, req, plan)
            full_violations = ws.check_integrity()
        except ValueError as e:
            raise HTTPException(400, str(e))

        preview_tables = []
        for table, recs in result.records.items():
            rows = list(recs.values())
            capped = len(rows) > PREVIEW_CAP
            rows.sort(key=lambda r: (r["_meta"]["depth"], r["_meta"]["business_key_json"]))
            preview_tables.append(
                {
                    "table": table,
                    "primary_key": ws.pk_of(table),
                    "total": len(recs),
                    "sampled": sum(1 for r in recs.values()
                                   if r["_meta"]["origin"] == "sampled"),
                    "parent_completion": sum(
                        1 for r in recs.values()
                        if r["_meta"]["origin"] == "parent_completion"),
                    "child_pull": sum(
                        1 for r in recs.values()
                        if r["_meta"]["origin"] == "child_pull"),
                    "capped": capped,
                    "rows": rows[:PREVIEW_CAP],
                }
            )
        preview_tables.sort(key=lambda t: t["table"])
        return {
            "plan": plan,
            "preview": {
                "tables": preview_tables,
                "waves": result.waves,
                "back_edges": result.back_edges,
            },
            "integrity_warnings": [v.model_dump() for v in full_violations],
        }


# ------------------------------------------------------------------ export
@app.post("/api/export")
def export(req: SampleRequest) -> Response:
    ws = get_workspace()
    with ws.lock:
        try:
            plan = build_sample_plan(ws, req)
            result = traverse(ws, req, plan)
            data = build_zip(ws, result, plan, req.model_dump())
        except IntegrityError as e:
            return JSONResponse(
                status_code=409,
                content={
                    "blocked": True,
                    "message": "导出子集存在孤立外键，已阻止导出，请先修复缺失关系",
                    "violations": [v.model_dump() for v in e.violations],
                },
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="sample_export.zip"'},
    )


# serve built frontend if present
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(_dist), html=True),
        name="frontend",
    )
