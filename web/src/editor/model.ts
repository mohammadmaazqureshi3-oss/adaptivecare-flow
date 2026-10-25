// The pathway JSON model (the same document pathway-core reads) and its conversion
// to and from React Flow's nodes and edges. Kept free of React so it can be unit-tested.

import type { Edge, Node } from "@xyflow/react";

export type NodeType =
  | "start"
  | "task"
  | "xor_split"
  | "xor_merge"
  | "and_split"
  | "and_join"
  | "timer"
  | "end";

export type VarType = "int" | "float" | "bool" | "string";

export interface Variable {
  name: string;
  type: VarType;
}

export interface Escalation {
  role: string;
  afterMin: number;
}

export interface Duration {
  dist: "fixed" | "exponential" | "lognormal" | "triangular";
  meanMin?: number;
  sdMin?: number;
  minMin?: number;
  modeMin?: number;
  maxMin?: number;
}

/** Everything a designer can set on a node (plan Section 5); which fields apply depends on the type. */
interface KnownNodeFields {
  id: string;
  type: NodeType;
  label?: string;
  kind?: "human" | "service" | "ml";
  role?: string;
  service?: string;
  inputs?: string[];
  outputs?: string[];
  trigger?: string;
  minutes?: number;
  fallback?: string;
  deadline?: { minutes: number; escalation: Escalation[] };
  retry?: { max: number; baseDelayS: number };
  undo?: string;
  duration?: Duration;
  override?: { suggested: string; decided: string };
  emit?: string;
  x?: number;
  y?: number;
}

/** Settings this editor does not know yet are kept as they are, so nothing is lost on save. */
export type NodeDoc = KnownNodeFields & Record<string, unknown>;

export interface EdgeDoc {
  id: string;
  from: string;
  to: string;
  condition?: string;
  default?: boolean;
  prob?: number;
}

export interface PathwayModel {
  id: string;
  version: number;
  name?: string;
  variables: Variable[];
  nodes: NodeDoc[];
  edges: EdgeDoc[];
}

/** The node's settings without its identity and position: what React Flow keeps in `data`. */
export type NodeData = Omit<KnownNodeFields, "id" | "type" | "x" | "y"> & Record<string, unknown>;
export type FlowNode = Node<NodeData, NodeType>;

export interface EdgeData extends Record<string, unknown> {
  condition?: string;
  default?: boolean;
  prob?: number;
  fallback?: boolean;
}
export type FlowEdge = Edge<EdgeData>;

export const NODE_LABELS: Record<NodeType, string> = {
  start: "Start",
  task: "Task",
  xor_split: "Decision",
  xor_merge: "Merge",
  and_split: "Parallel split",
  and_join: "Parallel join",
  timer: "Timer",
  end: "End",
};


export function edgeLabel(d: EdgeData | undefined): string | undefined {
  if (!d) return undefined;
  if (d.fallback) return "fallback";
  if (d.default) return "default";
  return d.condition || undefined;
}

/**
 * Positions for nodes saved without any (e.g. hand-written JSON): each node one column
 * right of its furthest predecessor on a path from Start, rows stacked within a column.
 */
export function autoLayout(model: PathwayModel): Map<string, { x: number; y: number }> {
  const out = new Map<string, string[]>();
  for (const e of model.edges) out.set(e.from, [...(out.get(e.from) ?? []), e.to]);
  for (const n of model.nodes) if (n.fallback) out.set(n.id, [...(out.get(n.id) ?? []), n.fallback]);
  const depth = new Map<string, number>();
  const start = model.nodes.find((n) => n.type === "start")?.id;
  const queue = start ? [start] : [];
  if (start) depth.set(start, 0);
  // Longest-path layering, bounded so loops cannot run forever.
  for (let steps = 0; queue.length && steps < model.nodes.length * model.nodes.length; steps++) {
    const id = queue.shift()!;
    for (const next of out.get(id) ?? []) {
      const d = depth.get(id)! + 1;
      if (d < model.nodes.length && d > (depth.get(next) ?? -1)) {
        depth.set(next, d);
        queue.push(next);
      }
    }
  }
  const rows = new Map<number, number>();
  const pos = new Map<string, { x: number; y: number }>();
  for (const n of model.nodes) {
    const col = depth.get(n.id) ?? 0;
    const row = rows.get(col) ?? 0;
    rows.set(col, row + 1);
    pos.set(n.id, { x: 60 + col * 200, y: 80 + row * 120 });
  }
  return pos;
}

export function toFlow(model: PathwayModel): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const layout = model.nodes.some((n) => n.x === undefined || n.y === undefined) ? autoLayout(model) : null;
  const nodes: FlowNode[] = model.nodes.map((n) => {
    const { id, type, x, y, ...data } = n;
    const auto = layout?.get(id) ?? { x: 0, y: 0 };
    return { id, type, position: { x: x ?? auto.x, y: y ?? auto.y }, data };
  });
  const edges: FlowEdge[] = model.edges.map((e, i) => {
    const data: EdgeData = { condition: e.condition, default: e.default, prob: e.prob };
    // Same default id as pathway-core, so ids stay stable across save and verify.
    const id = e.id || `${e.from}->${e.to}#${i}`;
    return { id, source: e.from, target: e.to, data, label: edgeLabel(data) };
  });
  return { nodes, edges: [...edges, ...fallbackEdges(nodes)] };
}

/** A task's fallback is a node setting; it is drawn as a dashed arrow that cannot be edited directly. */
export function fallbackEdges(nodes: FlowNode[]): FlowEdge[] {
  return nodes
    .filter((n) => n.type === "task" && n.data.fallback)
    .map((n) => ({
      id: fallbackEdgeId(n.id, n.data.fallback as string),
      source: n.id,
      target: n.data.fallback as string,
      data: { fallback: true },
      label: "fallback",
      deletable: false,
      selectable: false,
      animated: true,
      className: "fallback-edge",
    }));
}

/** The same id pathway-core gives a fallback arrow, so Verifier paths can be drawn on it. */
export function fallbackEdgeId(task: string, target: string): string {
  return `${task}~>${target}`;
}

export function isFallbackEdge(e: FlowEdge): boolean {
  return e.data?.fallback === true;
}

// ---- counterexample replay (NFR-USE-01) ------------------------------------------

export interface MoveLike {
  node: string;
  consumed: string[];
  produced: string[];
}

export interface ReplayStep {
  /** Tokens per arrow id after this step. */
  tokens: Record<string, number>;
  /** The node that fired to reach this step; null for the initial marking. */
  firing: string | null;
}

/**
 * Re-run a Verifier counterexample with the token rules: step 0 is the initial
 * marking (one token after Start), step k is the marking after the k-th move.
 */
export function replay(model: PathwayModel, path: MoveLike[]): ReplayStep[] {
  const ids = model.edges.map((e, i) => e.id || `${e.from}->${e.to}#${i}`);
  const tokens: Record<string, number> = {};
  model.edges.forEach((e, i) => {
    const from = model.nodes.find((n) => n.id === e.from);
    if (from?.type === "start") tokens[ids[i]] = (tokens[ids[i]] ?? 0) + 1;
  });
  const steps: ReplayStep[] = [{ tokens: { ...tokens }, firing: null }];
  for (const move of path) {
    for (const id of move.consumed) tokens[id] = (tokens[id] ?? 0) - 1;
    for (const id of move.produced) tokens[id] = (tokens[id] ?? 0) + 1;
    steps.push({ tokens: Object.fromEntries(Object.entries(tokens).filter(([, n]) => n > 0)), firing: move.node });
  }
  return steps;
}

export function fromFlow(
  base: Pick<PathwayModel, "id" | "version" | "name" | "variables">,
  nodes: FlowNode[],
  edges: FlowEdge[],
): PathwayModel {
  return {
    ...base,
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.type as NodeType,
      ...clean(n.data),
      x: Math.round(n.position.x),
      y: Math.round(n.position.y),
    })),
    edges: edges
      .filter((e) => !isFallbackEdge(e))
      .map((e) => {
        const doc: EdgeDoc = { id: e.id, from: e.source, to: e.target };
        if (e.data?.default) doc.default = true;
        else if (e.data?.condition !== undefined) doc.condition = e.data.condition;
        if (e.data?.prob !== undefined) doc.prob = e.data.prob;
        return doc;
      }),
  };
}

/** Drop empty settings so the saved JSON stays readable. */
function clean(data: NodeData): NodeData {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(data)) {
    if (v === undefined || v === "" || (Array.isArray(v) && v.length === 0)) continue;
    out[k] = v;
  }
  return out as NodeData;
}

/** A fresh, unused node id such as `task3`. */
export function nextId(type: NodeType, nodes: { id: string }[]): string {
  const taken = new Set(nodes.map((n) => n.id));
  let i = 1;
  while (taken.has(`${type}${i}`)) i++;
  return `${type}${i}`;
}

export function defaultData(type: NodeType): NodeData {
  switch (type) {
    case "task":
      return { label: "New task", kind: "human", role: "nurse", inputs: [], outputs: [] };
    case "timer":
      return { label: "Wait", minutes: 10 };
    case "start":
      return { label: "Start", inputs: [] };
    default:
      return { label: NODE_LABELS[type] };
  }
}

/** Settings for a new arrow: a decision's first branch is its default, later ones need a condition. */
export function newEdgeData(sourceType: NodeType | undefined, existingFromSource: FlowEdge[]): EdgeData {
  if (sourceType !== "xor_split") return {};
  const hasDefault = existingFromSource.some((e) => e.data?.default);
  return hasDefault ? { condition: "" } : { default: true };
}

/** What the editor checks before saving; the Verifier does the real analysis. */
export function quickChecks(model: PathwayModel): string[] {
  const issues: string[] = [];
  const starts = model.nodes.filter((n) => n.type === "start").length;
  if (starts !== 1) issues.push(`A pathway needs exactly one Start (it has ${starts}).`);
  if (!model.nodes.some((n) => n.type === "end")) issues.push("A pathway needs at least one End.");
  const names = model.variables.map((v) => v.name);
  const dup = names.find((n, i) => names.indexOf(n) !== i);
  if (dup) issues.push(`Variable "${dup}" is declared twice.`);
  for (const v of model.variables) {
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(v.name)) issues.push(`"${v.name}" is not a valid variable name.`);
  }
  for (const e of model.edges) {
    if (e.condition !== undefined && !e.default && e.condition.trim() === "") {
      issues.push(`The branch ${e.from} → ${e.to} needs a condition or must be the default.`);
    }
  }
  return issues;
}
