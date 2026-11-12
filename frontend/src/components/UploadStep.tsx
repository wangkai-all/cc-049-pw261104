import { useRef, useState } from "react";
import { api } from "../api";
import type { Catalog } from "../types";

interface Props {
  catalog: Catalog | null;
  onCatalog: (c: Catalog) => void;
  onError: (msg: string) => void;
}

export default function UploadStep({ catalog, onCatalog, onError }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);

  const doUpload = async (files: FileList | File[]) => {
    if (!files.length) return;
    setBusy(true);
    try {
      onCatalog(await api.upload(files));
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const demo = async (orphans: boolean) => {
    setBusy(true);
    try {
      onCatalog(await api.loadDemo(orphans));
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!window.confirm("确认清空所有已上传的表与登记信息？")) return;
    await api.reset();
    onCatalog(await api.catalog());
  };

  return (
    <div className="card">
      <h2>① 上传业务表 CSV</h2>
      <p className="hint">
        每个 CSV 文件名即表名（如 <code>orders.csv</code> → 表 orders），首行须为表头。
        支持一次选择多个文件；表名仅允许字母、数字、下划线。
      </p>
      <div
        className={`dropzone ${drag ? "drag" : ""}`}
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          void doUpload(e.dataTransfer.files);
        }}
      >
        {busy ? "正在解析…" : "点击选择，或把多个 CSV 拖拽到这里"}
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          multiple
          hidden
          onChange={(e) => e.target.files && void doUpload(e.target.files)}
        />
      </div>

      <h3>没有数据？使用内置演示数据</h3>
      <div className="row">
        <button className="secondary" disabled={busy} onClick={() => void demo(false)}>
          载入干净演示数据（6 张表）
        </button>
        <button className="ghost" disabled={busy} onClick={() => void demo(true)}>
          载入含孤立外键的演示数据（用于验证阻断）
        </button>
        {catalog && catalog.tables.length > 0 && (
          <button className="danger" onClick={() => void reset()}>
            清空重置
          </button>
        )}
      </div>
      <p className="hint small" style={{ marginTop: 8 }}>
        演示库：customers / employees（经理自引用，含环）/ products / orders / order_items（组合主键）/
        refunds（组合主键），订单可顺藤摸到客户、明细与退款。
      </p>

      {catalog && catalog.tables.length > 0 && (
        <>
          <h3>已入库的表（{catalog.tables.length}）</h3>
          <div className="scrollbox">
            <table className="grid">
              <thead>
                <tr>
                  <th>表名</th>
                  <th>行数</th>
                  <th>列（DuckDB 类型）</th>
                  <th>已登记主键</th>
                </tr>
              </thead>
              <tbody>
                {catalog.tables.map((t) => (
                  <tr key={t.name}>
                    <td className="mono">{t.name}</td>
                    <td>{t.row_count}</td>
                    <td className="mono muted">
                      {t.columns.map((c) => `${c.name}:${c.type}`).join("，")}
                    </td>
                    <td>{t.primary_key?.join(" + ") ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
