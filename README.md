# 多表关系抽样调试工具

从业务库里抽一小份数据做调试，但样本仍然保持关系完整：从起点表（如订单）抽样后，
能顺着外键找到客户、订单明细、退款等关联记录。技术栈：**Python + DuckDB + FastAPI + React**。

## 功能与规则对照

| 需求 | 实现位置 |
| --- | --- |
| 上传多表 CSV，页面登记主键（含组合主键）、外键和抽样起点 | `backend/app/main.py`、`frontend/src/components/RegistryStep.tsx` |
| 先从起点表抽样，再递归补齐父记录；子表可选「全部带出 / 不带出」 | `backend/app/traversal.py` |
| 多记录引用同一父记录只保留一份；有环时按 (表名, 主键) 记忆已访问记录 | `traversal.py` 的 `TraversalResult` + 波次遍历 |
| 孤立外键阻止导出，并先给出缺失关系明细 | `workspace.py::check_integrity`、`export.py::build_zip`（409 响应） |
| 每次选一个分组字段，给各组最低配额 + 起点总数；先配额后余量 | `backend/app/sampling.py` |
| 配额之和 > 总数报配置冲突；源数据不够显示还差多少 | `sampling.py` + 前端配额面板 |
| 相同数据/种子/配置得到同一组业务键，调换输入行顺序不影响结果 | `keying.py`：BLAKE2b(seed, 表名, 稳定 JSON 业务键) 作为排序值，不依赖物理行序 |
| 抽样记录与补齐记录分开展示，解释每条入选原因 | `PreviewStep.tsx`，每条记录带 `_meta.origin / reason / depth` |
| 关系图、计划与预览页面 | `RelationGraph.tsx`（React Flow，外键方向分层布局） |
| 下载多表 ZIP 前再次检查外键完整性 | `export.py`，对**导出子集**复检，含 0 行入选表的空子集视图 |

## 目录结构

```
backend/
  app/
    main.py        FastAPI 路由（上传/登记/完整性/计划/执行/导出）
    workspace.py   DuckDB 连接、CSV 入库、键值探测、完整性反连接
    sampling.py    确定性分层抽样（配额 → 全局补足）
    traversal.py   父记录递归补齐、子表带出、环检测、去重、入选原因
    export.py      子集视图、导出前复检、ZIP（每表 CSV + manifest.json）
    keying.py      稳定业务键与 BLAKE2b 排序值
    demo_data.py   内置演示数据（含组合主键、自引用环、孤立外键变体）
  tests/           pytest，11 个用例
frontend/
  src/             React + TypeScript + Vite + @xyflow/react
scripts/           启动/构建脚本
```

## 快速开始

```bash
# 1. 后端（自动创建 venv 并装依赖）
bash scripts/run-backend.sh
# 打开 http://127.0.0.1:8000 —— 后端会直接托管 frontend/dist

# 前端开发模式（热更新，可选）
bash scripts/run-frontend.sh   # http://127.0.0.1:5173，/api 代理到 8000

# 重新构建前端
bash scripts/build-frontend.sh
```

## 使用流程（页面四步）

1. **上传数据**：拖入多个 CSV（文件名即表名，首行表头），或点「载入演示数据」。
   另有「含孤立外键」变体可验证阻断逻辑。
2. **登记关系**：勾选每表主键（可多列组合，后端校验唯一性）；登记外键（两侧列数一致，
   支持自引用）。保存即做全量外键完整性检查，有孤立键时列出每个缺失键。
3. **抽样配置**：选起点表、种子、起点总数；可选一个分组字段并给各组最低配额；
   为需要带出的子表选「全部带出」。配额冲突、组内不足都会在页面提示。
4. **计划与预览**：查看分组达成、补齐波次、每条记录的来源（抽样/父补齐/子带出）与入选原因；
   下载 ZIP（导出前对子集复检，失败则返回 409 和缺失关系，不产生文件）。

## 确定性说明

每条候选记录的排序值 = `BLAKE2b(seed, 表名, JSON(业务主键))` 的十六进制摘要，
选样只依赖数据内容、种子与配置，与 CSV 行顺序、DuckDB 物理存储无关。
测试 `test_row_order_does_not_matter` 反转输入行顺序后验证选中键完全一致。

## 测试

```bash
.venv/bin/python -m pytest backend/tests -q
```

覆盖：确定性、行序无关、配额冲突、先配额后补足、缺口报告、父记录去重、
自引用环终止、组合主键子表带出、孤立外键检测与导出阻断、空子集导出回归。

## ZIP 产物

`{table}.csv`（仅含有入选记录的表）+ `manifest.json`（配置、种子、每表来源计数、
补齐波次、完整性结论）。
