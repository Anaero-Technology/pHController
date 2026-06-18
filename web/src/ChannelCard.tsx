import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import type { Action, Channel, ChannelUpdate } from "./api";
import { updateChannel } from "./api";

const inputCls =
  "w-full rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm text-gray-900 transition-colors focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 disabled:opacity-50";
const labelCls = "text-xs font-medium text-gray-500 dark:text-slate-400";

function DoseEditor({
  title,
  hint,
  tone,
  action,
  valves,
  refillValves,
  onChange,
}: {
  title: string;
  hint: string;
  tone: "low" | "high";
  action: Action;
  valves: number;
  refillValves: number[];
  onChange: (a: Action) => void;
}) {
  const Icon = tone === "low" ? ArrowDown : ArrowUp;
  const iconColor = tone === "low" ? "text-amber-500" : "text-red-500";
  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 p-3 dark:border-slate-800 dark:bg-slate-800/40">
      <div className="mb-1 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-sm font-medium text-gray-700 dark:text-slate-200">
          <Icon size={15} className={iconColor} />
          {title}
        </div>
        <label className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-slate-400">
          <input
            type="checkbox"
            checked={action.enabled}
            onChange={(e) => onChange({ ...action, enabled: e.target.checked })}
            className="h-3.5 w-3.5 accent-blue-600"
          />
          enabled
        </label>
      </div>
      <div className="mb-2 text-[11px] text-gray-400 dark:text-slate-500">{hint}</div>
      <div className="flex gap-2">
        <label className="block flex-1">
          <span className={labelCls}>Dose (ml)</span>
          <input
            type="number"
            step="0.1"
            min="0"
            value={action.volume_ml}
            disabled={!action.enabled}
            onChange={(e) => onChange({ ...action, volume_ml: Number(e.target.value) })}
            className={`${inputCls} mt-1`}
          />
        </label>
        <label className="block flex-1">
          <span className={labelCls}>From valve</span>
          <select
            value={action.valve}
            disabled={!action.enabled}
            onChange={(e) => onChange({ ...action, valve: Number(e.target.value) })}
            className={`${inputCls} mt-1`}
          >
            {Array.from({ length: valves }, (_, i) => i + 1)
              .filter((v) => !refillValves.includes(v))
              .map((v) => (
                <option key={v} value={v}>
                  Port {v}
                </option>
              ))}
          </select>
        </label>
      </div>
      <label className="mt-2 block">
        <span className={labelCls}>
          Repeat every (s){" "}
          <span className="text-gray-400 dark:text-slate-500">— 0 = once on crossing</span>
        </span>
        <input
          type="number"
          step="1"
          min="0"
          value={action.interval_s}
          disabled={!action.enabled}
          onChange={(e) => onChange({ ...action, interval_s: Number(e.target.value) })}
          className={`${inputCls} mt-1`}
        />
      </label>
    </div>
  );
}

export default function ChannelCard({
  data,
  valves,
  refillValves,
  onSaved,
}: {
  data: Channel;
  valves: number;
  refillValves: number[];
  onSaved: (c: Channel) => void;
}) {
  const [min, setMin] = useState<number | string>(data.min ?? "");
  const [max, setMax] = useState<number | string>(data.max ?? "");
  const [low, setLow] = useState<Action>(data.low);
  const [high, setHigh] = useState<Action>(data.high);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // sync from live data, but never clobber an in-progress edit
  useEffect(() => {
    if (!dirty) {
      setMin(data.min ?? "");
      setMax(data.max ?? "");
      setLow(data.low);
      setHigh(data.high);
    }
  }, [data, dirty]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const body: ChannelUpdate = { low, high };
      if (min !== "") body.min = Number(min);
      if (max !== "") body.max = Number(max);
      const c = await updateChannel(data.channel, body);
      onSaved(c);
      setDirty(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setSaving(false);
    }
  }

  const ring = data.alarm
    ? "border-red-300 ring-2 ring-red-500/50 dark:border-red-500/50"
    : "border-gray-200 dark:border-slate-800";
  const badgeCls =
    data.alarm === "LOW"
      ? "rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-500/15 dark:text-amber-300"
      : "rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-semibold text-red-700 dark:bg-red-500/15 dark:text-red-300";

  return (
    <div className={`rounded-2xl border bg-white p-4 shadow-sm dark:bg-slate-900 ${ring}`}>
      <div className="mb-3 flex items-center gap-2">
        <span className="text-sm font-semibold text-gray-400 dark:text-slate-500">
          CH{data.channel}
        </span>
        {data.alarm && <span className={badgeCls}>{data.alarm}</span>}
        <span className="ml-auto text-3xl font-bold tabular-nums text-gray-900 dark:text-slate-100">
          {data.ph == null ? "—" : data.ph.toFixed(2)}
          <span className="ml-1 align-middle text-xs font-medium text-gray-400">pH</span>
        </span>
      </div>

      <div className="mb-3 flex gap-2">
        <label className="block flex-1">
          <span className={labelCls}>Min</span>
          <input
            type="number"
            step="0.1"
            value={min}
            onChange={(e) => {
              setMin(e.target.value);
              setDirty(true);
            }}
            className={`${inputCls} mt-1`}
          />
        </label>
        <label className="block flex-1">
          <span className={labelCls}>Max</span>
          <input
            type="number"
            step="0.1"
            value={max}
            onChange={(e) => {
              setMax(e.target.value);
              setDirty(true);
            }}
            className={`${inputCls} mt-1`}
          />
        </label>
      </div>

      <div className="space-y-2">
        <DoseEditor
          title="On LOW → Alkaline"
          hint="pH below min → dose base to raise it"
          tone="low"
          action={low}
          valves={valves}
          refillValves={refillValves}
          onChange={(a) => {
            setLow(a);
            setDirty(true);
          }}
        />
        <DoseEditor
          title="On HIGH → Acid"
          hint="pH above max → dose acid to lower it"
          tone="high"
          action={high}
          valves={valves}
          refillValves={refillValves}
          onChange={(a) => {
            setHigh(a);
            setDirty(true);
          }}
        />
      </div>

      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={save}
          disabled={!dirty || saving}
          className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300 dark:disabled:bg-slate-700"
        >
          {saving ? "Saving…" : dirty ? "Save" : "Saved"}
        </button>
        {error && <span className="text-xs text-red-600 dark:text-red-400">{error}</span>}
      </div>
    </div>
  );
}
