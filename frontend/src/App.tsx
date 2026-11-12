import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Catalog, RunResponse, SampleRequest } from "./types";
import UploadStep from "./components/UploadStep";
import RegistryStep from "./components/RegistryStep";
import SampleStep from "./components/SampleStep";
import PreviewStep from "./components/PreviewStep";

const STEPS = ["上传数据", "登记关系", "抽样配置", "计划与预览"];

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [lastReq, setLastReq] = useState<SampleRequest | null>(null);
  const [lastResult, setLastResult] = useState<RunResponse | null>(null);

  useEffect(() => {
    api
      .catalog()
      .then(setCatalog)
      .catch((e) => setError((e as Error).message));
  }, []);

  const onError = useCallback((msg: string) => setError(msg), []);

  const hasTables = !!catalog && catalog.tables.length > 0;
  const registered = !!catalog?.registered;
  const hasResult = !!lastResult;

  const canGo = [true, hasTables, registered, hasResult];

  return (
    <div className="app">
      <header className="app-header">
        <h1>多表关系抽样调试工具</h1>
        <span className="sub">
          Python · DuckDB · FastAPI · React — 小样本也能顺着订单找到客户、明细与退款
        </span>
      </header>

      <nav className="stepper">
        {STEPS.map((label, i) => (
          <div
            key={label}
            className={`step-chip ${i === step ? "active" : ""} ${
              i < step || (i !== step && canGo[i]) ? "done" : ""
            }`}
            onClick={() => canGo[i] && setStep(i)}
            style={{ cursor: canGo[i] ? "pointer" : "not-allowed" }}
          >
            <span className="n">{i + 1}</span>
            {label}
          </div>
        ))}
      </nav>

      {error && (
        <div className="alert error" onClick={() => setError(null)}>
          {error}
          <span className="small" style={{ marginLeft: 10 }}>
            （点击关闭）
          </span>
        </div>
      )}

      {!catalog ? (
        <div className="card hint">正在连接后端…</div>
      ) : (
        <>
          {step === 0 && (
            <UploadStep catalog={catalog} onCatalog={setCatalog} onError={onError} />
          )}
          {step === 1 && hasTables && (
            <RegistryStep
              catalog={catalog}
              onCatalog={setCatalog}
              onError={onError}
              onSaved={() => setStep(2)}
            />
          )}
          {step === 2 && registered && (
            <SampleStep
              catalog={catalog}
              onError={onError}
              onResult={(req, res) => {
                setLastReq(req);
                setLastResult(res);
                setStep(3);
              }}
            />
          )}
          {step === 3 && hasResult && lastReq && (
            <PreviewStep req={lastReq} result={lastResult} onError={onError} />
          )}
        </>
      )}

      <div className="row" style={{ marginTop: 18 }}>
        {step > 0 && (
          <button className="ghost" onClick={() => setStep(step - 1)}>
            ← 上一步
          </button>
        )}
        <div className="spacer" />
        {step < 3 && canGo[step + 1] && (
          <button className="secondary" onClick={() => setStep(step + 1)}>
            下一步 →
          </button>
        )}
      </div>
    </div>
  );
}
