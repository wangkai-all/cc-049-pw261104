import { useEffect, useState } from "react";
import { api } from "../api";
import type {
  Catalog,
  ChildPolicy,
  GroupValue,
  RunResponse,
  SampleRequest,
} from "../types";
import RelationGraph from "./RelationGraph";

interface Props {
  catalog: Catalog;
  onError: (msg: string) => void;
  onResult: (req: SampleRequest, res: RunResponse) => void;
}

export default function SampleStep({ catalog, onError, onResult }: Props) {
  const firstTable = catalog.tables[0]?.name ?? "";
  const [startTable, setStartTable] = useState(firstTable);
  const [seed, setSeed] = useState(42);
  const [total, setTotal] = useState(10);
  const [groupField, setGroupField] = useState<string>("");
  const [groupValues, setGroupValues] = useState<GroupValue[]>([]);
  const [quotas, setQuotas] = useState<Record<string, number>>({});
  const [childPolicies, setChildPolicies] = useState<Record<string, ChildPolicy>>({});
  const [running, setRunning] = useState(false);

  useEffect(() => {
    setStartTable(firstTable);
  }, [firstTable]);

  useEffect(() => {
    if (!groupField || !startTable) {
      setGroupValues([]);
      setQuotas({});
      return;
    }
    let cancelled = false;
    api
      .groups(startTable, groupField)
      .then((vals) => {
        if (cancelled) return;
        setGroupValues(vals);
        setQuotas((old) => {
          const next: Record<string, number> = {};
          for (const v of vals) {
            const key = v.group === null ? "" : String(v.group);
            next[key] = old[key] ?? 0;
          }
          return next;
        });
      })
      .catch((e) => onError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [groupField, startTable, onError]);

  const startColumns =
    catalog.tables.find((t) => t.name === startTable)?.columns.map((c) => c.name) ?? [];

  const quotaSum = Object.values(quotas).reduce((s, v) => s + (Number(v) || 0), 0);
  const conflict = quotaSum > total;

  const run = async () => {
    setRunning(true);
    try {
      const req: SampleRequest = {
        start_table: startTable,
        total,
        seed,
        group_field: groupField || null,
        quotas: groupField
          ? Object.fromEntries(
              Object.entries(quotas)
                .filter(([, v]) => Number(v) > 0)
                .map(([k, v]) => [k, Number(v)])
            )
          : {},
        child_policies: Object.entries(childPolicies)
          .filter(([, p]) => p === "all")
          .map(([table, policy]) => ({ table, policy })),
      };
      const res = await api.run(req);
      onResult(req, res);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  // tables that have an outgoing FK (i.e. can pull children)
  const childCapable = new Set(
    catalog.foreign_keys.map((fk) => fk.ref_table)
  );

  return (
    <div>
      <div className="card">
        <h2>③ 抽样配置</h2>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label className="field">
            起点表（抽样起点）
            <select value={startTable} onChange={(e) => setStartTable(e.target.value)}>
              {catalog.tables.map((t) => (
                <option key={t.name}>{t.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            随机种子（同种子 + 同数据 = 同样本）
            <input
              type="number"
              value={seed}
              min={0}
              onChange={(e) => setSeed(Number(e.target.value))}
            />
          </label>
          <label className="field">
            起点总数
            <input
              type="number"
              value={total}
              min={1}
              onChange={(e) => setTotal(Number(e.target.value))}
            />
          </label>
          <label className="field">
            分组字段（可选，如 region / status）
            <select value={groupField} onChange={(e) => setGroupField(e.target.value)}>
              <option value="">不分组</option>
              {startColumns.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
        </div>

        {groupField && (
          <>
            <h3>各组最低配额：先满足配额，再从全局剩余记录补足总数</h3>
            <div className="quota-row" style={{ color: "var(--muted)" }}>
              <span>分组值（组内行数）</span>
              <span>最低配额</span>
              <span>配额后余量</span>
              <span>状态</span>
            </div>
            {groupValues.map((v) => {
              const key = v.group === null ? "" : String(v.group);
              const q = quotas[key] ?? 0;
              const over = q > v.count;
              return (
                <div className="quota-row" key={key}>
                  <span className="mono">
                    {v.group === null ? "␀ NULL" : v.group}
                    <span className="pill-count">（{v.count} 行）</span>
                  </span>
                  <input
                    type="number"
                    min={0}
                    value={q}
                    onChange={(e) => setQuotas({ ...quotas, [key]: Number(e.target.value) })}
                  />
                  <span className="pill-count">{Math.max(0, v.count - q)}</span>
                  <span>
                    {over ? (
                      <span className="badge danger">配额超过组内行数</span>
                    ) : (
                      <span className="badge ok">可行</span>
                    )}
                  </span>
                </div>
              );
            })}
            <div className="row" style={{ marginTop: 8 }}>
              <span className="hint">
                配额之和：<strong className={conflict ? "" : "muted"}>{quotaSum}</strong> / 总数{" "}
                {total}
              </span>
              {conflict && (
                <span className="badge danger">
                  配置冲突：配额之和 {quotaSum} 超过起点总数 {total}
                </span>
              )}
            </div>
          </>
        )}

        <h3>子表带出策略（父记录始终自动递归补齐）</h3>
        <p className="hint">
          「不带出」= 仅保证从起点沿外键向上找齐父记录；「全部带出」= 把引用该表的子表记录也一并带出。
          多个记录引用同一父记录只保留一份；自引用/环按 (表名, 主键) 记忆已访问记录后终止。
        </p>
        <div className="row">
          {catalog.tables
            .filter((t) => childCapable.has(t.name))
            .map((t) => (
              <label key={t.name} className="field" style={{ minWidth: 220 }}>
                表 <span className="mono">{t.name}</span> 的子表
                <select
                  value={childPolicies[t.name] ?? "none"}
                  onChange={(e) =>
                    setChildPolicies({
                      ...childPolicies,
                      [t.name]: e.target.value as ChildPolicy,
                    })
                  }
                >
                  <option value="none">不带出</option>
                  <option value="all">全部带出</option>
                </select>
              </label>
            ))}
        </div>

        <div className="row" style={{ marginTop: 16 }}>
          <button disabled={running || conflict || total < 1} onClick={() => void run()}>
            {running ? "计算中…" : "生成抽样计划并关联补齐"}
          </button>
          {conflict && <span className="toast-error">请先解决配额冲突</span>}
        </div>
      </div>

      <div className="card">
        <h2>关系图（高亮起点表）</h2>
        <RelationGraph catalog={catalog} startTable={startTable} small />
      </div>
    </div>
  );
}
