import { useState } from "react";
import { Droplet, RefreshCw } from "lucide-react";
import type { PumpsResponse, Role } from "./api";
import { assignPump, discoverPumps, updatePump } from "./api";

const ROLE_META: Record<
  Role,
  { label: string; sub: string; dot: string; defaultUID: number }
> = {
  alkaline: { label: "Alkaline pump", sub: "raises pH · LOW doses", dot: "bg-blue-500", defaultUID: 2 },
  acid: { label: "Acid pump", sub: "lowers pH · HIGH doses", dot: "bg-orange-500", defaultUID: 1 },
};

const selectCls =
  "rounded-lg border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100";

function RolePump({
  role,
  data,
  valves,
  found,
  onChange,
}: {
  role: Role;
  data: PumpsResponse;
  valves: number;
  found: Record<string, string> | null;
  onChange: (d: PumpsResponse) => void;
}) {
  const meta = ROLE_META[role];
  const cfg = data.config[role];
  const st = data.status[role];
  const [newUID, setNewUID] = useState<number>(cfg.address ?? meta.defaultUID);
  const [fromAddr, setFromAddr] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const foundAddrs = found ? Object.keys(found) : [];

  async function assign() {
    if (fromAddr === "") return;
    if (
      !window.confirm(
        `Assign the pump currently at address ${fromAddr} as the ${role.toUpperCase()} pump ` +
          `and write UID ${newUID} to it? Make sure this is the correct physical pump.`
      )
    )
      return;
    setBusy(true);
    setErr(null);
    try {
      const r = await assignPump(role, {
        current_address: Number(fromAddr),
        new_address: newUID,
      });
      onChange(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "assign failed");
    } finally {
      setBusy(false);
    }
  }

  async function setRefill(v: number) {
    try {
      onChange(await updatePump(role, { refill_valve: v }));
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 p-3 dark:border-slate-800 dark:bg-slate-800/40">
      <div className="mb-2 flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${meta.dot}`} />
        <span className="font-semibold text-gray-900 dark:text-slate-100">{meta.label}</span>
        <span className="text-xs text-gray-400">{meta.sub}</span>
        <span
          className={`ml-auto rounded-full px-2 py-0.5 text-xs font-medium ${
            st.connected
              ? "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300"
              : "bg-gray-200 text-gray-500 dark:bg-slate-700 dark:text-slate-400"
          }`}
        >
          {cfg.address == null ? "unassigned" : st.connected ? "online" : "offline"}
        </span>
      </div>

      <div className="mb-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-gray-500 dark:text-slate-400">
        <div>UID (address): <b className="text-gray-700 dark:text-slate-200">{cfg.address ?? "—"}</b></div>
        <div>port: <span className="opacity-70">{st.port ?? "—"}</span></div>
        <div>
          syringe: <b className="text-gray-700 dark:text-slate-200">
            {st.syringe_ml == null ? "—" : `${st.syringe_ml.toFixed(1)} ml`}
          </b>
        </div>
        <div className="flex items-center gap-1">
          refill valve:
          <select
            value={cfg.refill_valve}
            onChange={(e) => setRefill(Number(e.target.value))}
            className={selectCls + " py-0.5"}
          >
            {Array.from({ length: valves }, (_, i) => i + 1).map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-gray-200 pt-2 text-xs dark:border-slate-700">
        <span className="text-gray-500 dark:text-slate-400">Assign pump at</span>
        <select
          value={fromAddr}
          onChange={(e) => setFromAddr(e.target.value)}
          className={selectCls}
          disabled={!found}
        >
          <option value="">{found ? "addr…" : "discover first"}</option>
          {foundAddrs.map((a) => (
            <option key={a} value={a}>
              addr {a}
            </option>
          ))}
        </select>
        <span className="text-gray-500 dark:text-slate-400">→ UID</span>
        <input
          type="number"
          min={0}
          max={255}
          value={newUID}
          onChange={(e) => setNewUID(Number(e.target.value))}
          className={selectCls + " w-16"}
        />
        <button
          onClick={assign}
          disabled={busy || fromAddr === ""}
          className="rounded-lg bg-blue-600 px-3 py-1 font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 dark:disabled:bg-slate-700"
        >
          {busy ? "…" : "Assign"}
        </button>
        {err && <span className="text-red-600">{err}</span>}
      </div>
    </div>
  );
}

export default function PumpsPanel({
  data,
  valves,
  onChange,
}: {
  data: PumpsResponse | null;
  valves: number;
  onChange: (d: PumpsResponse) => void;
}) {
  const [found, setFound] = useState<Record<string, string> | null>(null);
  const [busy, setBusy] = useState(false);

  async function discover() {
    setBusy(true);
    try {
      setFound((await discoverPumps()).found);
    } catch {
      setFound({});
    } finally {
      setBusy(false);
    }
  }

  if (!data) return null;

  return (
    <div className="mb-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex items-center gap-2">
        <Droplet size={18} className="text-blue-600" />
        <span className="font-semibold text-gray-900 dark:text-slate-100">Pumps</span>
        <button
          onClick={discover}
          disabled={busy}
          className="ml-auto flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm transition-all hover:bg-gray-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
        >
          <RefreshCw size={14} className={busy ? "animate-spin" : ""} />
          Discover
        </button>
      </div>
      {found && (
        <div className="mb-3 text-xs text-gray-500 dark:text-slate-400">
          found:{" "}
          {Object.keys(found).length === 0
            ? "no pumps"
            : Object.entries(found).map(([a, p]) => `addr ${a} @ ${p}`).join("  ·  ")}
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <RolePump role="alkaline" data={data} valves={valves} found={found} onChange={onChange} />
        <RolePump role="acid" data={data} valves={valves} found={found} onChange={onChange} />
      </div>
    </div>
  );
}
