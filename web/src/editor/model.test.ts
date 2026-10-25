import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  autoLayout,
  fromFlow,
  newEdgeData,
  nextId,
  quickChecks,
  replay,
  toFlow,
  type PathwayModel,
} from "./model";

const load = (name: string): PathwayModel =>
  JSON.parse(readFileSync(new URL(`../../../pathways/${name}.json`, import.meta.url), "utf8"));
const triage = load("triage");

describe("model <-> React Flow", () => {
  it("round-trips the triage pathway without losing settings", () => {
    const { nodes, edges } = toFlow(triage);
    const back = fromFlow(triage, nodes, edges);
    expect(back.edges).toHaveLength(triage.edges.length);
    const vitals = back.nodes.find((n) => n.id === "vitals")!;
    expect(vitals.deadline).toEqual({ minutes: 10, escalation: [{ role: "charge_nurse", afterMin: 5 }] });
    expect(back.edges.find((e) => e.to === "confirm")!.condition).toContain("spo2 < 90");
    expect(back.edges.find((e) => e.to === "waiting")!.default).toBe(true);
  });

  it("draws a task's fallback as a dashed arrow that is not saved as an edge", () => {
    const { nodes, edges } = toFlow(triage);
    const fb = edges.find((e) => e.data?.fallback)!;
    expect(fb.source).toBe("predict");
    expect(fb.target).toBe("manual_triage");
    expect(fb.id).toBe("predict~>manual_triage"); // pathway-core's id, so Verifier paths can use it
    expect(fromFlow(triage, nodes, edges).edges.some((e) => e.id === fb.id)).toBe(false);
  });

  it("keeps node positions", () => {
    const { nodes, edges } = toFlow(triage);
    nodes[0].position = { x: 123.4, y: 56.7 };
    const back = fromFlow(triage, nodes, edges);
    expect([back.nodes[0].x, back.nodes[0].y]).toEqual([123, 57]);
  });
});

describe("auto layout", () => {
  it("puts each node right of its predecessors and terminates on loops", () => {
    const pos = autoLayout(triage);
    expect(pos.get("start")!.x).toBeLessThan(pos.get("split1")!.x);
    expect(pos.get("join1")!.x).toBeGreaterThan(pos.get("merge_pred")!.x);
    expect(pos.get("end")!.x).toBeGreaterThan(pos.get("merge_out")!.x);
    const loop: PathwayModel = {
      id: "l", version: 1, variables: [],
      nodes: [{ id: "s", type: "start" }, { id: "m", type: "xor_merge" }, { id: "x", type: "xor_split" }, { id: "e", type: "end" }],
      edges: [{ id: "1", from: "s", to: "m" }, { id: "2", from: "m", to: "x" }, { id: "3", from: "x", to: "m", default: true }, { id: "4", from: "x", to: "e", condition: "true" }],
    };
    expect(autoLayout(loop).size).toBe(4);
  });
});

describe("editing helpers", () => {
  it("gives a decision's first branch the default and later branches a condition", () => {
    expect(newEdgeData("xor_split", [])).toEqual({ default: true });
    expect(newEdgeData("xor_split", [{ id: "a", source: "x", target: "y", data: { default: true } }])).toEqual({
      condition: "",
    });
    expect(newEdgeData("task", [])).toEqual({});
  });

  it("picks unused ids", () => {
    expect(nextId("task", [{ id: "task1" }, { id: "task2" }])).toBe("task3");
  });

  it("quick checks catch missing start, duplicate variables and empty conditions", () => {
    const bad: PathwayModel = {
      id: "x",
      version: 1,
      variables: [
        { name: "a", type: "int" },
        { name: "a", type: "int" },
      ],
      nodes: [{ id: "e", type: "end" }],
      edges: [{ id: "1", from: "d", to: "e", condition: "" }],
    };
    const issues = quickChecks(bad).join("\n");
    expect(issues).toMatch(/exactly one Start/);
    expect(issues).toMatch(/declared twice/);
    expect(issues).toMatch(/needs a condition/);
    expect(quickChecks(triage)).toEqual([]);
  });
});

describe("counterexample replay (NFR-USE-01)", () => {
  // The Verifier's real deadlock path for the imaging example (pathway-core edge ids).
  const deadlockPath = [
    { node: "register", consumed: ["start->register#0"], produced: ["register->imaging_type#1"] },
    { node: "imaging_type", consumed: ["register->imaging_type#1"], produced: ["imaging_type->xray#2"] },
    { node: "xray", consumed: ["imaging_type->xray#2"], produced: ["xray->wait_both#4"] },
  ];

  it("starts with one token after Start and moves it step by step", () => {
    const steps = replay(load("imaging_deadlock"), deadlockPath);
    expect(steps).toHaveLength(4);
    expect(steps[0]).toEqual({ tokens: { "start->register#0": 1 }, firing: null });
    expect(steps[2]).toEqual({ tokens: { "imaging_type->xray#2": 1 }, firing: "imaging_type" });
    // The stuck state: one token waits at the join, which needs a second one that never comes.
    expect(steps[3]).toEqual({ tokens: { "xray->wait_both#4": 1 }, firing: "xray" });
  });

  it("uses the same ids as the canvas, including fallback arrows", () => {
    const { edges } = toFlow(triage);
    const ids = new Set(edges.map((e) => e.id));
    const steps = replay(triage, [
      { node: "split1", consumed: ["start->split1#0"], produced: ["split1->predict#1", "split1->vitals#2"] },
      { node: "predict", consumed: ["split1->predict#1"], produced: ["predict~>manual_triage"] },
    ]);
    for (const step of steps) for (const id of Object.keys(step.tokens)) expect(ids.has(id)).toBe(true);
    expect(steps[2].tokens).toEqual({ "split1->vitals#2": 1, "predict~>manual_triage": 1 });
  });
});
