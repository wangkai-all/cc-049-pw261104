import type {
  Catalog,
  RegistryRequest,
  RunResponse,
  SampleRequest,
  Violation,
  GroupValue,
} from "./types";

async function handle<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = `请求失败 (${resp.status})`;
    try {
      const body = await resp.json();
      detail = body.detail || body.message || JSON.stringify(body);
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  catalog: () => fetch("/api/catalog").then((r) => handle<Catalog>(r)),

  upload: (files: FileList | File[]) => {
    const fd = new FormData();
    for (const f of Array.from(files)) fd.append("files", f);
    return fetch("/api/tables/upload", { method: "POST", body: fd }).then(
      (r) => handle<Catalog>(r)
    );
  },

  loadDemo: (orphans: boolean) =>
    fetch(`/api/demo?orphans=${orphans}`, { method: "POST" }).then((r) =>
      handle<Catalog>(r)
    ),

  reset: () => fetch("/api/reset", { method: "POST" }).then((r) => handle(r)),

  saveRegistry: (req: RegistryRequest) =>
    fetch("/api/registry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }).then((r) => handle<Catalog>(r)),

  groups: (table: string, field: string) =>
    fetch(
      `/api/groups?table=${encodeURIComponent(table)}&field=${encodeURIComponent(field)}`
    ).then((r) => handle<GroupValue[]>(r)),

  integrity: () =>
    fetch("/api/integrity", { method: "POST" }).then((r) =>
      handle<{ ok: boolean; violations: Violation[] }>(r)
    ),

  run: (req: SampleRequest) =>
    fetch("/api/sample/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }).then((r) => handle<RunResponse>(r)),

  export: async (
    req: SampleRequest
  ): Promise<{ ok: true; blob: Blob } | { ok: false; violations: Violation[]; message: string }> => {
    const resp = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (resp.ok) return { ok: true, blob: await resp.blob() };
    const body = await resp.json();
    return {
      ok: false,
      violations: body.violations ?? [],
      message: body.message ?? "导出被阻止",
    };
  },
};
