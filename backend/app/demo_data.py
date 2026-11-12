"""Deterministic demo dataset: customers / employees / products / orders /
order_items / refunds, with composite PKs, a self-referencing employee cycle
and an optional orphan-FK variant.

Writes CSVs into a fresh empty directory and returns the path mapping. The
generator is pure standard library and deterministic.
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

TABLES = ["customers", "employees", "products", "orders", "order_items", "refunds"]

REGIONS = ["华东", "华南", "华北", "西南"]
STATUSES = ["paid", "shipped", "cancelled", "refunded"]
CATEGORIES = ["电子", "家居", "图书", "户外"]


def generate(out_dir: Path, *, orphans: bool = False) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(20261113)
    paths: dict[str, Path] = {}

    def write(name: str, header: list[str], rows: list[tuple]) -> None:
        p = out_dir / f"{name}.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        paths[name] = p

    # customers ------------------------------------------------------------
    customers = [
        (f"C{idx:03d}", f"客户{idx:02d}", REGIONS[idx % 4], f"city-{idx % 6}")
        for idx in range(1, 13)
    ]
    write("customers", ["customer_id", "name", "region", "city"], customers)

    # employees with a manager self-reference (E1<->E2 closes a cycle) ------
    employees = [
        ("E1", "总监甲", "E2"),
        ("E2", "总监乙", "E1"),
        ("E3", "经理丙", "E1"),
        ("E4", "经理丁", "E2"),
        ("E5", "销售戊", "E3"),
        ("E6", "销售己", "E4"),
    ]
    write("employees", ["employee_id", "name", "manager_id"], employees)

    # products --------------------------------------------------------------
    products = [
        (f"P{idx:03d}", f"商品{idx:02d}", CATEGORIES[idx % 4], 10 * idx + 5)
        for idx in range(1, 9)
    ]
    write("products", ["product_id", "name", "category", "price"], products)

    # orders ----------------------------------------------------------------
    orders: list[tuple] = []
    for oid in range(1001, 1031):
        customer = f"C{(oid % 12) + 1:03d}"
        employee = f"E{(oid % 6) + 1}"
        orders.append(
            (
                f"O{oid}",
                customer,
                employee,
                REGIONS[oid % 4],
                STATUSES[oid % 4],
                f"2026-10-{oid % 28 + 1:02d}",
                rnd.randint(1, 5) * 100,
            )
        )
    if orphans:
        # dangling customer reference; NULL on another row is allowed
        orders[0] = (orders[0][0], "C999", orders[0][2], orders[0][3],
                     orders[0][4], orders[0][5], orders[0][6])
        orders[1] = (orders[1][0], "", orders[1][2], orders[1][3],
                     orders[1][4], orders[1][5], orders[1][6])
    write(
        "orders",
        ["order_id", "customer_id", "employee_id", "region", "status",
         "order_date", "amount"],
        orders,
    )

    # order_items: composite PK (order_id, line_no) -------------------------
    items: list[tuple] = []
    for oid in range(1001, 1031):
        for line in range(1, rnd.randint(2, 4) + 1):
            product = f"P{((oid + line) % 8) + 1:03d}"
            items.append((f"O{oid}", line, product, rnd.randint(1, 3),
                          rnd.randint(10, 200)))
    if orphans:
        items.append(("O1001", 9, "P999", 1, 50))  # dangling product reference
    write(
        "order_items",
        ["order_id", "line_no", "product_id", "quantity", "unit_price"],
        items,
    )

    # refunds: composite PK (order_id, refund_seq) --------------------------
    refunds: list[tuple] = []
    seq_per_order: dict[str, int] = {}
    for oid in range(1001, 1031):
        if oid % 4 == 0:  # refunded orders
            for k in range(1, rnd.randint(1, 2) + 1):
                seq_per_order[f"O{oid}"] = k
                refunds.append((f"O{oid}", k, f"2026-11-{k:02d}",
                                rnd.randint(20, 150), "质量问题" if k == 1 else "部分退款"))
    write(
        "refunds",
        ["order_id", "refund_seq", "refund_date", "amount", "reason"],
        refunds,
    )
    return paths
