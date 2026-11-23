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

          <div className="section-title">Pods</div>
          <div className="controls">
            <input placeholder="search namespace / pod…" value={q} onChange={(e) => setQ(e.target.value)} />
            <select value={node} onChange={(e) => setNode(e.target.value)}>
              <option value="all">all nodes</option>
              {data.nodes.map((n) => <option key={n.name} value={n.name}>{n.name}</option>)}
            </select>
            <span className="count">{rows.length} pods</span>
          </div>
          <PodTable pods={rows} sort={sort} setSort={setSort} />
        </>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
