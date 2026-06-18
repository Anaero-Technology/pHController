import { AlertTriangle, Power, Zap } from "lucide-react";
import type { ControllerStatus } from "./api";
import { setController } from "./api";

export default function ControlBar({
  status,
  onChange,
}: {
  status: ControllerStatus | null;
  onChange: (s: ControllerStatus) => void;
}) {
  if (!status) return null;
  const { armed, dry_run, pumps, events, queue_depth } = status;
  const live = armed && !dry_run;

  async function toggleArm() {
    if (!armed && !dry_run) {
      const ok = window.confirm(
        "Arm with dry-run OFF? The pump will PHYSICALLY dispense when channels alarm."
      );
      if (!ok) return;
    }
    onChange(await setController({ armed: !armed }));
  }

  async function toggleDryRun() {
    if (dry_run) {
      const ok = window.confirm(
        "Turn OFF dry-run? Doses will physically drive the pump (not just simulate)."
      );
      if (!ok) return;
    }
    onChange(await setController({ dry_run: !dry_run }));
  }

  const armBtn = armed
    ? "bg-red-600 hover:bg-red-700"
    : "bg-blue-600 hover:bg-blue-700";

  return (
    <div className="mb-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 font-semibold text-gray-900 dark:text-slate-100">
          <Power size={18} className="text-blue-600" />
          Dosing controller
        </div>

        <span
          className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
            live
              ? "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300"
              : armed
              ? "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300"
              : "bg-gray-100 text-gray-500 dark:bg-slate-800 dark:text-slate-400"
          }`}
        >
          {live ? <Zap size={12} /> : null}
          {live ? "ARMED · LIVE" : armed ? "ARMED · dry-run" : "DISARMED"}
        </span>

        {(["alkaline", "acid"] as const).map((role) => {
          const p = pumps[role];
          return (
            <span
              key={role}
              className="flex items-center gap-1.5 rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500 dark:bg-slate-800 dark:text-slate-400"
            >
              <span className={`h-2 w-2 rounded-full ${p.connected ? "bg-green-500" : "bg-gray-400"}`} />
              {role}: {p.address == null ? "unassigned" : `UID ${p.address}`}
              {p.syringe_ml != null && ` · ${p.syringe_ml.toFixed(1)} ml`}
            </span>
          );
        })}

        {queue_depth > 0 && (
          <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-500/15 dark:text-blue-300">
            queue: {queue_depth}
          </span>
        )}

        <div className="ml-auto flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-slate-300">
            <input
              type="checkbox"
              checked={dry_run}
              onChange={toggleDryRun}
              className="h-4 w-4 accent-blue-600"
            />
            Dry run
          </label>
          <button
            onClick={toggleArm}
            className={`rounded-lg px-4 py-1.5 text-sm font-semibold text-white transition-colors ${armBtn}`}
          >
            {armed ? "Disarm" : "Arm"}
          </button>
        </div>
      </div>

      {live && (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          <AlertTriangle size={15} />
          Live dosing is active — the pump will physically dispense when a channel
          crosses its limit.
        </div>
      )}

      {events.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs font-medium text-gray-500 dark:text-slate-400">
            Recent doses
          </div>
          <div className="max-h-32 overflow-y-auto rounded-lg border border-gray-100 dark:border-slate-800">
            {events
              .slice()
              .reverse()
              .map((e, i) => (
                <div
                  key={i}
                  className="flex items-center gap-2 border-b border-gray-100 px-3 py-1.5 text-xs last:border-0 dark:border-slate-800"
                >
                  <span className="tabular-nums text-gray-400">{e.time}</span>
                  <span className="font-medium text-gray-700 dark:text-slate-200">
                    CH{e.channel}
                  </span>
                  <span
                    className={
                      e.edge === "low" ? "text-amber-600" : "text-red-600"
                    }
                  >
                    {e.edge}
                  </span>
                  <span className="text-gray-500 dark:text-slate-400">
                    {e.volume_ml} ml · valve {e.valve}
                  </span>
                  <span
                    className={`ml-auto ${
                      e.status === "done"
                        ? "text-green-600"
                        : e.status === "simulated"
                        ? "text-blue-500"
                        : e.status.startsWith("error")
                        ? "text-red-600"
                        : "text-gray-400"
                    }`}
                  >
                    {e.status}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
