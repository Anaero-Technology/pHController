export interface Action {
  enabled: boolean;
  volume_ml: number;
  valve: number;
  interval_s: number; // 0 = dose once on crossing; >0 = repeat every N s while breached
}

export interface Channel {
  channel: number;
  ph: number | null;
  min: number | null;
  max: number | null;
  alarm: "LOW" | "HIGH" | null;
  low: Action;
  high: Action;
}

export type Role = "acid" | "alkaline";

export interface Meta {
  connected: boolean;
  channels: number;
  valves: number;
  refill_valves: number[];
  role_for_edge: { low: Role; high: Role };
}

export interface PumpStatus {
  address: number | null;
  refill_valve: number;
  connected: boolean;
  port: string | null;
  syringe_ml: number | null;
}

export interface PumpsConfig {
  acid: { address: number | null; refill_valve: number };
  alkaline: { address: number | null; refill_valve: number };
}

export interface DoseEvent {
  ts: number;
  time: string;
  channel: number;
  edge: "low" | "high";
  role: Role;
  volume_ml: number;
  valve: number;
  status: string;
}

export interface ControllerStatus {
  armed: boolean;
  dry_run: boolean;
  queue_depth: number;
  pumps: Record<Role, PumpStatus>;
  breached: string[];
  events: DoseEvent[];
}

export interface ChannelUpdate {
  min?: number;
  max?: number;
  low?: Action;
  high?: Action;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const getMeta = () => fetch("/api/meta").then((r) => json<Meta>(r));

export const getChannels = () =>
  fetch("/api/channels").then((r) => json<Channel[]>(r));

export const updateChannel = (ch: number, body: ChannelUpdate) =>
  fetch(`/api/channels/${ch}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => json<Channel>(r));

export const getController = () =>
  fetch("/api/controller").then((r) => json<ControllerStatus>(r));

export const setController = (body: { armed?: boolean; dry_run?: boolean }) =>
  fetch("/api/controller", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => json<ControllerStatus>(r));

// ---- pumps ----
export interface PumpsResponse {
  config: PumpsConfig;
  status: Record<Role, PumpStatus>;
}

export const getPumps = () => fetch("/api/pumps").then((r) => json<PumpsResponse>(r));

export const updatePump = (role: Role, body: { address?: number; refill_valve?: number }) =>
  fetch(`/api/pumps/${role}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => json<PumpsResponse>(r));

export const discoverPumps = () =>
  fetch("/api/pumps/discover", { method: "POST" }).then((r) =>
    json<{ found: Record<string, string> }>(r)
  );

export const assignPump = (
  role: Role,
  body: { current_address: number; new_address: number; refill_valve?: number }
) =>
  fetch(`/api/pumps/${role}/assign`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => json<PumpsResponse & { assign: unknown }>(r));
