// The pathway IDE (P4): draw (DES-01), declare data (DES-02), write conditions (DES-03),
// set task policies (DES-04), Save, Verify (Algorithm 1), Publish an immutable version (DES-05).

import {
  addEdge,
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type User, type VerificationError, type Version, type VersionSummary } from "../api";
import { EdgeInspector, NodeInspector } from "../editor/Inspector";
import {
  defaultData,
  edgeLabel,
  fallbackEdges,
  fromFlow,
  isFallbackEdge,
  newEdgeData,
  nextId,
  NODE_LABELS,
  quickChecks,
  replay,
  toFlow,
  type EdgeData,
  type FlowEdge,
  type FlowNode,
  type NodeData,
  type NodeType,
  type Variable,
} from "../editor/model";
import { nodeTypes } from "../editor/nodes";
import { ReportPanel } from "../editor/ReportPanel";
import { StatusBadge } from "../editor/StatusBadge";
import { VariablesPanel } from "../editor/VariablesPanel";

const PALETTE: NodeType[] = ["task", "xor_split", "xor_merge", "and_split", "and_join", "timer", "start", "end"];

type Selection = { kind: "node" | "edge"; id: string } | null;

export function Editor(props: { pathwayId: string; user: User }) {
  return (
    <ReactFlowProvider>
      <EditorInner {...props} />
    </ReactFlowProvider>
  );
}

function EditorInner({ pathwayId, user }: { pathwayId: string; user: User }) {
  const flow = useReactFlow();
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [version, setVersion] = useState<Version | null>(null);
  const [nodes, setNodes, onNodesChangeBase] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChangeBase] = useEdgesState<FlowEdge>([]);
  const [variables, setVariables] = useState<Variable[]>([]);
  const [dirty, setDirty] = useState(false);
  const [selection, setSelection] = useState<Selection>(null);
  const [selectedError, setSelectedError] = useState<VerificationError | null>(null);
  const [notice, setNotice] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  // Bumped on every load: the canvas remounts, so React Flow measures the new nodes from scratch.
  const [canvasKey, setCanvasKey] = useState(0);

  const readOnly = user.role !== "designer" || version?.status === "published";

  const show = useCallback((v: Version) => {
    const f = toFlow(v.model);
    setVersion(v);
    setNodes(f.nodes);
    setEdges(f.edges.filter((e) => !isFallbackEdge(e)));
    setVariables(v.model.variables ?? []);
    setDirty(false);
    setSelection(null);
    setSelectedError(null);
    setCanvasKey((k) => k + 1);
  }, [setNodes, setEdges]);

  const load = useCallback(
    async (versionId?: number) => {
      try {
        const list = await api.versions(pathwayId);
        setVersions(list);
        show(await api.version(versionId ?? list[list.length - 1].id));
      } catch (err) {
        setNotice({ kind: "error", text: err instanceof Error ? err.message : "Could not load the pathway" });
      }
    },
    [pathwayId, show],
  );

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => dirty && e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const onNodesChange = useCallback(
    (changes: NodeChange<FlowNode>[]) => {
      onNodesChangeBase(changes);
      if (changes.some((c) => c.type === "remove" || (c.type === "position" && c.dragging === false))) setDirty(true);
    },
    [onNodesChangeBase],
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange<FlowEdge>[]) => {
      onEdgesChangeBase(changes);
      if (changes.some((c) => c.type === "remove")) setDirty(true);
    },
    [onEdgesChangeBase],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      setEdges((eds) => {
        const sourceType = nodes.find((n) => n.id === c.source)?.type;
        const data = newEdgeData(sourceType, eds.filter((e) => e.source === c.source));
        const id = `${c.source}->${c.target}#${Date.now().toString(36)}`;
        return addEdge({ ...c, id, data, label: edgeLabel(data) }, eds);
      });
      setDirty(true);
    },
    [nodes, setEdges],
  );

  function addNode(type: NodeType) {
    const id = nextId(type, nodes);
    const pane = document.querySelector(".canvas")?.getBoundingClientRect();
    const centre = pane
      ? flow.screenToFlowPosition({ x: pane.left + pane.width / 2, y: pane.top + pane.height / 2 })
      : { x: 200, y: 200 };
    const jitter = (nodes.length % 5) * 20;
    setNodes((ns) => [
      ...ns.map((n) => ({ ...n, selected: false })),
      { id, type, position: { x: centre.x + jitter, y: centre.y + jitter }, data: defaultData(type), selected: true },
    ]);
    setSelection({ kind: "node", id });
    setDirty(true);
  }

  function updateNode(id: string, patch: Partial<NodeData>) {
    setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)));
    setDirty(true);
  }

  function updateEdge(id: string, patch: Partial<EdgeData>) {
    setEdges((es) =>
      es.map((e) => {
        if (e.id !== id) return e;
        const data = { ...e.data, ...patch };
        return { ...e, data, label: edgeLabel(data) };
      }),
    );
    setDirty(true);
  }

  function makeDefault(id: string) {
    const source = edges.find((e) => e.id === id)?.source;
    setEdges((es) =>
      es.map((e) => {
        if (e.source !== source) return e;
        const data: EdgeData = e.id === id ? { ...e.data, default: true, condition: undefined } : { ...e.data, default: false, condition: e.data?.condition ?? "" };
        return { ...e, data, label: edgeLabel(data) };
      }),
    );
    setDirty(true);
  }

  function deleteSelected() {
    if (!selection) return;
    if (selection.kind === "node") {
      const id = selection.id;
      setNodes((ns) =>
        ns.filter((n) => n.id !== id).map((n) => (n.data.fallback === id ? { ...n, data: { ...n.data, fallback: undefined } } : n)),
      );
      setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
    } else {
      setEdges((es) => es.filter((e) => e.id !== selection.id));
    }
    setSelection(null);
    setDirty(true);
  }

  const model = useMemo(
    () => (version ? fromFlow({ id: pathwayId, version: version.number, name: version.model.name, variables }, nodes, edges) : null),
    [version, pathwayId, variables, nodes, edges],
  );
  const hints = useMemo(() => (model ? quickChecks(model) : []), [model]);

  async function act(label: string, action: () => Promise<Version | void>) {
    setBusy(true);
    setNotice(null);
    try {
      const v = await action();
      if (v) {
        setVersion(v);
        setVersions(await api.versions(pathwayId));
      }
      setNotice({ kind: "info", text: label });
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Request failed" });
    } finally {
      setBusy(false);
    }
  }

  const save = () =>
    act("Draft saved.", async () => {
      const v = await api.saveVersion(version!.id, model!);
      setDirty(false);
      return v;
    });

  const verify = () =>
    act("Verification finished.", async () => {
      if (dirty) {
        await api.saveVersion(version!.id, model!);
        setDirty(false);
      }
      const v = await api.verify(version!.id);
      setSelectedError(v.report?.errors[0] ?? null);
      return v;
    });

  const publish = () => act(`Version ${version!.number} published. It can no longer change.`, () => api.publish(version!.id));

  const newDraft = () =>
    act("New draft created from the latest version.", async () => {
      const v = await api.newDraft(pathwayId);
      await load(v.id);
    });

  // Replay of the selected error's counterexample (NFR-USE-01). It runs on the saved
  // version the report belongs to, and is hidden while there are unsaved edits.
  const steps = useMemo(
    () => (selectedError && version && !dirty ? replay(version.model, selectedError.path) : []),
    [selectedError, version, dirty],
  );
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    setStep(Math.max(steps.length - 1, 0)); // open on the bad state; step back from there
    setPlaying(false);
  }, [steps]);
  useEffect(() => {
    if (!playing) return;
    if (step >= steps.length - 1) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setStep((k) => k + 1), 800);
    return () => clearTimeout(t);
  }, [playing, step, steps.length]);

  const current = steps[step];
  const atEnd = step === steps.length - 1;
  const firedBefore = useMemo(
    () => new Set(selectedError?.path.slice(0, Math.max(step - 1, 0)).map((m) => m.node) ?? []),
    [selectedError, step],
  );

  const shownNodes = useMemo(() => {
    const nodeClass = (id: string): string => {
      if (!selectedError) return "";
      if (!current) return selectedError.nodes.includes(id) ? "hl-error" : "";
      if (current.firing === id) return "hl-firing";
      if (atEnd && selectedError.nodes.includes(id)) return "hl-error";
      return firedBefore.has(id) ? "hl-path" : "";
    };
    return nodes.map((n) => ({ ...n, className: nodeClass(n.id) }));
  }, [nodes, selectedError, current, atEnd, firedBefore]);
  const shownEdges = useMemo(
    () =>
      [...edges, ...fallbackEdges(nodes)].map((e) => {
        const tokens = current?.tokens[e.id] ?? 0;
        const base = typeof e.label === "string" ? e.label : "";
        return {
          ...e,
          label: tokens ? `${"●".repeat(tokens)} ${base}`.trim() : e.label,
          className: [e.className, selectedError?.edge === e.id ? "hl-error-edge" : "", tokens ? "has-token" : ""]
            .filter(Boolean)
            .join(" "),
        };
      }),
    [edges, nodes, selectedError, current],
  );

  const selectedNode = selection?.kind === "node" ? nodes.find((n) => n.id === selection.id) : undefined;
  const selectedEdge = selection?.kind === "edge" ? edges.find((e) => e.id === selection.id) : undefined;
  const latest = versions[versions.length - 1];

  if (!version) {
    return <div className="page">{notice ? <p className="error">{notice.text}</p> : <p className="muted">Loading…</p>}</div>;
  }

  return (
    <div className="editor">
      <div className="toolbar">
        <a href="#/pathways" className="ghost">
          ← Pathways
        </a>
        <strong>{version.model.name || pathwayId}</strong>
        <select value={version.id} onChange={(e) => load(Number(e.target.value))} disabled={busy}>
          {versions.map((v) => (
            <option key={v.id} value={v.id}>
              v{v.number} · {v.status}
            </option>
          ))}
        </select>
        <StatusBadge status={version.status} />
        {dirty && <span className="muted small">unsaved changes</span>}
        <span className="spacer" />
        {user.role === "designer" && version.status !== "published" && (
          <>
            <button onClick={save} disabled={busy || !dirty}>
              Save
            </button>
            <button onClick={verify} disabled={busy}>
              Verify
            </button>
            <button
              className="primary"
              onClick={publish}
              disabled={busy || dirty || version.status !== "verified"}
              title={version.status !== "verified" ? "Verify this version as SAFE first" : "Freeze this version"}
            >
              Publish
            </button>
          </>
        )}
        {user.role === "designer" && latest?.status === "published" && (
          <button className="primary" onClick={newDraft} disabled={busy}>
            New draft (v{latest.number + 1})
          </button>
        )}
      </div>
      {notice && <div className={`notice ${notice.kind}`}>{notice.text}</div>}
      {readOnly && (
        <div className="notice info">
          {version.status === "published"
            ? "Published versions are immutable. Start a new draft to change this pathway."
            : "Read-only: only designers edit pathways."}
        </div>
      )}

      <div className="editor-body">
        {!readOnly && (
          <aside className="palette">
            <h3>Add</h3>
            {PALETTE.map((t) => (
              <button key={t} className={`pal pal-${t}`} onClick={() => addNode(t)}>
                {NODE_LABELS[t]}
              </button>
            ))}
            <p className="muted small">Drag from a node's right dot to another node's left dot to draw an arrow.</p>
          </aside>
        )}
        <div className="canvas">
          <ReactFlow
            key={canvasKey}
            nodes={shownNodes}
            edges={shownEdges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, n) => setSelection({ kind: "node", id: n.id })}
            onEdgeClick={(_, e) => !isFallbackEdge(e) && setSelection({ kind: "edge", id: e.id })}
            onPaneClick={() => setSelection(null)}
            nodesDraggable={!readOnly}
            nodesConnectable={!readOnly}
            deleteKeyCode={readOnly ? null : ["Backspace", "Delete"]}
            // Curved arrows: branches leaving one decision separate at once, so each stays clickable.
            defaultEdgeOptions={{ type: "default", interactionWidth: 16 }}
            fitView
            fitViewOptions={{ padding: 0.2 }}
          >
            <Background gap={16} />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>
        <aside className="side">
          {selectedNode ? (
            <NodeInspector
              node={selectedNode}
              nodes={nodes}
              variables={variables}
              readOnly={readOnly}
              onChange={(p) => updateNode(selectedNode.id, p)}
              onDelete={deleteSelected}
            />
          ) : selectedEdge ? (
            <EdgeInspector
              edge={selectedEdge}
              sourceType={nodes.find((n) => n.id === selectedEdge.source)?.type}
              variables={variables}
              readOnly={readOnly}
              onChange={(p) => updateEdge(selectedEdge.id, p)}
              onMakeDefault={() => makeDefault(selectedEdge.id)}
              onDelete={deleteSelected}
            />
          ) : (
            <VariablesPanel
              variables={variables}
              readOnly={readOnly}
              onChange={(v) => {
                setVariables(v);
                setDirty(true);
              }}
            />
          )}
          {hints.length > 0 && !readOnly && (
            <div className="hints">
              {hints.map((h) => (
                <div key={h}>⚠ {h}</div>
              ))}
            </div>
          )}
          {version.report && (
            <ReportPanel
              report={version.report}
              selected={selectedError}
              onSelect={setSelectedError}
              replay={
                steps.length > 1
                  ? { step, total: steps.length, firing: current?.firing ?? null, playing, setStep, setPlaying }
                  : null
              }
              stale={dirty}
            />
          )}
        </aside>
      </div>
    </div>
  );
}
