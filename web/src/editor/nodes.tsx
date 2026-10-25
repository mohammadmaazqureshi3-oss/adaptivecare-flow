// One canvas shape per pathway element (plan Section 5). Arrows go left to right:
// every node but Start has an input handle, every node but End has an output handle.

import { Handle, Position, type NodeProps, type NodeTypes } from "@xyflow/react";
import type { FlowNode, NodeType } from "./model";

const KIND_ICON = { human: "👤", service: "⚙︎", ml: "🧠" } as const;

function Ports({ type }: { type: NodeType }) {
  return (
    <>
      {type !== "start" && <Handle type="target" position={Position.Left} />}
      {type !== "end" && <Handle type="source" position={Position.Right} />}
    </>
  );
}

function TaskNode({ data, selected }: NodeProps<FlowNode>) {
  const kind = data.kind ?? "human";
  const who = kind === "human" ? data.role : data.service;
  return (
    <div className={`pn pn-task ${selected ? "selected" : ""}`}>
      <Ports type="task" />
      <div className="pn-title">
        <span aria-hidden>{KIND_ICON[kind]}</span> {data.label || "Task"}
      </div>
      <div className="pn-sub">
        {who && <span>{who}</span>}
        {data.deadline && <span title="deadline">⏱ {data.deadline.minutes} min</span>}
        {data.retry && <span title="retries">↻ {data.retry.max}</span>}
      </div>
    </div>
  );
}

function DecisionNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`pn pn-diamond ${selected ? "selected" : ""}`}>
      <Ports type="xor_split" />
      <div className="pn-diamond-shape" />
      <div className="pn-diamond-label">{data.label || "Decision"}</div>
    </div>
  );
}

function GatewayNode(symbol: string, cls: string, type: NodeType) {
  return function Gateway({ data, selected }: NodeProps<FlowNode>) {
    return (
      <div className={`pn pn-gateway ${cls} ${selected ? "selected" : ""}`} title={data.label}>
        <Ports type={type} />
        <span className="pn-symbol">{symbol}</span>
        <div className="pn-under">{data.label}</div>
      </div>
    );
  };
}

function EventNode(type: "start" | "end") {
  return function Event({ data, selected }: NodeProps<FlowNode>) {
    return (
      <div className={`pn pn-event pn-${type} ${selected ? "selected" : ""}`}>
        <Ports type={type} />
        <div className="pn-under">
          {data.label || (type === "start" ? "Start" : "End")}
          {type === "start" && data.trigger && <div className="pn-trigger">on {data.trigger}</div>}
        </div>
      </div>
    );
  };
}

function TimerNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`pn pn-event pn-timer ${selected ? "selected" : ""}`}>
      <Ports type="timer" />
      <span className="pn-symbol">⏲</span>
      <div className="pn-under">
        {data.label} · {data.minutes ?? "?"} min
      </div>
    </div>
  );
}

export const nodeTypes: NodeTypes = {
  start: EventNode("start"),
  end: EventNode("end"),
  task: TaskNode,
  xor_split: DecisionNode,
  xor_merge: GatewayNode("✕", "pn-xor", "xor_merge"),
  and_split: GatewayNode("+", "pn-and", "and_split"),
  and_join: GatewayNode("+", "pn-and", "and_join"),
  timer: TimerNode,
};
