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

// FastAPI reports errors as {"detail": "..."} (or a list of validation issues);
// surface the message itself rather than the raw JSON body.
async function errorMessage(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  try {
    const detail = JSON.parse(text)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => d?.msg ?? String(d)).join("; ");
    }
  } catch {
    /* not JSON */
  }
  return text || res.statusText || `HTTP ${res.status}`;
}

// The server answered with an error -- as opposed to fetch() rejecting because
// the request never completed (which, after a network change, usually means the
// link we were talking over was just reconfigured).
export class ApiError extends Error {}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new ApiError(await errorMessage(res));
  return res.json() as Promise<T>;
}

export const getHealth = () =>
  fetch("/api/health").then((r) => json<{ connected: boolean; channels: number }>(r));

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

// ---- network (the appliance's own Ethernet / Wi-Fi settings) ----
export type IfaceType = "ethernet" | "wifi";

export interface NetInterface {
  device: string;
  type: IfaceType;
  state: string; // NetworkManager state, e.g. "connected", "unavailable"
  connection: string | null;
  ssid: string | null;
  method: string | null; // "auto" (DHCP) | "manual" (static) | ...
  addresses: string[]; // CIDR, e.g. "192.168.1.20/24"
  gateway: string | null;
  dns: string[];
  mac: string | null;
}

export interface NetworkStatus {
  supported: boolean; // false on a dev machine without NetworkManager
  hostname: string | null; // mDNS name, e.g. "phcontroller.local"
  rescue_address: string; // always-on direct-cable address (CIDR)
  interfaces: NetInterface[];
  hmi: { host: string; connected: boolean; on_subnet: boolean | null };
}

export interface WifiNetwork {
  ssid: string;
  signal: number; // percent, -1 if unknown
  security: string;
  open: boolean;
  enterprise: boolean;
  connected: boolean;
}

export type IpConfig =
  | { mode: "dhcp" }
  | { mode: "static"; address: string; prefix: number; gateway: string; dns: string[] };

export const getNetwork = () => fetch("/api/network").then((r) => json<NetworkStatus>(r));

export const setIpConfig = (type: IfaceType, body: IpConfig) =>
  fetch(`/api/network/${type}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => json<{ message: string }>(r));

export const scanWifi = () =>
  fetch("/api/network/wifi/networks").then((r) =>
    json<{ networks: WifiNetwork[]; error: string | null }>(r)
  );

export const connectWifi = (body: {
  ssid: string;
  password: string;
  username?: string;
  security: string;
  eap_method?: string;
  phase2?: string;
}) =>
  fetch("/api/network/wifi/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => json<{ message: string }>(r));
