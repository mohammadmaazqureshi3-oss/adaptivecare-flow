// Every request goes through the gateway at /api (proxied by Vite in development and
// nginx in Compose). The access token lives in memory only; the refresh token is kept in
// sessionStorage so a page reload does not log the user out, and is gone when the tab closes.

import type { PathwayModel } from "./editor/model";

export type Role = "admin" | "designer" | "nurse" | "charge_nurse" | "doctor" | "manager";
export const ROLES: Role[] = ["admin", "designer", "nurse", "charge_nurse", "doctor", "manager"];

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  active: boolean;
}

export interface VersionSummary {
  id: number;
  pathway_id: string;
  number: number;
  status: "draft" | "verified" | "published" | "deployed" | "draining" | "retired";
  author: string;
  updated_at: string;
  published_at: string | null;
  report_status: "SAFE" | "UNSAFE" | "TOO_LARGE" | null;
}

export interface Move {
  node: string;
  consumed: string[];
  produced: string[];
}

export interface VerificationError {
  type: string;
  property: string;
  nodes: string[];
  message: string;
  path: Move[];
  edge?: string;
  pos?: number;
}

export interface Report {
  status: "SAFE" | "UNSAFE" | "TOO_LARGE";
  errors: VerificationError[];
  states_explored: number;
  search_complete: boolean;
  elapsed_ms: number;
}

export interface Version extends VersionSummary {
  model: PathwayModel;
  report: Report | null;
}

export interface PathwaySummary {
  id: string;
  name: string;
  created_by: string;
  latest_version: VersionSummary | null;
  published_versions: number[];
}

export interface ConditionCheck {
  ok: boolean;
  errors: { kind: "syntax" | "type"; message: string; pos: number }[];
}

export type Sex = "female" | "male" | "other" | "unknown";
export type ArrivalMode = "walk_in" | "ambulance" | "referral" | "other";

export interface Patient {
  id: number;
  mrn: string;
  name: string;
  date_of_birth: string;
  age: number;
  sex: Sex;
  arrival_mode: ArrivalMode;
  chief_complaint: string;
  arrived_at: string;
  registered_by: string;
}

export interface PatientIn {
  name: string;
  date_of_birth: string;
  sex: Sex;
  arrival_mode: ArrivalMode;
  chief_complaint: string;
  confirm_duplicate?: boolean;
}

export interface Bed {
  id: string;
  ward: string;
  status: "free" | "reserved" | "occupied";
  patient_id: string;
  case_id: string;
  updated_at: string;
}

export interface TargetIn {
  task: string;
  max_wait_min: number;
  max_share: number;
  urgency_max: number | null;
}

export interface ScenarioIn {
  arrivals_per_hour: number | number[];
  staff: Record<string, number>;
  cost: Record<string, number>;
  days: number;
  warmup_days: number;
  seed: number;
  targets: TargetIn[];
}

export interface EstimateOut {
  mean: number;
  low: number;
  high: number;
  half_width: number;
}

export interface SimulationResult {
  replications: number;
  cap_reached: boolean;
  metrics: Record<string, EstimateOut>;
}

export interface SimulationJob {
  id: number;
  version_id: number;
  pathway: string;
  version: number;
  kind: "simulate" | "advise";
  scenario: ScenarioIn;
  budget: number | null;
  status: "queued" | "running" | "done" | "failed";
  error: string;
  created_at: string;
  result: null | {
    roles: string[];
    targets: { metric: string; limit: number; text: string }[];
    simulation?: SimulationResult;
    advice?: {
      staff: Record<string, number>;
      cost: number;
      feasible: boolean;
      reason: string;
      rounds: { staff: Record<string, number>; cost: number; shortfall: number }[];
      result: SimulationResult | null;
    };
  };
}

export interface Notification {
  id: number;
  role: string;
  message: string;
  case_id: string;
  created_at: string;
}

export interface Deployment {
  id: number;
  version_id: number;
  pathway: string;
  version: number;
  container: string;
  queue: string;
  schema: string;
  status: "starting" | "running" | "failed" | "draining" | "retired";
  error: string;
  requested_by: string;
  started_at: string;
  healthy_at: string | null;
}

export interface Task {
  id: number;
  case_id: string;
  pathway: string;
  version: number;
  node: string;
  label: string;
  role: string;
  patient_id: string;
  inputs: Record<string, unknown>;
  outputs: { name: string; type: "int" | "float" | "bool" | "string" }[];
  deadline_min: number | null;
  due_at: string | null;
  kind: "task" | "undo";
  level: number;
  override: { suggested: string; decided: string } | null;
  status: "open" | "claimed" | "done" | "cancelled" | "failed";
  assignee: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
  completed_at: string | null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
  }
}

const REFRESH_KEY = "adaptivecare.refresh";
let accessToken: string | null = null;
let onLoggedOut: () => void = () => {};

export function setLoggedOutHandler(fn: () => void): void {
  onLoggedOut = fn;
}

function readRefresh(): string | null {
  try {
    return sessionStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

function writeRefresh(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(REFRESH_KEY, token);
    else sessionStorage.removeItem(REFRESH_KEY);
  } catch {
    /* storage blocked: the session simply ends with the page */
  }
}

async function refreshAccess(): Promise<boolean> {
  const refresh_token = readRefresh();
  if (!refresh_token) return false;
  const r = await fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh_token }),
  });
  if (!r.ok) {
    writeRefresh(null);
    return false;
  }
  accessToken = (await r.json()).access_token;
  return true;
}

async function request<T>(method: string, path: string, body?: unknown, retry = true): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["content-type"] = "application/json";
  if (accessToken) headers.authorization = `Bearer ${accessToken}`;
  const r = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401 && retry && (await refreshAccess())) {
    return request<T>(method, path, body, false);
  }
  if (r.status === 401) {
    accessToken = null;
    onLoggedOut();
  }
  if (!r.ok) {
    let message = `${r.status} ${r.statusText}`;
    let detail: unknown;
    try {
      detail = (await r.json()).detail;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail)) message = detail.map((d: { msg: string }) => d.msg).join("; ");
      else if (detail && typeof detail === "object" && "message" in detail) message = String(detail.message);
    } catch {
      /* keep the status text */
    }
    throw new ApiError(r.status, message, detail);
  }
  return (await r.json()) as T;
}

export const api = {
  async login(email: string, password: string): Promise<User> {
    const body = await request<{ access_token: string; refresh_token: string; user: User }>(
      "POST",
      "/auth/login",
      { email, password },
      false,
    );
    accessToken = body.access_token;
    writeRefresh(body.refresh_token);
    return body.user;
  },
  async resume(): Promise<User | null> {
    if (!(await refreshAccess())) return null;
    return request<User>("GET", "/auth/me");
  },
  logout(): void {
    accessToken = null;
    writeRefresh(null);
  },

  users: () => request<User[]>("GET", "/users"),
  createUser: (u: { name: string; email: string; password: string; role: Role }) =>
    request<User>("POST", "/users", u),
  updateUser: (id: number, patch: Partial<Pick<User, "name" | "role" | "active">> & { password?: string }) =>
    request<User>("PATCH", `/users/${id}`, patch),

  pathways: () => request<PathwaySummary[]>("GET", "/pathways"),
  createPathway: (id: string, name: string) => request<PathwaySummary>("POST", "/pathways", { id, name }),
  versions: (pathwayId: string) => request<VersionSummary[]>("GET", `/pathways/${pathwayId}/versions`),
  newDraft: (pathwayId: string) => request<Version>("POST", `/pathways/${pathwayId}/versions`),
  version: (id: number) => request<Version>("GET", `/versions/${id}`),
  saveVersion: (id: number, model: PathwayModel) => request<Version>("PUT", `/versions/${id}`, { model }),
  verify: (id: number) => request<Version>("POST", `/versions/${id}/verify`),
  publish: (id: number) => request<Version>("POST", `/versions/${id}/publish`),
  checkCondition: (condition: string, variables: PathwayModel["variables"]) =>
    request<ConditionCheck>("POST", "/conditions/check", { condition, variables }),

  searchPatients: (q: string) => request<Patient[]>("GET", `/patients?q=${encodeURIComponent(q)}`),
  registerPatient: (p: PatientIn) => request<Patient>("POST", "/patients", p),

  startSimulation: (versionId: number, body: { scenario: ScenarioIn; advise: boolean; budget: number | null }) =>
    request<SimulationJob>("POST", `/versions/${versionId}/simulations`, body),
  simulation: (jobId: number) => request<SimulationJob>("GET", `/simulations/${jobId}`),
  simulations: (versionId: number) => request<SimulationJob[]>("GET", `/simulations?version_id=${versionId}`),

  notifications: () => request<Notification[]>("GET", "/notifications"),
  deploy: (versionId: number) => request<Deployment>("POST", `/versions/${versionId}/deploy`),
  undeploy: (deploymentId: number) => request<Deployment>("DELETE", `/deployments/${deploymentId}`),
  deployments: (pathway: string) => request<Deployment[]>("GET", `/deployments?pathway=${encodeURIComponent(pathway)}`),

  beds: () => request<Bed[]>("GET", "/beds"),
  addBed: (id: string, ward: string) => request<Bed>("POST", "/beds", { id, ward }),
  releaseBed: (id: string) => request<Bed>("POST", `/beds/${encodeURIComponent(id)}/release`),

  tasks: (includeDone = false) => request<Task[]>("GET", `/tasks${includeDone ? "?include_done=true" : ""}`),
  claimTask: (id: number) => request<Task>("POST", `/tasks/${id}/claim`),
  releaseTask: (id: number) => request<Task>("POST", `/tasks/${id}/release`),
  completeTask: (id: number, outputs: Record<string, unknown>, reason?: string) =>
    request<Task>("POST", `/tasks/${id}/complete`, { outputs, reason }),
  failTask: (id: number, reason: string) => request<Task>("POST", `/tasks/${id}/fail`, { reason }),
};
