import { Droplet } from "lucide-react";
import type { PumpsResponse, Role } from "./api";
import { updatePump } from "./api";

const ROLE_META: Record<Role, { label: string; sub: string; dot: string }> = {
  alkaline: { label: "Alkaline pump", sub: "raises pH · LOW doses", dot: "bg-blue-500" },
  acid: { label: "Acid pump", sub: "lowers pH · HIGH doses", dot: "bg-orange-500" },
};

const selectCls =
  "rounded-lg border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100";

function RolePump({
  role,
  data,
  valves,
  onChange,
}: {
  role: Role;
  data: PumpsResponse;
  valves: number;
  onChange: (d: PumpsResponse) => void;
}) {
  const meta = ROLE_META[role];
  const cfg = data.config[role];
  const st = data.status[role];

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

      <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs text-gray-500 dark:text-slate-400">
        <div>
          UID (fixed):{" "}
          <b className="text-gray-700 dark:text-slate-200">{cfg.address ?? "—"}</b>
        </div>
        <div>
          port: <span className="opacity-70">{st.port ?? "—"}</span>
        </div>
        <div>
          syringe:{" "}
          <b className="text-gray-700 dark:text-slate-200">
            {st.syringe_ml == null ? "—" : `${st.syringe_ml.toFixed(1)} ml`}
          </b>
        </div>
        <div className="flex items-center gap-1.5">
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
  if (!data) return null;

  return (
    <div className="mb-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex items-center gap-2">
        <Droplet size={18} className="text-blue-600" />
        <span className="font-semibold text-gray-900 dark:text-slate-100">Pumps</span>
        <span className="text-xs text-gray-400">
          UID is fixed per pump · set each pump's refill valve below
        </span>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <RolePump role="alkaline" data={data} valves={valves} onChange={onChange} />
        <RolePump role="acid" data={data} valves={valves} onChange={onChange} />
      </div>
    </div>
  );
}
