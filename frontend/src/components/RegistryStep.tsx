import { useEffect, useState } from "react";
import { api } from "../api";
import type { Catalog, ForeignKeySpec, RegistryRequest, Violation } from "../types";
import RelationGraph from "./RelationGraph";

interface Props {
  catalog: Catalog;
  onCatalog: (c: Catalog) => void;
  onError: (msg: string) => void;
  onSaved: () => void;
}

export default function RegistryStep({ catalog, onCatalog, onError, onSaved }: Props) {
  const [pkMap, setPkMap] = useState<Record<string, string[]>>({});
  const [fks, setFks] = useState<ForeignKeySpec[]>([]);
  const [violations, setViolations] = useState<Violation[] | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // prefill from previously saved registry, else guess single-column "*_id"
    const initialPk: Record<string, string[]> = {};
    for (const t of catalog.tables) {
      initialPk[t.name] = t.primary_key
        ? [...t.primary_key]
        : t.columns.filter((c) => c.name === `${t.name.replace(/s$/, "")}_id`).map((c) => c.name);
    }
    setPkMap(initialPk);
    setFks(catalog.foreign_keys.length ? catalog.foreign_keys : []);
    setViolations(null);
  }, [catalog]);

  const colName = (table: string) =>
    catalog.tables.find((t) => t.name === table)?.columns.map((c) => c.name) ?? [];

  const togglePk = (table: string, col: string) => {
    const cur = pkMap[table] ?? [];
    const next = cur.includes(col) ? cur.filter((c) => c !== col) : [...cur, col];
    // keep column order as defined in the table
    const ordered = colName(table).filter((c) => next.includes(c));
    setPkMap({ ...pkMap, [table]: ordered });
  };

  const addFk = () => {
    const t = catalog.tables[0]?.name;
    if (!t) return;
    setFks([
      ...fks,
      { name: `fk_${fks.length + 1}`, table: t, columns: [], ref_table: t, ref_columns: [] },
    ]);
  };

  const updateFk = (i: number, patch: Partial<ForeignKeySpec>) => {
    const copy = fks.map((f, idx) => (idx === i ? { ...f, ...patch } : f));
    setFks(copy);
  };

  const removeFk = (i: number) => setFks(fks.filter((_, idx) => idx !== i));

  const save = async () => {
    setSaving(true);
    setViolations(null);
    try {
      const req: RegistryRequest = {
        tables: catalog.tables.map((t) => ({
          name: t.name,
          primary_key: pkMap[t.name] ?? [],
        })),
        foreign_keys: fks,
      };
      const updated = await api.saveRegistry(req);
      onCatalog(updated);
      const integrity = await api.integrity();
      setViolations(integrity.violations);
      if (integrity.ok) onSaved();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const recheck = async () => {
    try {
      const r = await api.integrity();
      setViolations(r.violations);
    } catch (e) {
      onError((e as Error).message);
    }
  };

  return (
    <div>
      <div className="card">
        <h2>② 登记主键（支持组合主键）</h2>
        <p className="hint">
          勾选一列或多列作为主键；后端会用 DuckDB 校验组合键唯一性，重复时拒绝保存。
        </p>
        <div className="scrollbox">
          <table className="grid">
            <thead>
              <tr>
                <th>表</th>
                <th>选择主键列（多选 = 组合主键）</th>
                <th>当前主键</th>
              </tr>
            </thead>
            <tbody>
              {catalog.tables.map((t) => (
                <tr key={t.name}>
                  <td className="mono">{t.name}</td>
                  <td>
                    {t.columns.map((c) => (
                      <label key={c.name} style={{ marginRight: 12, whiteSpace: "nowrap" }}>
                        <input
                          type="checkbox"
                          checked={(pkMap[t.name] ?? []).includes(c.name)}
                          onChange={() => togglePk(t.name, c.name)}
                          style={{ marginRight: 4 }}
                        />
                        <span className="mono">{c.name}</span>
                      </label>
                    ))}
                  </td>
                  <td className="mono">{(pkMap[t.name] ?? []).join(" + ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>登记外键关系</h2>
        <p className="hint">
          外键从子表指向父表（如 order_items.order_id → orders.order_id），两侧列数必须一致；
          自引用（如 employees.manager_id → employees.employee_id）也支持，遍历时按表名+主键去重防环。
        </p>
        {fks.map((fk, i) => (
          <div className="fk-row" key={i}>
            <input
              placeholder="外键名称"
              value={fk.name ?? ""}
              onChange={(e) => updateFk(i, { name: e.target.value })}
            />
            <select
              value={fk.table}
              onChange={(e) => updateFk(i, { table: e.target.value, columns: [] })}
            >
              {catalog.tables.map((t) => (
                <option key={t.name}>{t.name}</option>
              ))}
            </select>
            <select
              value={fk.ref_table}
              onChange={(e) => updateFk(i, { ref_table: e.target.value, ref_columns: [] })}
            >
              {catalog.tables.map((t) => (
                <option key={t.name}>{t.name}</option>
              ))}
            </select>
            <button className="danger" onClick={() => removeFk(i)}>
              删
            </button>
            <span />
            <select
              multiple
              size={Math.min(4, Math.max(2, colName(fk.table).length))}
              onChange={(e) =>
                updateFk(i, {
                  columns: Array.from(e.target.selectedOptions).map((o) => o.value),
                })
              }
            >
              {colName(fk.table).map((c) => (
                <option key={c} value={c} selected={fk.columns.includes(c)}>
                  {c}
                </option>
              ))}
            </select>
            <select
              multiple
              size={Math.min(4, Math.max(2, colName(fk.ref_table).length))}
              onChange={(e) =>
                updateFk(i, {
                  ref_columns: Array.from(e.target.selectedOptions).map((o) => o.value),
                })
              }
            >
              {colName(fk.ref_table).map((c) => (
                <option key={c} value={c} selected={fk.ref_columns.includes(c)}>
                  {c}
                </option>
              ))}
            </select>
            <div className="pill-count mono">
              {fk.columns.join(",")} → {fk.ref_columns.join(",")}
            </div>
          </div>
        ))}
        <div className="row">
          <button className="secondary" onClick={addFk}>
            + 添加外键
          </button>
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button disabled={saving} onClick={() => void save()}>
            {saving ? "校验中…" : "保存登记并检查外键完整性"}
          </button>
          {catalog.registered && (
            <button className="ghost" onClick={() => void recheck()}>
              重新检查完整性
            </button>
          )}
        </div>
      </div>

      {violations !== null &&
        (violations.length === 0 ? (
          <div className="alert ok">✓ 全部外键完整，未发现孤立外键，可以进入抽样配置。</div>
        ) : (
          <div className="alert error">
            <strong>检测到 {violations.reduce((s, v) => s + v.count, 0)} 个孤立外键，存在缺失关系：</strong>
            {violations.map((v) => (
              <div key={v.foreign_key} style={{ marginTop: 8 }}>
                <div>
                  <code>{v.foreign_key}</code>：{v.source_table}.({v.source_columns.join(", ")})
                  在 {v.ref_table}.({v.ref_columns.join(", ")}) 中找不到（共 {v.count} 个缺失键
                  {v.note ? `，${v.note}` : ""}）
                </div>
                <div className="scrollbox mono small" style={{ marginTop: 4 }}>
                  {v.missing_keys.map((k, i) => (
                    <div key={i}>{JSON.stringify(k)}</div>
                  ))}
                </div>
              </div>
            ))}
            <div className="small" style={{ marginTop: 6 }}>
              请先在源数据中补齐或删除这些引用；导出前系统还会对抽样子集再检查一次。
            </div>
          </div>
        ))}

      <div className="card">
        <h2>关系图</h2>
        <RelationGraph catalog={catalog} />
      </div>
    </div>
  );
}
