import { useEffect, useState } from "react";
import { FlaskConical, Moon, Sun, Wifi, WifiOff } from "lucide-react";
import type { Channel, ControllerStatus, PumpsResponse } from "./api";
import { getChannels, getController, getMeta, getPumps } from "./api";
import ChannelCard from "./ChannelCard";
import ControlBar from "./ControlBar";
import PumpsPanel from "./PumpsPanel";

const POLL_MS = 2000;

function useTheme() {
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem("theme");
    if (saved) return saved === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("theme", dark ? "dark" : "light");
  }, [dark]);
  return { dark, toggle: () => setDark((d) => !d) };
}

export default function App() {
  const { dark, toggle } = useTheme();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [valves, setValves] = useState(15);
  const [refillValves, setRefillValves] = useState<number[]>([15]);
  const [connected, setConnected] = useState(false);
  const [controller, setControllerState] = useState<ControllerStatus | null>(null);
  const [pumps, setPumps] = useState<PumpsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMeta()
      .then((m) => {
        setValves(m.valves);
        setRefillValves(m.refill_valves);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const [rows, ctrl, pmp] = await Promise.all([
          getChannels(),
          getController(),
          getPumps(),
        ]);
        if (!alive) return;
        setChannels(rows);
        setControllerState(ctrl);
        setPumps(pmp);
        setConnected(true);
        setError(null);
      } catch (e) {
        if (!alive) return;
        setConnected(false);
        setError(e instanceof Error ? e.message : "fetch failed");
      }
    }
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  function onSaved(c: Channel) {
    setChannels((prev) => prev.map((x) => (x.channel === c.channel ? c : x)));
  }

  return (
    <div className="mx-auto max-w-7xl p-4">
      <header className="mb-6 flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-5 py-4 dark:border-slate-800 dark:bg-slate-900">
        <FlaskConical className="text-blue-600" size={22} />
        <h1 className="text-lg font-semibold text-gray-900 dark:text-slate-100">
          pH Controller
        </h1>
        <span
          className={`ml-auto flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
            connected
              ? "bg-green-50 text-green-700 dark:bg-green-500/15 dark:text-green-300"
              : "bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300"
          }`}
        >
          {connected ? <Wifi size={13} /> : <WifiOff size={13} />}
          {connected ? "connected" : "offline"}
        </span>
        <button
          onClick={toggle}
          aria-label="toggle theme"
          className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm transition-all hover:border-gray-300 hover:bg-gray-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
        >
          {dark ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </header>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </div>
      )}

      <ControlBar status={controller} onChange={setControllerState} />

      <PumpsPanel data={pumps} valves={valves} onChange={setPumps} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {channels.map((c) => (
          <ChannelCard
            key={c.channel}
            data={c}
            valves={valves}
            refillValves={refillValves}
            onSaved={onSaved}
          />
        ))}
      </div>

      {channels.length === 0 && !error && (
        <p className="text-gray-500 dark:text-slate-400">Loading…</p>
      )}
    </div>
  );
}
