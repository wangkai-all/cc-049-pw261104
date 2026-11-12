import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MarkerType,
  Handle,
  Position,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Catalog, ForeignKeySpec } from "../types";

interface Props {
  catalog: Catalog;
  startTable?: string | null;
  small?: boolean;
}

type TableNodeData = Record<string, unknown> & {
  name: string;
  rowCount: number;
  pk: string[];
  fkCols: Set<string>;
  isStart: boolean;
};

function TableNode({ data }: { data: TableNodeData }) {
  return (
    <div className={`react-flow__node-tableNode ${data.isStart ? "start" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="tn-header">
        <span>{data.name}</span>
        <span className="tn-count">{data.rowCount} 行</span>
      </div>
      <div className="tn-cols">
        {data.pk.map((c) => (
          <div key={c} className="pk mono">🔑 {c}</div>
        ))}
        {[...data.fkCols].map((c) => (
          <div key={c} className="fk mono">↗ {c}</div>
        ))}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes = { tableNode: TableNode };

/** Assign each table an integer "level": start=0, parents positive, children negative. */
function computeLevels(tables: string[], fks: ForeignKeySpec[], start: string): Map<string, number> {
  const level = new Map<string, number>(tables.map((t) => [t, 0]));
  if (start) level.set(start, 0);
  // iterative relaxation; graph is tiny
  for (let iter = 0; iter < tables.length * 2 + 4; iter++) {
    let changed = false;
    for (const fk of fks) {
      const child = fk.table;
      const parent = fk.ref_table;
      const wantParent = level.get(child)! + 1;
      if (wantParent > level.get(parent)!) {
        level.set(parent, wantParent);
        changed = true;
      }
      const wantChild = level.get(parent)! - 1;
      if (wantChild < level.get(child)!) {
        level.set(child, wantChild);
        changed = true;
      }
    }
    if (!changed) break;
  }
  // normalize so minimum is 0
  const min = Math.min(...level.values());
  for (const [k, v] of level) level.set(k, v - min);
  return level;
}

export default function RelationGraph({ catalog, startTable, small }: Props) {
  const { nodes, edges } = useMemo(() => {
    const tables = catalog.tables;
    const fks = catalog.foreign_keys;
    const start = startTable ?? tables[0]?.name ?? "";
    const levels = computeLevels(
      tables.map((t) => t.name),
      fks,
      start
    );

    const columns = new Map<number, string[]>();
    for (const t of tables) {
      const lv = levels.get(t.name) ?? 0;
      if (!columns.has(lv)) columns.set(lv, []);
      columns.get(lv)!.push(t.name);
    }

    const positions = new Map<string, { x: number; y: number }>();
    const COL_W = 300;
    const ROW_H = 190;
    for (const [lv, names] of columns) {
      names.sort();
      names.forEach((name, i) => {
        positions.set(name, { x: lv * COL_W, y: i * ROW_H });
      });
    }

    const fkColsByTable = new Map<string, Set<string>>();
    for (const fk of fks) {
      if (!fkColsByTable.has(fk.table)) fkColsByTable.set(fk.table, new Set());
      fk.columns.forEach((c) => fkColsByTable.get(fk.table)!.add(c));
    }

    const nodes: Node<TableNodeData>[] = tables.map((t) => ({
      id: t.name,
      type: "tableNode",
      position: positions.get(t.name) ?? { x: 0, y: 0 },
      data: {
        name: t.name,
        rowCount: t.row_count,
        pk: t.primary_key ?? [],
        fkCols: fkColsByTable.get(t.name) ?? new Set(),
        isStart: t.name === start,
      },
    }));

    const edges: Edge[] = fks.map((fk, i) => ({
      id: `e-${i}-${fk.name ?? fk.table}`,
      source: fk.table,
      target: fk.ref_table,
      label: `${fk.name ?? "fk"} (${fk.columns.join(", ")})`,
      labelStyle: { fill: "#93a0b8", fontSize: 11 },
      style: { stroke: "#5b8def", strokeWidth: 1.4 },
      markerEnd: { type: MarkerType.ArrowClosed, color: "#5b8def" },
      animated: fk.table === fk.ref_table,
    }));
    return { nodes, edges };
  }, [catalog, startTable]);

  return (
    <div className={`graph-wrap ${small ? "small" : ""}`}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
      >
        <Background color="#22304d" gap={22} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
