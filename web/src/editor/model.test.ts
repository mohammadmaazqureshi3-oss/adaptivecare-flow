import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { autoLayout, fromFlow, newEdgeData, nextId, quickChecks, toFlow, type PathwayModel } from "./model";

const triage: PathwayModel = JSON.parse(
  readFileSync(new URL("../../../pathways/triage.json", import.meta.url), "utf8"),
);

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
