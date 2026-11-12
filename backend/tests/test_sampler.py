import importlib
import sys
import tempfile
from pathlib import Path

import pytest

# make backend package importable when running pytest from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLER_DATA_DIR", str(tmp_path / "data"))
    from app import workspace as ws_mod
    importlib.reload(ws_mod)
    from app.demo_data import generate
    from app.models import ForeignKeySpec, RegistryRequest, TableSpec

    workspace = ws_mod.get_workspace()
    paths = generate(Path(tmp_path) / "demo", orphans=False)
    for name, p in paths.items():
        workspace.load_csv(name, str(p))
    workspace.set_registry(
        RegistryRequest(
            tables=[
                TableSpec(name="customers", primary_key=["customer_id"]),
                TableSpec(name="employees", primary_key=["employee_id"]),
                TableSpec(name="products", primary_key=["product_id"]),
                TableSpec(name="orders", primary_key=["order_id"]),
                TableSpec(name="order_items", primary_key=["order_id", "line_no"]),
                TableSpec(name="refunds", primary_key=["order_id", "refund_seq"]),
            ],
            foreign_keys=[
                ForeignKeySpec(name="fk_orders_customer", table="orders",
                               columns=["customer_id"], ref_table="customers",
                               ref_columns=["customer_id"]),
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
    )
    return workspace


def _sample_request(**overrides):
    from app.models import SampleRequest
    base = {"start_table": "orders", "total": 6, "seed": 42}
    base.update(overrides)
    return SampleRequest(**base)


def test_deterministic_same_keys(ws):
    from app.sampling import build_sample_plan
    req = _sample_request()
    p1 = build_sample_plan(ws, req)
    p2 = build_sample_plan(ws, req)
    keys = [k["business_key_json"] for k in p1["selected_keys"]]
    assert keys == [k["business_key_json"] for k in p2["selected_keys"]]
    assert len(keys) == len(set(keys)) == 6


def test_row_order_does_not_matter(ws, tmp_path):
    # shuffle the orders CSV physically; selected business keys must be identical
    import csv
    from app.models import SampleRequest
    from app.sampling import build_sample_plan

    before = [k["business_key_json"] for k in build_sample_plan(ws, _sample_request())["selected_keys"]]

    src = Path(__file__).resolve().parents[1] / "app" / "demo_data.py"
    # re-ingest rows in reverse via a new table then swap
    rows = ws.all_rows("orders")
    shuffled = list(reversed(rows))
    p = tmp_path / "orders_rev.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(shuffled[0].keys()))
        w.writeheader()
        w.writerows(shuffled)
    ws.load_csv("orders", str(p))
    # registry dropped by reload; re-register
    ws.set_registry(_re_registry(ws))
    after = [k["business_key_json"]
             for k in build_sample_plan(ws, SampleRequest(start_table="orders", total=6, seed=42))["selected_keys"]]
    assert before == after


def _re_registry(ws):
    from app.models import ForeignKeySpec, RegistryRequest, TableSpec
    return RegistryRequest(
        tables=[
            TableSpec(name="customers", primary_key=["customer_id"]),
            TableSpec(name="employees", primary_key=["employee_id"]),
            TableSpec(name="products", primary_key=["product_id"]),
            TableSpec(name="orders", primary_key=["order_id"]),
            TableSpec(name="order_items", primary_key=["order_id", "line_no"]),
            TableSpec(name="refunds", primary_key=["order_id", "refund_seq"]),
        ],
        foreign_keys=[
            ForeignKeySpec(name="fk_orders_customer", table="orders", columns=["customer_id"],
                           ref_table="customers", ref_columns=["customer_id"]),
            ForeignKeySpec(name="fk_items_order", table="order_items", columns=["order_id"],
                           ref_table="orders", ref_columns=["order_id"]),
            ForeignKeySpec(name="fk_items_product", table="order_items", columns=["product_id"],
                           ref_table="products", ref_columns=["product_id"]),
            ForeignKeySpec(name="fk_refunds_order", table="refunds", columns=["order_id"],
                           ref_table="orders", ref_columns=["order_id"]),
            ForeignKeySpec(name="fk_employees_manager", table="employees", columns=["manager_id"],
                           ref_table="employees", ref_columns=["employee_id"]),
        ],
    )


def test_quota_conflict(ws):
    req = _sample_request(
        group_field="region",
        total=3,
        quotas={"华东": 2, "华南": 2},  # sum 4 > 3
    )
    from app.sampling import build_sample_plan
    with pytest.raises(ValueError, match="配置冲突"):
        build_sample_plan(ws, req)


def test_quota_then_fill(ws):
    req = _sample_request(
        group_field="status", total=10, seed=7,
        quotas={"paid": 4, "cancelled": 3},
    )
    from app.sampling import build_sample_plan
    plan = build_sample_plan(ws, req)
    by_phase = {}
    for k in plan["selected_keys"]:
        by_phase.setdefault(k["phase"], 0)
        by_phase[k["phase"]] += 1
    # each group has >= quota rows in source (30 orders / 4 statuses)
    quota_rows = [k for k in plan["selected_keys"] if k["phase"] == "quota"]
    counts = {}
    for k in quota_rows:
        counts[k["group"]] = counts.get(k["group"], 0) + 1
    assert counts["paid"] == 4
    assert counts["cancelled"] == 3
    assert plan["selected_count"] == 10
    assert plan["deficit"] == 0


def test_numeric_group_quota_keys_match(ws):
    """Quotas arrive as JSON strings; a numeric group column must still match."""
    from app.models import SampleRequest
    from app.sampling import build_sample_plan

    # amount is a numeric column in demo orders
    amount = ws.con.execute("SELECT DISTINCT amount FROM orders ORDER BY 1 LIMIT 1").fetchone()[0]
    req = SampleRequest(
        start_table="orders", total=10, seed=5,
        group_field="amount", quotas={str(amount): 2},
    )
    plan = build_sample_plan(ws, req)
    quota_rows = [k for k in plan["selected_keys"] if k["phase"] == "quota"]
    assert quota_rows and all(k["group"] == amount for k in quota_rows)
    assert len(quota_rows) == 2
    assert plan["unknown_groups"] == []


def test_deficit_reported(ws):
    req = _sample_request(total=999)
    from app.sampling import build_sample_plan
    plan = build_sample_plan(ws, req)
    assert plan["selected_count"] == 30
    assert plan["deficit"] == 999 - 30
    assert "还需" in plan["deficit_message"]


def test_traversal_parents_dedup_and_cycle(ws):
    from app.traversal import traverse
    req = _sample_request(total=8, seed=1)
    from app.sampling import build_sample_plan
    plan = build_sample_plan(ws, req)
    result = traverse(ws, req, plan)
    # parents were completed and each (table, key) appears once
    assert len(result.records["orders"]) == 8
    customers = result.records["customers"]
    assert customers, "客户父记录应被递归补齐"
    assert len(customers) == len(set(customers.keys()))


def test_self_reference_cycle_terminates(ws):
    """Sampling employees walks the manager self-FK; the E1<->E2 cycle must
    terminate via (table, pk) visited tracking."""
    from app.models import SampleRequest
    from app.sampling import build_sample_plan
    from app.traversal import traverse
    req = SampleRequest(start_table="employees", total=2, seed=3)
    plan = build_sample_plan(ws, req)
    result = traverse(ws, req, plan)
    assert len(result.records["employees"]) <= ws.row_count("employees")
    assert result.back_edges  # back edges were noticed and suppressed


def test_child_policy_all_and_composite_pk(ws):
    from app.models import ChildTablePolicy
    from app.sampling import build_sample_plan
    from app.traversal import traverse
    req = _sample_request(total=5, seed=2, child_policies=[
        ChildTablePolicy(table="orders", policy="all")])
    plan = build_sample_plan(ws, req)
    result = traverse(ws, req, plan)
    # all items/refunds of the five orders pulled, composite keys kept unique
    item_keys = list(result.records["order_items"].keys())
    assert item_keys and len(item_keys) == len(set(item_keys))
    origins = {r["_meta"]["origin"] for r in result.records["order_items"].values()}
    assert origins == {"child_pull"}


def test_export_succeeds_when_some_subset_tables_are_empty(ws):
    """Regression: a subset where refunds has zero rows must still pass the
    export-time FK re-check (empty subset view, not full-table fallback)."""
    import zipfile
    from io import BytesIO
    from app.export import build_zip
    from app.models import SampleRequest
    from app.sampling import build_sample_plan
    from app.traversal import traverse

    req = SampleRequest(start_table="orders", total=5, seed=42)
    plan = build_sample_plan(ws, req)
    result = traverse(ws, req, plan)
    assert "refunds" not in result.records or len(result.records.get("refunds", {})) == 0
    data = build_zip(ws, result, plan, req.model_dump())
    names = zipfile.ZipFile(BytesIO(data)).namelist()
    assert "orders.csv" in names and "manifest.json" in names
    # a table with no selected rows contributes no CSV
    assert "refunds.csv" not in names


def test_export_blocks_subset_orphan_and_passes_clean_subset(ws, tmp_path, monkeypatch):
    """With orphan source data: a subset containing the dangling row is blocked,
    while a subset avoiding it exports successfully."""
    from app.demo_data import generate
    from app.export import IntegrityError, build_zip
    from app.models import SampleRequest
    from app.sampling import build_sample_plan
    from app.traversal import traverse

    monkeypatch.setenv("SAMPLER_DATA_DIR", str(tmp_path / "data3"))
    from app import workspace as ws_mod
    importlib.reload(ws_mod)
    bad = ws_mod.get_workspace()
    for name, p in generate(Path(tmp_path) / "demo_c", orphans=True).items():
        bad.load_csv(name, str(p))
    bad.set_registry(_re_registry(bad))

    # find a seed whose 5-order sample includes O1001 (the dangling-customer row)
    blocked = False
    for seed in range(50):
        req = SampleRequest(start_table="orders", total=5, seed=seed)
        plan = build_sample_plan(bad, req)
        keys = [k["business_key"][0] for k in plan["selected_keys"]]
        if "O1001" in keys:
            with pytest.raises(IntegrityError) as ei:
                build_zip(bad, traverse(bad, req, plan), plan, req.model_dump())
            fk_names = {v.foreign_key for v in ei.value.violations}
            assert "fk_orders_customer" in fk_names
            blocked = True
            break
    assert blocked, "测试数据中应能找到包含 O1001 的种子"

    # any 5-order sample avoiding O1001, parent completion only -> clean subset
    for seed in range(200):
        req = SampleRequest(start_table="orders", total=5, seed=seed)
        plan = build_sample_plan(bad, req)
        keys = [k["business_key"][0] for k in plan["selected_keys"]]
        if "O1001" not in keys:
            build_zip(bad, traverse(bad, req, plan), plan, req.model_dump())
            return
    pytest.fail("未找到避开孤立行的种子")


def test_orphans_block_export(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLER_DATA_DIR", str(tmp_path / "data2"))
    from app import workspace as ws_mod
    importlib.reload(ws_mod)
    from app.demo_data import generate
    workspace = ws_mod.get_workspace()
    paths = generate(Path(tmp_path) / "demo_bad", orphans=True)
    for name, p in paths.items():
        workspace.load_csv(name, str(p))
    workspace.set_registry(_re_registry(workspace))
    violations = workspace.check_integrity()
    fk_names = {v.foreign_key for v in violations}
    assert "fk_orders_customer" in fk_names
    assert "fk_items_product" in fk_names
    # missing keys are surfaced for the UI
    cust_v = next(v for v in violations if v.foreign_key == "fk_orders_customer")
    assert any(k.get("customer_id") == "C999" for k in cust_v.missing_keys)
    # empty-string -> read_csv_auto treats as NULL, must NOT be a violation
    assert all(k.get("customer_id") not in (None, "") for k in cust_v.missing_keys)
