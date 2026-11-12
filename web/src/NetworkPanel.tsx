import { useCallback, useEffect, useState } from "react";
import {
  Cable,
  EthernetPort,
  Loader2,
  Lock,
  RefreshCw,
  Wifi,
  WifiHigh,
  WifiLow,
  WifiZero,
} from "lucide-react";
import type { IpConfig, NetInterface, NetworkStatus, WifiNetwork } from "./api";
import { ApiError, connectWifi, getNetwork, scanWifi, setIpConfig } from "./api";

const REFRESH_MS = 10000;

const cardCls =
  "rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900";
const inputCls =
  "w-full rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm text-gray-900 transition-colors focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 disabled:opacity-50";
const labelCls = "text-xs font-medium text-gray-500 dark:text-slate-400";
const subtleBtn =
  "flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-medium text-gray-700 shadow-sm transition-all hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700";
const primaryBtn =
  "flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300 dark:disabled:bg-slate-700";

type Note = { kind: "ok" | "error" | "info"; text: string };

function NoteBox({ note }: { note: Note | null }) {
  if (!note) return null;
  const tone =
    note.kind === "ok"
      ? "border-green-200 bg-green-50 text-green-700 dark:border-green-500/30 dark:bg-green-500/10 dark:text-green-300"
      : note.kind === "error"
      ? "border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
      : "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300";
  return <div className={`mt-3 rounded-lg border px-3 py-2 text-sm ${tone}`}>{note.text}</div>;
}

const ip = (cidr: string) => cidr.split("/")[0];
const isLinkLocal = (cidr: string) => cidr.startsWith("169.254.");

/** Is the browser talking to the controller through this interface? */
function isThisConnection(iface: NetInterface) {
  return iface.addresses.some((a) => ip(a) === window.location.hostname);
}

function stateLabel(state: string) {
  if (state.startsWith("connected")) return "connected";
  if (state.startsWith("connecting")) return "connecting";
  if (state === "unavailable") return "unavailable";
  return state || "unknown";
}

function statePill(state: string) {
  if (state.startsWith("connected"))
    return "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300";
  if (state.startsWith("connecting"))
    return "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300";
  return "bg-gray-100 text-gray-500 dark:bg-slate-800 dark:text-slate-400";
}

// ---- one interface: live state + DHCP/static form -------------------------
function InterfaceRow({
  iface,
  rescue,
  onApplied,
}: {
  iface: NetInterface;
  rescue: string;
  onApplied: () => void;
}) {
  const wired = iface.type === "ethernet";
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"dhcp" | "static">("dhcp");
  const [address, setAddress] = useState("");
  const [prefix, setPrefix] = useState("24");
  const [gateway, setGateway] = useState("");
  const [dns, setDns] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Note | null>(null);

  const primary = iface.addresses.filter((a) => !isLinkLocal(a));
  const fallback = iface.addresses.filter(isLinkLocal);
  const here = isThisConnection(iface);
  // Wi-Fi IP settings live on the joined network's profile: nothing to edit
  // until one is joined.
  const configurable = wired || Boolean(iface.connection);

  function openForm() {
    // pre-fill from the live config so Apply is never a surprise
    const isStatic = iface.method === "manual";
    const current = primary[0];
    setMode(isStatic ? "static" : "dhcp");
    setAddress(current ? ip(current) : "");
    setPrefix(current ? current.split("/")[1] ?? "24" : "24");
    setGateway(isStatic ? iface.gateway ?? "" : "");
    setDns(isStatic ? iface.dns.join(", ") : "");
    setNote(null);
    setOpen(true);
  }

  async function apply() {
    if (
      here &&
      !window.confirm(
        "You are connected through this interface. Applying will interrupt the " +
          "connection, and this page may stop responding until you reconnect at " +
          "the new address. Continue?"
      )
    )
      return;
    const body: IpConfig =
      mode === "static"
        ? {
            mode: "static",
            address: address.trim(),
            prefix: Number(prefix),
            gateway: gateway.trim(),
            dns: dns
              .split(",")
              .map((d) => d.trim())
              .filter(Boolean),
          }
        : { mode: "dhcp" };
    setBusy(true);
    setNote(null);
    try {
      const res = await setIpConfig(iface.type, body);
      setNote({ kind: "ok", text: res.message });
    } catch (e) {
      if (e instanceof ApiError) {
        setNote({ kind: "error", text: e.message });
      } else {
        // the request died mid-flight: we were almost certainly connected
        // through the interface that was just reconfigured
        setNote({
          kind: "info",
          text:
            "The connection dropped while applying, which is expected when you are " +
            "connected through this interface. Reconnect at the new address" +
            (wired ? `, or over a direct cable at http://${ip(rescue)}.` : ", or over Ethernet."),
        });
      }
    } finally {
      setBusy(false);
      onApplied();
    }
  }

  const Icon = wired ? EthernetPort : Wifi;

  return (
    <div className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="w-full min-w-0 sm:w-auto sm:flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Icon size={16} className="text-gray-400 dark:text-slate-500" />
            <span className="font-semibold text-gray-900 dark:text-slate-100">
              {wired ? "Ethernet" : "Wi-Fi"}
            </span>
            <span className="text-xs text-gray-400 dark:text-slate-500">{iface.device}</span>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statePill(iface.state)}`}>
              {stateLabel(iface.state)}
            </span>
            {here && (
              <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-500/15 dark:text-blue-300">
                this connection
              </span>
            )}
          </div>
          <div className="mt-1 text-xs text-gray-500 dark:text-slate-400">
            {!wired && iface.ssid && (
              <>
                network <b className="text-gray-700 dark:text-slate-200">{iface.ssid}</b> ·{" "}
              </>
            )}
            {iface.method === "manual"
              ? "static address"
              : iface.method
              ? "automatic (DHCP)"
              : wired
              ? "not active"
              : "not joined to a network"}
            {iface.gateway && (
              <>
                {" "}
                · gateway <span className="font-mono">{iface.gateway}</span>
              </>
            )}
            {iface.mac && (
              <>
                {" "}
                · MAC <span className="font-mono">{iface.mac}</span>
              </>
            )}
          </div>
          {!wired && iface.state === "unavailable" && (
            <div className="mt-1 text-xs text-amber-700 dark:text-amber-300">
              The Wi-Fi radio is off or blocked. On Raspberry Pi OS it stays blocked until a
              Wi-Fi country is set (re-run the installer with WIFI_COUNTRY=xx).
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {primary.map((a) => (
            <span
              key={a}
              className="rounded-md border border-gray-200 bg-gray-50 px-2 py-1 font-mono text-xs font-semibold text-gray-800 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            >
              {a}
            </span>
          ))}
          {fallback.map((a) => (
            <span
              key={a}
              title="Fixed direct-cable address. Always present on Ethernet."
              className="flex items-center gap-1.5 rounded-md border border-gray-200 bg-gray-50 px-2 py-1 font-mono text-xs text-gray-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400"
            >
              {a}
              <span className="font-sans text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-slate-500">
                direct cable
              </span>
            </span>
          ))}
          {iface.addresses.length === 0 && (
            <span className="text-xs text-gray-400 dark:text-slate-500">no address</span>
          )}
          <button
            onClick={() => (open ? setOpen(false) : openForm())}
            disabled={!configurable}
            title={configurable ? undefined : "Join a Wi-Fi network first"}
            className={subtleBtn}
          >
            {open ? "Close" : "IP settings"}
          </button>
        </div>
      </div>

      {open && (
        <div className="mt-3 rounded-xl border border-gray-200 bg-gray-50 p-3 dark:border-slate-800 dark:bg-slate-800/40">
          <div className="mb-3 text-xs text-gray-500 dark:text-slate-400">
            {wired
              ? `The direct-cable address ${ip(rescue)} stays active in either mode, so a wrong setting here can't lock you out.`
              : `Applies to the joined network${iface.ssid ? ` (${iface.ssid})` : ""}. If a wrong setting cuts Wi-Fi off, reconnect by Ethernet cable.`}
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <label className="block">
              <span className={labelCls}>Mode</span>
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as "dhcp" | "static")}
                className={`${inputCls} mt-1`}
              >
                <option value="dhcp">Automatic (DHCP)</option>
                <option value="static">Static address</option>
              </select>
            </label>
            {mode === "static" && (
              <>
                <label className="block">
                  <span className={labelCls}>IP address</span>
                  <input
                    value={address}
                    onChange={(e) => setAddress(e.target.value)}
                    placeholder="192.168.2.50"
                    inputMode="decimal"
                    className={`${inputCls} mt-1 font-mono`}
                  />
                </label>
                <label className="block">
                  <span className={labelCls}>Prefix length</span>
                  <input
                    type="number"
                    min={1}
                    max={32}
                    value={prefix}
                    onChange={(e) => setPrefix(e.target.value)}
                    className={`${inputCls} mt-1 font-mono`}
                  />
                </label>
                <label className="block">
                  <span className={labelCls}>Gateway (optional)</span>
                  <input
                    value={gateway}
                    onChange={(e) => setGateway(e.target.value)}
                    placeholder="none"
                    inputMode="decimal"
                    className={`${inputCls} mt-1 font-mono`}
                  />
                </label>
                <label className="block">
                  <span className={labelCls}>DNS (optional)</span>
                  <input
                    value={dns}
                    onChange={(e) => setDns(e.target.value)}
                    placeholder="comma separated"
                    className={`${inputCls} mt-1 font-mono`}
                  />
                </label>
              </>
            )}
          </div>
          {mode === "static" && (
            <div className="mt-2 text-xs text-gray-400 dark:text-slate-500">
              Prefix 24 = netmask 255.255.255.0. Leave the gateway empty unless this network is
              the controller's route to the internet.
            </div>
          )}
          <div className="mt-3 flex items-center gap-2">
            <button onClick={apply} disabled={busy || (mode === "static" && !address.trim())} className={primaryBtn}>
              {busy && <Loader2 size={14} className="animate-spin" />}
              {busy ? "Applying…" : "Apply"}
            </button>
          </div>
          <NoteBox note={note} />
        </div>
      )}
    </div>
  );
}

// ---- Wi-Fi: scan + join ----------------------------------------------------
function SignalIcon({ signal }: { signal: number }) {
  const Icon = signal >= 75 ? Wifi : signal >= 50 ? WifiHigh : signal >= 25 ? WifiLow : WifiZero;
  return <Icon size={16} className="text-gray-500 dark:text-slate-400" />;
}

function WifiSection({ onJoined }: { onJoined: () => void }) {
  const [networks, setNetworks] = useState<WifiNetwork[] | null>(null);
  const [scanning, setScanning] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [username, setUsername] = useState("");
  const [eap, setEap] = useState("peap");
  const [phase2, setPhase2] = useState("mschapv2");
  const [joining, setJoining] = useState<string | null>(null);
  const [note, setNote] = useState<Note | null>(null);

  const scan = useCallback(async () => {
    setScanning(true);
    try {
      const res = await scanWifi();
      setNetworks(res.networks);
      if (res.error) setNote({ kind: "error", text: res.error });
    } catch (e) {
      setNote({ kind: "error", text: e instanceof Error ? e.message : "Scan failed" });
    } finally {
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    scan();
  }, [scan]);

  function select(net: WifiNetwork) {
    setSelected(selected === net.ssid ? null : net.ssid);
    setPassword("");
    setUsername("");
    setNote(null);
  }

  async function join(net: WifiNetwork) {
    const current = networks?.find((n) => n.connected);
    if (
      current &&
      current.ssid !== net.ssid &&
      !window.confirm(
        `Joining "${net.ssid}" leaves "${current.ssid}". If you are reaching this page ` +
          "over Wi-Fi you will need to reconnect on the new network (or by Ethernet cable). Continue?"
      )
    )
      return;
    setJoining(net.ssid);
    setNote(null);
    try {
      const res = await connectWifi({
        ssid: net.ssid,
        password,
        security: net.security,
        ...(net.enterprise ? { username: username.trim(), eap_method: eap, phase2 } : {}),
      });
      setNote({ kind: "ok", text: res.message });
      setSelected(null);
      setPassword("");
      scan();
    } catch (e) {
      setNote(
        e instanceof ApiError
          ? { kind: "error", text: e.message }
          : {
              kind: "info",
              text:
                `The connection dropped while joining "${net.ssid}". If you were on Wi-Fi, ` +
                "reconnect on the new network or by Ethernet cable.",
            }
      );
    } finally {
      setJoining(null);
      onJoined();
    }
  }

  return (
    <div className={cardCls}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Wifi size={18} className="text-blue-600" />
        <span className="font-semibold text-gray-900 dark:text-slate-100">Wi-Fi networks</span>
        <span className="text-xs text-gray-400">optional · the controller remembers joined networks</span>
        <button onClick={scan} disabled={scanning} className={`${subtleBtn} ml-auto`}>
          <RefreshCw size={13} className={scanning ? "animate-spin" : ""} />
          {scanning ? "Scanning…" : "Scan"}
        </button>
      </div>

      {networks === null ? (
        <div className="text-sm text-gray-500 dark:text-slate-400">Scanning for networks…</div>
      ) : networks.length === 0 ? (
        <div className="text-sm text-gray-500 dark:text-slate-400">No networks found.</div>
      ) : (
        <div className="divide-y divide-gray-100 rounded-xl border border-gray-200 dark:divide-slate-800 dark:border-slate-800">
          {networks.map((net) => {
            const isOpen = selected === net.ssid;
            const busy = joining === net.ssid;
            const ready = net.open || (password.length > 0 && (!net.enterprise || username.trim().length > 0));
            return (
              <div key={net.ssid} className="px-3 py-2">
                <div className="flex items-center gap-2">
                  <SignalIcon signal={net.signal} />
                  <span className="min-w-0 truncate text-sm font-medium text-gray-900 dark:text-slate-100">
                    {net.ssid}
                  </span>
                  {!net.open && <Lock size={12} className="shrink-0 text-gray-400" />}
                  <span className="hidden text-xs text-gray-400 sm:inline dark:text-slate-500">
                    {net.security}
                    {net.signal >= 0 && ` · ${net.signal}%`}
                  </span>
                  {net.connected ? (
                    <span className="ml-auto rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700 dark:bg-green-500/15 dark:text-green-300">
                      connected
                    </span>
                  ) : (
                    <button
                      onClick={() => (net.open ? join(net) : select(net))}
                      disabled={joining !== null}
                      className={`${subtleBtn} ml-auto`}
                    >
                      {busy && <Loader2 size={13} className="animate-spin" />}
                      {busy ? "Joining…" : isOpen ? "Cancel" : "Join"}
                    </button>
                  )}
                </div>

                {isOpen && !net.connected && (
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (ready) join(net);
                    }}
                    className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4"
                  >
                    {net.enterprise && (
                      <label className="block">
                        <span className={labelCls}>Username</span>
                        <input
                          value={username}
                          onChange={(e) => setUsername(e.target.value)}
                          placeholder="user@university.ac.uk"
                          autoComplete="username"
                          autoCapitalize="none"
                          className={`${inputCls} mt-1`}
                        />
                      </label>
                    )}
                    <label className="block">
                      <span className={labelCls}>Password</span>
                      <input
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        autoComplete="off"
                        autoFocus={!net.enterprise}
                        className={`${inputCls} mt-1`}
                      />
                    </label>
                    {net.enterprise && (
                      <>
                        <label className="block">
                          <span className={labelCls}>EAP method</span>
                          <select value={eap} onChange={(e) => setEap(e.target.value)} className={`${inputCls} mt-1`}>
                            <option value="peap">PEAP</option>
                            <option value="ttls">TTLS</option>
                            <option value="pwd">PWD</option>
                          </select>
                        </label>
                        <label className="block">
                          <span className={labelCls}>Inner authentication</span>
                          <select
                            value={phase2}
                            onChange={(e) => setPhase2(e.target.value)}
                            className={`${inputCls} mt-1`}
                          >
                            <option value="mschapv2">MSCHAPv2</option>
                            <option value="pap">PAP</option>
                            <option value="chap">CHAP</option>
                            <option value="mschap">MSCHAP</option>
                            <option value="gtc">GTC</option>
                            <option value="md5">MD5</option>
                          </select>
                        </label>
                      </>
                    )}
                    <div className="flex items-end">
                      <button type="submit" disabled={!ready || joining !== null} className={primaryBtn}>
                        {busy && <Loader2 size={14} className="animate-spin" />}
                        {busy ? "Joining…" : "Connect"}
                      </button>
                    </div>
                  </form>
                )}
              </div>
            );
          })}
        </div>
      )}
      <NoteBox note={note} />
    </div>
  );
}

// ---- page ------------------------------------------------------------------
export default function NetworkPanel() {
  const [status, setStatus] = useState<NetworkStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await getNetwork());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "fetch failed");
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  if (!status) {
    return <p className="text-gray-500 dark:text-slate-400">{error ?? "Loading…"}</p>;
  }

  if (!status.supported) {
    return (
      <div className={cardCls}>
        <div className="font-semibold text-gray-900 dark:text-slate-100">Network</div>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
          Network settings are managed on the controller itself (Raspberry Pi with
          NetworkManager). This machine isn't one, so there is nothing to configure here.
        </p>
      </div>
    );
  }

  const rescue = status.rescue_address;
  const port = window.location.port ? `:${window.location.port}` : "";
  const hasWifi = status.interfaces.some((i) => i.type === "wifi");
  const order = (i: NetInterface) => (i.type === "ethernet" ? 0 : 1);
  const interfaces = [...status.interfaces].sort((a, b) => order(a) - order(b));
  const { hmi } = status;

  return (
    <div className="space-y-4">
      <div className={cardCls}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <EthernetPort size={18} className="text-blue-600" />
          <span className="font-semibold text-gray-900 dark:text-slate-100">Connections</span>
          {status.hostname && (
            <span className="text-xs text-gray-400">
              also reachable at{" "}
              <a
                href={`http://${status.hostname}${port}`}
                className="font-mono text-blue-600 hover:underline dark:text-blue-400"
              >
                {status.hostname}
              </a>
            </span>
          )}
          <button onClick={load} className={`${subtleBtn} ml-auto`}>
            <RefreshCw size={13} />
            Refresh
          </button>
        </div>

        <div className="divide-y divide-gray-100 dark:divide-slate-800">
          {interfaces.map((iface) => (
            <InterfaceRow key={iface.device} iface={iface} rescue={rescue} onApplied={load} />
          ))}
          {interfaces.length === 0 && (
            <div className="text-sm text-gray-500 dark:text-slate-400">
              No network interfaces reported.
            </div>
          )}
        </div>

        <div className="mt-4 flex items-start gap-2 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500 dark:bg-slate-800/40 dark:text-slate-400">
          <Cable size={14} className="mt-0.5 shrink-0" />
          <span>
            Lost access? Plug an Ethernet cable straight from a computer into the controller
            and open <b className="font-mono text-gray-700 dark:text-slate-200">http://{ip(rescue)}</b>.
            That address works whatever is configured here.
          </span>
        </div>
      </div>

      <div className={cardCls}>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${hmi.connected ? "bg-green-500" : "bg-red-500"}`} />
          <span className="font-semibold text-gray-900 dark:text-slate-100">HMI link</span>
          <span className="font-mono text-xs text-gray-500 dark:text-slate-400">{hmi.host}</span>
          <span
            className={`ml-auto rounded-full px-2 py-0.5 text-xs font-medium ${
              hmi.connected
                ? "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300"
                : "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300"
            }`}
          >
            {hmi.connected ? "connected" : "not connected"}
          </span>
        </div>
        {!hmi.connected && (
          <p className="mt-2 text-sm text-gray-500 dark:text-slate-400">
            {hmi.on_subnet === false
              ? `The controller has no address on the HMI's network, so it cannot reach ${hmi.host}. ` +
                "If the HMI is on the Ethernet side, give Ethernet a static address in the same " +
                "range (same first three numbers, a different last one) and leave the gateway empty."
              : hmi.on_subnet
              ? `The controller has an address on the HMI's network but ${hmi.host} is not answering. ` +
                "Check the HMI's power and cable; the controller keeps retrying."
              : `${hmi.host} is not answering. Check the HMI's power and cable; the controller keeps retrying.`}
          </p>
        )}
      </div>

      {hasWifi && <WifiSection onJoined={load} />}
    </div>
  );
}
