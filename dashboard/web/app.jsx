const { useState, useEffect, useMemo, useCallback } = React;

/* ---------- formatting helpers ---------- */
const fmtCpu = (m) => (m == null ? null : (m / 1000).toFixed(2));
const fmtCpuShort = (m) => (m == null ? null : m < 1000 ? `${Math.round(m)}m` : `${(m / 1000).toFixed(2)}`);
const fmtMem = (mi) => {
  if (mi == null) return null;
  return mi >= 1024 ? `${(mi / 1024).toFixed(2)} Gi` : `${Math.round(mi)} Mi`;
};
const pct = (a, b) => (b > 0 ? (a * 100) / b : 0);
const clamp = (x) => Math.max(0, Math.min(100, x));

const sevClass = (p) => (p >= 90 ? "crit" : p >= 75 ? "warn" : "ok");

/* ---------- small presentational bits ---------- */
function Cell({ val, cls = "" }) {
  if (val == null) return <td className={`num na ${cls}`}>not-set</td>;
  return <td className={`num ${cls}`}>{val}</td>;
}

function ResourceBar({ label, used, requested, limit, allocatable, unit }) {
  const usedP = clamp(pct(used, allocatable));
  const reqP = clamp(pct(requested, allocatable));
  const limP = pct(limit, allocatable);
  const fmt = unit === "cpu" ? fmtCpu : fmtMem;
  const over = limP > 100;
  return (
    <div className="resgroup">
      <div className="head">
        <span>{label}</span>
        <span>
          <b>{fmt(used)}</b> used · {fmt(requested)} req ·{" "}
          <span className={over ? "t-warn" : ""}>{fmt(limit)} lim</span> / {fmt(allocatable)}
        </span>
      </div>
      <div className="bar" title={`used ${usedP.toFixed(0)}% · requested ${reqP.toFixed(0)}% · limit ${limP.toFixed(0)}% of allocatable`}>
        <span className="req" style={{ width: `${reqP}%` }} />
        <span className={`used g-${sevClass(usedP)}`} style={{ width: `${usedP}%` }} />
        {limP <= 100 && <span className="lim-marker" style={{ left: `${clamp(limP)}%` }} />}
      </div>
      <div className="legend">
        <span><i className="sw-used" />used {usedP.toFixed(0)}%</span>
        <span><i className="sw-req" />requested {reqP.toFixed(0)}%</span>
        <span><i className="sw-lim" />limit {limP.toFixed(0)}%{over ? " ⚠ overcommit" : ""}</span>
      </div>
    </div>
  );
}

function NodeCard({ n }) {
  const a = n.allocatable;
  return (
    <div className="node">
      <h3>
        {n.name}
        {!n.hasMetrics && <span className="pill warn">no live metrics</span>}
      </h3>
      <div className="sub">
        {n.podCount} pods · {(a.cpu_m / 1000).toFixed(0)} cores · {(a.mem_mi / 1024).toFixed(1)} GiB allocatable
      </div>
      <ResourceBar label="CPU" unit="cpu" allocatable={a.cpu_m}
        used={n.used.cpu_m} requested={n.requested.cpu_m} limit={n.limits.cpu_m} />
      <ResourceBar label="Memory" unit="mem" allocatable={a.mem_mi}
        used={n.used.mem_mi} requested={n.requested.mem_mi} limit={n.limits.mem_mi} />
    </div>
  );
}

function Kpi({ label, value, sub }) {
  return (
    <div className="kpi">
      <div className="label">{label}</div>
      <div className="value">{value} {sub && <small>{sub}</small>}</div>
    </div>
  );
}

/* ---------- pod table ---------- */
const COLUMNS = [
  { key: "namespace", label: "Namespace", num: false },
  { key: "name", label: "Pod", num: false },
  { key: "node", label: "Node", num: false },
  { key: "cpuUse_m", label: "CPU use", num: true },
  { key: "cpuReq_m", label: "CPU req", num: true },
  { key: "cpuLim_m", label: "CPU lim", num: true },
  { key: "cpuRatio", label: "CPU use/lim", num: true },
  { key: "memUse_mi", label: "Mem use", num: true },
  { key: "memReq_mi", label: "Mem req", num: true },
  { key: "memLim_mi", label: "Mem lim", num: true },
  { key: "memRatio", label: "Mem use/lim", num: true },
];

function memRatio(p) {
  if (p.memUse_mi == null || !p.memLim_mi) return null;
  return pct(p.memUse_mi, p.memLim_mi);
}
function cpuRatio(p) {
  if (p.cpuUse_m == null || !p.cpuLim_m) return null;
  return pct(p.cpuUse_m, p.cpuLim_m);
}

function RatioCell({ r }) {
  if (r == null) return <td className="num"><span className="na">—</span></td>;
  return (
    <td className="num">
      <span className="usecell">
        <span className="minibar"><span className={`g-${sevClass(r)}`} style={{ width: `${clamp(r)}%` }} /></span>
        <span className={`ratio t-${sevClass(r)}`}>{r.toFixed(0)}%</span>
      </span>
    </td>
  );
}

function PodRow({ p }) {
  return (
    <tr>
      <td className="ns">{p.namespace}</td>
      <td className="podname">{p.name}</td>
      <td className="ns">{p.node || "—"}</td>
      <Cell val={fmtCpuShort(p.cpuUse_m)} />
      <Cell val={fmtCpuShort(p.cpuReq_m)} />
      <Cell val={fmtCpuShort(p.cpuLim_m)} />
      <RatioCell r={cpuRatio(p)} />
      <Cell val={fmtMem(p.memUse_mi)} />
      <Cell val={fmtMem(p.memReq_mi)} />
      <Cell val={fmtMem(p.memLim_mi)} />
      <RatioCell r={memRatio(p)} />
    </tr>
  );
}

function PodTable({ pods, sort, setSort }) {
  const onSort = (key) =>
    setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: key === "namespace" || key === "name" ? 1 : -1 }));
  return (
    <div className="tablecard">
      <table>
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th key={c.key} className={c.num ? "num" : ""} onClick={() => onSort(c.key)}>
                {c.label}
                {sort.key === c.key && <span className="arrow">{sort.dir > 0 ? "▲" : "▼"}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {pods.length === 0 ? (
            <tr><td colSpan={COLUMNS.length} className="empty">No pods match the filter.</td></tr>
          ) : (
            pods.map((p) => <PodRow key={p.namespace + "/" + p.name} p={p} />)
          )}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- host usage (processes over SSH) ---------- */
function ProcTable({ title, rows, metric }) {
  return (
    <div className="ptable">
      <div className="pt-title">{title}</div>
      <table className="ptab">
        <tbody>
          {(rows || []).map((p, i) => {
            const v = metric === "cpu" ? p.cpu : p.mem;
            return (
              <tr key={i}>
                <td className="pcell"><span className="minibar"><span className={`g-${sevClass(v)}`} style={{ width: `${clamp(v)}%` }} /></span></td>
                <td className="num pval">{v.toFixed(1)}%</td>
                <td className="pcomm">
                  <div className="pshort">
                    {p.comm} <span className="ppid">#{p.pid}</span>
                    {p.container && <span className="pbadge" title={p.image ? `image: ${p.image}` : ""}>📦 {p.container}</span>}
                  </div>
                  <div className="ppath" title={`cmd: ${p.cmd}${p.exe ? "\nexe: " + p.exe : ""}${p.cwd ? "\ncwd: " + p.cwd : ""}`}>
                    {p.location || p.cmd || "—"}
                  </div>
                </td>
                <td className="num ns">{fmtMem(p.rssMi)}</td>
                <td className="ns puser" title={p.user}>{p.user}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HostNodeCard({ n }) {
  if (!n.ok) {
    return (
      <div className="hostcard err">
        <h3>{n.name}</h3>
        <div className="na">⚠ {n.error}</div>
      </div>
    );
  }
  const mem = n.mem || {};
  const memPct = mem.total_mi ? pct(mem.used_mi, mem.total_mi) : 0;
  return (
    <div className="hostcard">
      <h3>{n.name}</h3>
      <div className="sub">
        load {n.load1 != null ? n.load1 : "—"} · RAM {fmtMem(mem.used_mi)} / {fmtMem(mem.total_mi)} ({memPct.toFixed(0)}%)
      </div>
      <div className="proccols">
        <ProcTable title="Top processes by CPU" rows={n.procsByCpu} metric="cpu" />
        <ProcTable title="Top processes by RAM" rows={n.procsByMem} metric="mem" />
      </div>
      {n.containers && n.containers.length > 0 && (
        <div className="containers">
          <div className="pt-title">Non-k8s containers (docker)</div>
          {n.containers.map((c, i) => (
            <div className="crow" key={i}>
              <span className="cname">{c.name}</span>
              <span className="t-warn">{c.cpu}</span>
              <span className="ns">{c.mem}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function HostView({ host, loading }) {
  if (loading && !host) return <div className="empty"><span className="spin" /> scanning hosts over SSH…</div>;
  if (!host) return <div className="empty">Pick a node and press Scan to read host processes.</div>;
  if (host.error) return <div className="banner">⚠ {host.error}</div>;
  if (!host.nodes || host.nodes.length === 0) return <div className="empty">No nodes configured — edit <b>ssh-nodes.json</b>.</div>;
  return (
    <div className="hostgrid">
      {loading && <div className="meta" style={{ marginBottom: 8 }}><span className="spin" /> refreshing…</div>}
      {host.nodes.map((n) => <HostNodeCard key={n.name} n={n} />)}
    </div>
  );
}

/* ---------- app ---------- */
function App() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updated, setUpdated] = useState(null);
  const [node, setNode] = useState("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState({ key: "memUse_mi", dir: -1 });
  const [auto, setAuto] = useState(true);
  const [view, setView] = useState("pods");
  const [host, setHost] = useState(null);
  const [hostLoading, setHostLoading] = useState(false);
  const [hostNode, setHostNode] = useState("");   // Host-usage targets one node by default

  const loadHost = useCallback(async (n) => {
    setHostLoading(true);
    try {
      const res = await fetch(`/api/processes?node=${encodeURIComponent(n)}`);
      setHost(await res.json());
    } catch (e) {
      setHost({ nodes: [], error: String(e) });
    } finally {
      setHostLoading(false);
    }
  }, []);

  // On entering Host usage, default to the FIRST ssh node (single node = fast) then scan it.
  useEffect(() => {
    if (view !== "host" || !data) return;
    const ssh = data.sshNodes || [];
    const target = hostNode && (ssh.includes(hostNode) || hostNode === "all") ? hostNode : (ssh[0] || "all");
    if (target !== hostNode) { setHostNode(target); return; }  // re-runs effect, then scans
    loadHost(target);
  }, [view, hostNode, data, loadHost]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/data");
      const json = await res.json();
      if (json.error) { setErr(json.error); }
      else { setData(json); setErr(null); setUpdated(new Date()); }
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!auto) return;
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [auto, load]);

  const rows = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    let list = data.pods.filter((p) => {
      if (node !== "all" && p.node !== node) return false;
      if (needle && !(`${p.namespace}/${p.name}`).toLowerCase().includes(needle)) return false;
      return true;
    });
    const { key, dir } = sort;
    const val = (p) => (key === "memRatio" ? memRatio(p) : key === "cpuRatio" ? cpuRatio(p) : p[key]);
    list = [...list].sort((a, b) => {
      const va = val(a), vb = val(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;        // nulls always last
      if (vb == null) return -1;
      if (typeof va === "string") return va.localeCompare(vb) * dir;
      return (va - vb) * dir;
    });
    return list;
  }, [data, node, q, sort]);

  if (err && !data) {
    return (
      <div className="wrap">
        <header className="top"><h1><span className="logo">📊</span>k3s Resource Dashboard</h1></header>
        <div className="banner"><b>Could not load data.</b> {err}</div>
        <button className="btn primary" onClick={load}>Retry</button>
      </div>
    );
  }

  const c = data?.cluster;
  return (
    <div className="wrap">
      <header className="top">
        <h1><span className="logo">📊</span>k3s Resource Dashboard</h1>
        <div className="spacer" />
        <label className="toggle">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          auto-refresh 15s
        </label>
        <span className="meta">
          {updated ? `updated ${updated.toLocaleTimeString()}` : "—"}
        </span>
        <button className="btn primary" onClick={load} disabled={loading}>
          {loading ? <span className="spin" /> : "↻"} Refresh
        </button>
      </header>

      {err && <div className="banner">⚠ {err}</div>}
      {!data ? (
        <div className="empty"><span className="spin" /> loading cluster…</div>
      ) : (
        <>
          <div className="cluster">
            <Kpi label="Nodes" value={c.nodeCount} />
            <Kpi label="Pods" value={c.podCount} />
            <Kpi label="CPU allocatable" value={(c.allocatable.cpu_m / 1000).toFixed(0)} sub="cores" />
            <Kpi label="CPU used" value={(c.used.cpu_m / 1000).toFixed(2)} sub={`of ${(c.allocatable.cpu_m / 1000).toFixed(0)} (${pct(c.used.cpu_m, c.allocatable.cpu_m).toFixed(0)}%)`} />
            <Kpi label="Mem allocatable" value={(c.allocatable.mem_mi / 1024).toFixed(1)} sub="GiB" />
            <Kpi label="Mem used" value={(c.used.mem_mi / 1024).toFixed(1)} sub={`GiB (${pct(c.used.mem_mi, c.allocatable.mem_mi).toFixed(0)}%)`} />
          </div>

          <div className="section-title">Nodes</div>
          <div className="nodes">
            {data.nodes.map((n) => <NodeCard key={n.name} n={n} />)}
          </div>

          <div className="section-title">{view === "pods" ? "Pods" : "Host usage (all processes & containers)"}</div>
          <div className="controls">
            {view === "pods" && (
              <input placeholder="search namespace / pod…" value={q} onChange={(e) => setQ(e.target.value)} />
            )}
            {view === "pods" ? (
              <select value={node} onChange={(e) => setNode(e.target.value)}>
                <option value="all">all nodes</option>
                {data.nodes.map((n) => <option key={n.name} value={n.name}>{n.name}</option>)}
              </select>
            ) : (
              <select value={hostNode} onChange={(e) => setHostNode(e.target.value)}>
                {(data.sshNodes || []).map((n) => <option key={n} value={n}>{n}</option>)}
                <option value="all">all nodes (slow)</option>
              </select>
            )}
            <div className="viewtoggle">
              <button className={view === "pods" ? "active" : ""} onClick={() => setView("pods")}>K8s pods</button>
              <button className={view === "host" ? "active" : ""} onClick={() => setView("host")}>Host usage</button>
            </div>
            {view === "pods" ? (
              <span className="count">{rows.length} pods</span>
            ) : (
              <button className="btn" onClick={() => loadHost(hostNode)} disabled={hostLoading}>
                {hostLoading ? <span className="spin" /> : "↻"} Scan
              </button>
            )}
          </div>
          {view === "pods"
            ? <PodTable pods={rows} sort={sort} setSort={setSort} />
            : <HostView host={host} loading={hostLoading} />}
        </>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
