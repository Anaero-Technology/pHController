import { useEffect, useState } from "react";
import { FlaskConical, Moon, Sun } from "lucide-react";
import type { Channel, ControllerStatus, PumpsResponse } from "./api";
import { getChannels, getController, getHealth, getMeta, getPumps } from "./api";
import ChannelCard from "./ChannelCard";
import ControlBar from "./ControlBar";
import NetworkPanel from "./NetworkPanel";
import PumpsPanel from "./PumpsPanel";

type View = "dashboard" | "network";

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
  const [view, setView] = useState<View>("dashboard");
  const [connected, setConnected] = useState(false); // this page <-> controller
  const [hmiConnected, setHmiConnected] = useState(false); // controller <-> HMI
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
        const [rows, ctrl, pmp, health] = await Promise.all([
          getChannels(),
          getController(),
          getPumps(),
          getHealth(),
        ]);
        if (!alive) return;
        setChannels(rows);
        setControllerState(ctrl);
        setPumps(pmp);
        setHmiConnected(health.connected);
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

  // Three states: the controller isn't answering this page; it is, but it has
  // lost the HMI (no pH readings, so no dosing); everything is up.
  const badge = !connected
    ? { text: "controller offline", cls: "bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300", dot: "bg-red-500" }
    : !hmiConnected
    ? { text: "HMI not connected", cls: "bg-amber-50 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300", dot: "bg-amber-500" }
    : { text: "HMI connected", cls: "bg-green-50 text-green-700 dark:bg-green-500/15 dark:text-green-300", dot: "bg-green-500" };

  const tabCls = (v: View) =>
    `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
      view === v
        ? "bg-blue-600 text-white"
        : "text-gray-600 hover:bg-gray-100 dark:text-slate-300 dark:hover:bg-slate-800"
    }`;

  return (
    <div className="mx-auto max-w-7xl p-4">
      <header className="mb-6 flex flex-wrap items-center gap-3 rounded-lg border border-gray-200 bg-white px-5 py-4 dark:border-slate-800 dark:bg-slate-900">
        <FlaskConical className="text-blue-600" size={22} />
        <h1 className="text-lg font-semibold text-gray-900 dark:text-slate-100">
          pH Controller
        </h1>
        <nav className="flex items-center gap-1">
          <button onClick={() => setView("dashboard")} className={tabCls("dashboard")}>
            Dashboard
          </button>
          <button onClick={() => setView("network")} className={tabCls("network")}>
            Network
          </button>
        </nav>
        <span
          className={`ml-auto flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${badge.cls}`}
        >
          <span className={`h-2 w-2 rounded-full ${badge.dot}`} />
          {badge.text}
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

      {view === "network" ? (
        <NetworkPanel />
      ) : (
        <>
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
        </>
      )}
    </div>
  );
}
