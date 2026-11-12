export interface ColumnInfo {
  name: string;
  type: string;
}

export interface TableInfo {
  name: string;
  columns: ColumnInfo[];
  row_count: number;
  primary_key?: string[] | null;
}

export interface ForeignKeySpec {
  name?: string;
  table: string;
  columns: string[];
  ref_table: string;
  ref_columns: string[];
}

export interface Catalog {
  tables: TableInfo[];
  foreign_keys: ForeignKeySpec[];
  registered: boolean;
}

export interface TableSpec {
  name: string;
  primary_key: string[];
}

export interface RegistryRequest {
  tables: TableSpec[];
  foreign_keys: ForeignKeySpec[];
}

export interface Violation {
  foreign_key: string;
  source_table: string;
  source_columns: string[];
  ref_table: string;
  ref_columns: string[];
  missing_keys: Record<string, unknown>[];
  count: number;
  note?: string | null;
}

export type ChildPolicy = "none" | "all";

export interface SampleRequest {
  start_table: string;
  total: number;
  seed: number;
  group_field?: string | null;
  quotas: Record<string, number>;
  child_policies: { table: string; policy: ChildPolicy }[];
}

export interface SelectedKey {
  business_key: unknown[];
  business_key_json: string;
  group: unknown;
  sort_value: string;
  phase: "quota" | "fill";
  reason: string;
}

export interface GroupSummary {
  group: string | null;
  total_rows: number;
  quota: number;
  selected: number;
  deficit: number;
}

export interface Plan {
  start_table: string;
  primary_key: string[];
  group_field: string | null;
  seed: number;
  requested_total: number;
  selected_count: number;
  source_row_count: number;
  deficit: number;
  deficit_message: string | null;
  unknown_groups: string[];
  groups: GroupSummary[];
  selected_keys: SelectedKey[];
}

export interface RowMeta {
  business_key: unknown[];
  business_key_json: string;
  origin: "sampled" | "parent_completion" | "child_pull";
  reason: string;
  depth: number;
}

export type RowRecord = Record<string, unknown> & { _meta: RowMeta };

export interface PreviewTable {
  table: string;
  primary_key: string[];
  total: number;
  sampled: number;
  parent_completion: number;
  child_pull: number;
  capped: boolean;
  rows: RowRecord[];
}

export interface Wave {
  wave: number;
  added: Record<string, number>;
  note: string;
}

export interface BackEdge {
  from: string;
  to: string;
  note?: string;
}

export interface RunResponse {
  plan: Plan;
  preview: {
    tables: PreviewTable[];
    waves: Wave[];
    back_edges: BackEdge[];
  };
  integrity_warnings: Violation[];
}

export interface GroupValue {
  group: string | null;
  count: number;
}
