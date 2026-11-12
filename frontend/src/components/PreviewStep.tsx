import { useState } from "react";
import { api } from "../api";
import type { RunResponse, SampleRequest, Violation } from "../types";

interface Props {
  req: SampleRequest;
  result: RunResponse;
  onError: (msg: string) => void;
}

const ORIGIN_LABEL: Record<string, string> = {
  sampled: "抽样记录",
  parent_completion: "父记录补齐",
  child_pull: "子表带出",
};

export default function PreviewStep({ req, result, onError }: Props) {
  const { plan, preview, integrity_warnings } = result;
  const [tab, setTab] = useState<string>("__plan__");
  const [exportViolations, setExportViolations] = useState<Violation[] | null>(null);
  const [exporting, setExporting] = useState(false);

  const doExport = async () => {
    setExporting(true);
    setExportViolations(null);
    try {
      const r = await api.export(req);
      if (r.ok) {
        const url = URL.createObjectURL(r.blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "sample_export.zip";
        a.click();
        URL.revokeObjectURL(url);
      } else {
        setExportViolations(r.violations);
      }
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div>
      <div className="card">
        <h2>④ 抽样计划与补齐预览</h2>
        <div className="kv">
          <span className="k">起点表 / 主键</span>
          <span className="mono">
            {plan.start_table}（{plan.primary_key.join(" + ")}）
          </span>
          <span className="k">种子</span>
          <span className="mono">{plan.seed}</span>
          <span className="k">请求总数 / 实际入选</span>
          <span>
            {plan.requested_total} / <strong>{plan.selected_count}</strong>
            （源表共 {plan.source_row_count} 行）
          </span>
          <span className="k">分组字段</span>
          <span className="mono">{plan.group_field ?? "未分组"}</span>
        </div>

        {plan.deficit > 0 && (
          <div className="alert warn" style={{ marginTop: 12 }}>
            {plan.deficit_message}
          </div>
        )}
        {plan.unknown_groups.length > 0 && (
          <div className="alert warn" style={{ marginTop: 12 }}>
            配额中的分组值在源数据中不存在：
            {plan.unknown_groups.join("、")}
          </div>
        )}
        {integrity_warnings.length > 0 && (
          <div className="alert error" style={{ marginTop: 12 }}>
            源数据存在 {integrity_warnings.length} 组孤立外键，关联补齐可能不完整；
            导出时会对抽样子集再次检查并阻断不合规导出。
          </div>
        )}

        <h3>分组配额达成情况</h3>
        <table className="grid" style={{ maxHeight: 220 }}>
          <thead>
            <tr>
              <th>分组</th>
              <th>组内行数</th>
              <th>最低配额</th>
              <th>实际入选</th>
              <th>缺口</th>
            </tr>
          </thead>
          <tbody>
            {plan.groups.map((g) => (
              <tr key={String(g.group)}>
                <td className="mono">{g.group === null ? "␀ NULL" : String(g.group)}</td>
                <td>{g.total_rows}</td>
                <td>{g.quota}</td>
                <td>{g.selected}</td>
                <td>
                  {g.deficit > 0 ? (
                    <span className="badge danger">还差 {g.deficit}</span>
                  ) : (
                    <span className="badge ok">满足</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3>补齐波次（每轮沿外键扩展一层）</h3>
        <div className="hint">
          {preview.waves.map((w) => (
            <div key={w.wave}>
              第 {w.wave} 波 · {w.note}：
              {Object.entries(w.added).map(([t, n]) => (
                <span key={t} className="mono" style={{ marginLeft: 8 }}>
                  {t} +{n}
                </span>
              ))}
            </div>
          ))}
        </div>
        {preview.back_edges.length > 0 && (
          <p className="hint small">
            检测到 {preview.back_edges.length} 次重复访问（环或共享父记录），已按
            (表名, 主键) 去重，每个业务记录只保留一份。
          </p>
        )}

        <div className="row" style={{ marginTop: 14 }}>
          <button disabled={exporting} onClick={() => void doExport()}>
            {exporting ? "复检并打包中…" : "下载多表 ZIP（导出前再次复检外键）"}
          </button>
          <span className="hint small">
            ZIP 内含每张表的 CSV 与 manifest.json（配置、种子、每表来源统计、完整性结论）
          </span>
        </div>

        {exportViolations && (
          <div className="alert error" style={{ marginTop: 12 }}>
            <strong>导出已阻止：抽样子集仍有缺失关系</strong>
            {exportViolations.map((v) => (
              <div key={v.foreign_key} style={{ marginTop: 6 }}>
                <code>{v.foreign_key}</code>：{v.source_table}
                （{v.source_columns.join(", ")}）→ {v.ref_table}
                （{v.ref_columns.join(", ")}），缺失 {v.count} 个键：
                <div className="mono small">
                  {v.missing_keys.slice(0, 10).map((k, i) => (
                    <div key={i}>{JSON.stringify(k)}</div>
                  ))}
                  {v.missing_keys.length > 10 && <div>…（其余见 API 返回）</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h2>记录级预览（抽样记录与补齐记录分开展示）</h2>
        <div className="legend">
          <span>
            <i style={{ background: "var(--sampled)" }} />
            抽样记录（起点表入选）
          </span>
          <span>
            <i style={{ background: "var(--parent)" }} />
            父记录补齐（沿外键向上递归）
          </span>
          <span>
            <i style={{ background: "var(--child)" }} />
            子表带出（策略=全部带出）
          </span>
        </div>
        <div className="tabs">
          <div className={`tab ${tab === "__plan__" ? "active" : ""}`} onClick={() => setTab("__plan__")}>
            起点入选明细（{plan.selected_count}）
          </div>
          {preview.tables.map((t) => (
            <div
              key={t.table}
              className={`tab ${tab === t.table ? "active" : ""}`}
              onClick={() => setTab(t.table)}
            >
              {t.table}（{t.total}）
            </div>
          ))}
        </div>

        {tab === "__plan__" ? (
          <table className="grid">
            <thead>
              <tr>
                <th>业务主键</th>
                {plan.group_field && <th>分组</th>}
                <th>入选阶段</th>
                <th>排序值（种子+稳定业务键的 BLAKE2b）</th>
                <th>入选原因</th>
              </tr>
            </thead>
            <tbody>
              {plan.selected_keys.map((k) => (
                <tr key={k.business_key_json}>
                  <td className="mono">{k.business_key_json}</td>
                  {plan.group_field && <td className="mono">{String(k.group)}</td>}
                  <td>
                    <span className={`badge ${k.phase}`}>
                      {k.phase === "quota" ? "配额入选" : "余量补足"}
                    </span>
                  </td>
                  <td className="mono small">{k.sort_value}</td>
                  <td className="meta-reason">{k.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          (() => {
            const t = preview.tables.find((x) => x.table === tab);
            if (!t) return null;
            const dataCols = Object.keys(t.rows[0] ?? {}).filter((c) => c !== "_meta");
            return (
              <div>
                <div className="table-meta">
                  <span className="name mono">{t.table}</span>
                  <span className="badge sampled">抽样 {t.sampled}</span>
                  <span className="badge parent_completion">父补齐 {t.parent_completion}</span>
                  <span className="badge child_pull">子带出 {t.child_pull}</span>
                  <span className="pill-count">
                    主键：{t.primary_key.join(" + ")}
                  </span>
                </div>
                {t.capped && (
                  <div className="alert warn">
                    预览仅展示前 {t.rows.length} 行，完整数据以导出的 CSV 为准。
                  </div>
                )}
                <table className="grid">
                  <thead>
                    <tr>
                      <th>来源</th>
                      <th>深度</th>
                      {dataCols.map((c) => (
                        <th key={c} className="mono">
                          {c}
                        </th>
                      ))}
                      <th>入选原因</th>
                    </tr>
                  </thead>
                  <tbody>
                    {t.rows.map((row, i) => (
                      <tr key={`${row._meta.business_key_json}-${i}`}>
                        <td>
                          <span className={`badge ${row._meta.origin}`}>
                            {ORIGIN_LABEL[row._meta.origin]}
                          </span>
                        </td>
                        <td>{row._meta.depth}</td>
                        {dataCols.map((c) => (
                          <td key={c} className="mono">
                            {row[c] === null ? "␀" : String(row[c])}
                          </td>
                        ))}
                        <td className="meta-reason">{row._meta.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })()
        )}
      </div>
    </div>
  );
}
