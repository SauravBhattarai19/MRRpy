'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { buildModel, childrenOf, mcSweep, scatterAdd, sweepSolve, eliminationFill, type TreeModel } from '@/lib/tree/tree';
import { WidgetFrame, Toggle, LookFor, Stat, Unstable, Slider } from '../flood/ui';
import { PRESETS, GridView, TreeView, RoleLegend, cellName, Btn, T } from './shared';

type Walk = 'explicit' | 'mc' | 'implicit';
type OrderKind = 'natural' | 'shuffled';

// seeded shuffle, so "Reshuffle" is repeatable and the page renders the same on the server
function shuffled(n: number, seed: number) {
  const a = Array.from({ length: n }, (_, i) => i);
  let s = seed * 9301 + 49297;
  for (let i = n - 1; i > 0; i--) {
    s = (s * 9301 + 49297) % 233280;
    const j = Math.floor((s / 233280) * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}
const f2 = (v: number) => (Number.isFinite(v) ? v.toFixed(2) : '—');

// ── the explicit walk (kinematic / diffusive): compute all, then scatter ─────
function explicitFrames(m: TreeModel, visit: number[]) {
  const n = m.order.length;
  const O = m.order.map((f) => 0.5 * (1 + (f % 3)));            // outflow volume this step
  const movers = visit.filter((i) => m.dsIdx[i] >= 0);
  const frames: { inflow: number[]; active: number[]; note: string }[] = [];
  frames.push({ inflow: new Array(n).fill(0), active: m.order.map((_, i) => i),
    note: 'Phase 1: all cells work out their outflow at the same time, each from its own water at the end of the last step. Nobody waits for anybody.' });
  const inflow = new Array(n).fill(0);
  for (const i of movers) {
    scatterAdd(inflow, [m.dsIdx[i]], [O[i]]);
    frames.push({ inflow: [...inflow], active: [i],
      note: `Phase 2 (scatter_add): ${cellName(m.order[i])} adds its ${f2(O[i])} into ${cellName(m.order[m.dsIdx[i]])}'s inflow, giving ${f2(inflow[m.dsIdx[i]])}.` });
  }
  frames.push({ inflow: [...inflow], active: [],
    note: 'Phase 3: every cell updates its water: new = old + inflow − outflow, again all at once. The step is done.' });
  return { O, frames };
}

// ── the Muskingum–Cunge sweep: one cell at a time, upstream first ───────────
const MC = { C0: 0.4, C1: 0.3, C2: 0.3, C3: 1 };
function mcRun(m: TreeModel, visit: number[], upto: number) {
  const n = m.order.length;
  const c = (v: number) => new Array(n).fill(v);
  return mcSweep(c(MC.C0), c(MC.C1), c(MC.C2), c(MC.C3), c(0), c(0), c(1), m.dsIdx, visit.slice(0, upto));
}

// ── the implicit tree solve ──────────────────────────────────────────────────
function treeSystem(m: TreeModel, store: number) {
  const n = m.order.length;
  const off = m.dsIdx.map((d) => (d >= 0 ? -1 : 0));                        // −K, K = 1 on every face
  const diag = m.dsIdx.map(() => store + 1);                                // own face (at a root: the outflow face)
  m.dsIdx.forEach((d) => { if (d >= 0) diag[d] += 1; });                    // children's faces
  const rhs = new Array(n).fill(1);                                         // A/Δt·z_old + q, with z_old = 0, q = 1
  return { diag, off, rhs };
}
function implicitFrames(m: TreeModel, store: number) {
  const n = m.order.length, { diag: d0, off, rhs: b0 } = treeSystem(m, store);
  const diag = [...d0], rhs = [...b0];
  const z = new Array<number>(n).fill(NaN);
  const frames: { diag: number[]; rhs: number[]; z: number[]; done: number; active: number; phase: 'fold' | 'back' | 'start'; note: string }[] = [];
  frames.push({ diag: [...diag], rhs: [...rhs], z: [...z], done: -1, active: -1, phase: 'start',
    note: 'The matrix M of one implicit step: one row per cell, ordered upstream → downstream. Off the diagonal, a −1 appears only where a cell meets its one downstream cell.' });
  for (let i = 0; i < n; i++) {
    const p = m.dsIdx[i];
    if (p >= 0) {
      const inv = 1 / diag[i];
      diag[p] -= off[i] * off[i] * inv;
      rhs[p] -= off[i] * rhs[i] * inv;
    }
    frames.push({ diag: [...diag], rhs: [...rhs], z: [...z], done: i, active: i, phase: 'fold',
      note: p >= 0
        ? `Fold ${cellName(m.order[i])} into its parent ${cellName(m.order[p])}: only ${cellName(m.order[p])}'s diagonal and right-hand side change. Row ${cellName(m.order[i])} has no other neighbour left, so no new entries appear.`
        : `${cellName(m.order[i])} is the root: nothing to fold into. Forward sweep done.` });
  }
  for (let i = n - 1; i >= 0; i--) {
    const p = m.dsIdx[i];
    z[i] = p < 0 ? rhs[i] / diag[i] : (rhs[i] - off[i] * z[p]) / diag[i];
    frames.push({ diag: [...diag], rhs: [...rhs], z: [...z], done: n, active: i, phase: 'back',
      note: p < 0
        ? `Back-substitution starts at the root: z = rhs / diag = ${f2(z[i])}.`
        : `${cellName(m.order[i])}: its parent ${cellName(m.order[p])} is already solved, so z = (rhs − off·z_parent) / diag = ${f2(z[i])}.` });
  }
  return { frames, d0, off, b0 };
}

/** A second downstream link for the "non-tree" demo: the first cell with a lower 8-neighbour that is not its parent. */
function extraLink(m: TreeModel): [number, number] | null {
  for (let i = 0; i < m.order.length; i++) {
    const f = m.order[i], r = Math.floor(f / m.nx), c = f % m.nx;
    for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
      const rr = r + dr, cc = c + dc;
      if ((!dr && !dc) || rr < 0 || cc < 0 || rr >= m.ny || cc >= m.nx) continue;
      const j = m.pos[rr * m.nx + cc];
      if (j > i && j !== m.dsIdx[i] && m.dsIdx[j] !== i && m.dsIdx[i] >= 0 && m.filled[rr * m.nx + cc] < m.filled[f]) return [i, j];
    }
  }
  return null;
}

export default function ThreeWalksWidget() {
  const P = PRESETS.mini;
  const m = useMemo(() => buildModel(P.z, P.ny, P.nx), [P]);
  const n = m.order.length;
  const kids = useMemo(() => childrenOf(m.dsIdx), [m]);

  const [walk, setWalk] = useState<Walk>('explicit');
  const [ok, setOk] = useState<OrderKind>('natural');
  const [seed, setSeed] = useState(3);
  const [k, setK] = useState(0);
  const [play, setPlay] = useState(false);
  const [store, setStore] = useState(0.5);
  const [nonTree, setNonTree] = useState(false);

  const visit = useMemo(() => (ok === 'natural' ? m.order.map((_, i) => i) : shuffled(n, seed)), [ok, seed, n, m]);
  const ex = useMemo(() => explicitFrames(m, visit), [m, visit]);
  const exNat = useMemo(() => explicitFrames(m, m.order.map((_, i) => i)), [m]);
  const im = useMemo(() => implicitFrames(m, store), [m, store]);
  const link = useMemo(() => extraLink(m), [m]);
  const fill = useMemo(() => {
    const links: [number, number][] = m.dsIdx.flatMap((d, i) => (d >= 0 ? [[i, d] as [number, number]] : []));
    if (nonTree && link) links.push(link);
    return eliminationFill(n, links);
  }, [m, n, nonTree, link]);

  const nFrames = walk === 'explicit' ? ex.frames.length : walk === 'mc' ? n + 1 : im.frames.length;
  useEffect(() => { setK(0); setPlay(false); }, [walk, ok, seed, store, nonTree]);
  useEffect(() => {
    if (!play) return;
    if (k >= nFrames - 1) { setPlay(false); return; }
    const t = setTimeout(() => setK((x) => x + 1), 700);
    return () => clearTimeout(t);
  }, [play, k, nFrames]);

  // ── per-walk state for the current frame ──
  let nodeText: (p: number) => React.ReactNode = () => null;
  let nodeFill: (p: number) => string | undefined = () => undefined;
  let nodeStroke: (p: number) => string | undefined = () => undefined;
  let note: React.ReactNode = '';
  let caption = '';
  let side: React.ReactNode = null;

  if (walk === 'explicit') {
    const fr = ex.frames[Math.min(k, ex.frames.length - 1)];
    const finalNat = exNat.frames[exNat.frames.length - 1].inflow;
    const finalNow = ex.frames[ex.frames.length - 1].inflow;
    const diff = Math.max(...finalNow.map((v, i) => Math.abs(v - finalNat[i])));
    const act = new Set(fr.active);
    const targets = new Set(fr.active.length === 1 ? [m.dsIdx[fr.active[0]]] : []);
    caption = k === 0 ? 'number = outflow this step' : 'number = inflow collected so far';
    nodeText = (p) => (k === 0 ? f2(ex.O[p]) : f2(fr.inflow[p]));
    nodeFill = (p) => (act.has(p) ? '#fef3c7' : targets.has(p) ? '#ede9fe' : undefined);
    nodeStroke = (p) => (act.has(p) ? T.current : targets.has(p) ? T.downstream : undefined);
    note = fr.note;
    side = (
      <>
        <pre className="text-[11.5px] bg-slate-900 text-slate-100 rounded-lg p-3 overflow-x-auto">{`# router.py, kinematic & diffusive (every step)
Q_out = manning(h)                  # phase 1: all cells at once
inflow.fill(0)
scatter_add(inflow, ds_idx[valid],  # phase 2: np.add.at on CPU,
            Q_out[valid] * dt)      #   atomic adds on the GPU
V += inflow - Q_out * dt + rain     # phase 3: all at once`}</pre>
        <div className="grid grid-cols-2 gap-2 mt-3">
          <Stat label="inflow at the outlet" value={f2(fr.inflow[n - 1])} />
          <Stat label="vs. upstream-first order" value={k === ex.frames.length - 1 ? (diff < 1e-12 ? 'identical ✓' : `differs ${diff.toExponential(1)}`) : 'run to the end'} tone={k === ex.frames.length - 1 ? 'green' : 'slate'} />
        </div>
        <p className="text-[12.5px] text-slate-600 mt-2">
          Adding up does not care about order (2 + 3 = 3 + 2), so the visiting order <b>never</b> matters here. That is why this walk runs as one
          parallel pass on a GPU. The only care needed is at a confluence, where several cells write into the same inflow at once: hence <b>atomic</b> adds.
        </p>
      </>
    );
  } else if (walk === 'mc') {
    const now = mcRun(m, visit, k);
    const fin = mcRun(m, visit, n);
    const ref = mcRun(m, m.order.map((_, i) => i), n);
    const seen = new Set(visit.slice(0, k));
    const missed = new Set<number>();
    visit.forEach((i, s) => { if (kids[i].some((c) => visit.indexOf(c) > s)) missed.add(i); });
    const cur = k > 0 ? visit[k - 1] : -1;
    caption = 'number = new outflow O₂ · ✗ = visited too early';
    nodeText = (p) => (seen.has(p) ? `${f2(now.O2[p])}${missed.has(p) ? '✗' : ''}` : '·');
    nodeFill = (p) => (p === cur ? '#fef3c7' : seen.has(p) ? (missed.has(p) ? '#fee2e2' : '#e0f2fe') : undefined);
    nodeStroke = (p) => (p === cur ? T.current : seen.has(p) && missed.has(p) ? T.bad : undefined);
    note = cur < 0
      ? 'Each cell needs its new inflow I₂ before it can work out its new outflow O₂, so cells are visited one at a time.'
      : <>Visit {cellName(m.order[cur])}: O₂ = {MC.C0}·I₂ + {MC.C1}·I₁ + {MC.C2}·O₁ + {MC.C3}·q = {MC.C0}·{f2(now.I2[cur])} + 0 + 0 + 1 = <b>{f2(now.O2[cur])}</b>
        {missed.has(cur) ? <span className="text-red-700 font-semibold"> ✗ visited before {kids[cur].filter((c) => visit.indexOf(c) > k - 1).map((c) => cellName(m.order[c])).join(', ')}: that inflow is missed.</span> : null}</>;
    const outlet = n - 1;
    side = (
      <>
        <pre className="text-[11.5px] bg-slate-900 text-slate-100 rounded-lg p-3 overflow-x-auto">{`# hydraulics._mc_sweep (numba)
for i in range(n):           # upstream first: ds_idx[i] > i
    o = C0[i]*I2[i] + C1[i]*I1[i] + C2[i]*O1[i] + C3[i]*Q_L[i]
    O2[i] = max(o, 0)
    I2[ds_idx[i]] += O2[i]   # finished before ds is visited`}</pre>
        <div className="grid grid-cols-2 gap-2 mt-3">
          <Stat label="outflow at the outlet" value={k === n ? f2(fin.O2[outlet]) : '…'} tone={k === n && Math.abs(fin.O2[outlet] - ref.O2[outlet]) > 1e-9 ? 'red' : 'slate'} />
          <Stat label="upstream-first gives" value={f2(ref.O2[outlet])} tone="green" />
        </div>
        <p className="text-[12.5px] text-slate-600 mt-2">
          Every cell gets 1 m³/s of local runoff (q), starting dry, with the step&apos;s weights C₀ = {MC.C0}, C₁ = {MC.C1}, C₂ = {MC.C2}, C₃ = {MC.C3}.
          Shuffle the order and cells marked ✗ are visited before a cell that feeds them, so their inflow is incomplete and the outlet
          gets less water. Here the order is not about speed: it is what makes the answer right.
        </p>
      </>
    );
  } else {
    const fr = im.frames[Math.min(k, im.frames.length - 1)];
    const finite = fr.diag.every(Number.isFinite) && fr.rhs.every(Number.isFinite) && fr.z.every((v) => Number.isNaN(v) || Number.isFinite(v));
    const solved = fr.phase === 'back' && fr.active === 0;
    let resid = NaN;
    if (solved) {
      const z = sweepSolve(im.d0, im.off, m.dsIdx, m.dsIdx.map((d) => d < 0), im.b0);
      resid = 0;
      for (let i = 0; i < n; i++) {
        let row = im.d0[i] * z[i];
        if (m.dsIdx[i] >= 0) row += im.off[i] * z[m.dsIdx[i]];
        for (const c of kids[i]) row += im.off[c] * z[c];
        resid = Math.max(resid, Math.abs(row - im.b0[i]));
      }
    }
    const fillNow = nonTree ? fill.filter(([, , v]) => fr.phase !== 'start' && v <= fr.done) : [];
    const fillSet = new Set(fillNow.flatMap(([a, b]) => [`${a},${b}`, `${b},${a}`]));
    const cs = 20, lab = 18;
    caption = nonTree ? '' : fr.phase === 'back' ? 'number = solved level z (or diagonal, not solved yet)' : 'number = diagonal entry M_ii';
    nodeText = (p) => (nonTree ? null : fr.phase === 'back' && Number.isFinite(fr.z[p]) ? f2(fr.z[p]) : f2(fr.diag[p]));
    nodeFill = (p) => (p === fr.active ? '#fef3c7' : fr.phase === 'fold' && p <= fr.done ? '#f1f5f9' : fr.phase === 'back' && Number.isFinite(fr.z[p]) ? '#dcfce7' : undefined);
    nodeStroke = (p) => (p === fr.active ? T.current : fr.phase === 'fold' && p === m.dsIdx[fr.active] ? T.downstream : undefined);
    note = nonTree
      ? <>With the extra link {link ? `${cellName(m.order[link[0]])} → ${cellName(m.order[link[1]])}` : ''}, folding a cell that has <b>two</b> neighbours further down creates a new entry between them (✚, fill-in). That is the sparse-solver problem a tree never has.</>
      : fr.note;
    side = (
      <>
        {!finite && <Unstable msg="the elimination divided by zero. Raise the storage term A/Δt." />}
        <div className="overflow-x-auto">
          <svg viewBox={`0 0 ${lab + n * cs + 70} ${lab + n * cs + 4}`} width={lab + n * cs + 70} height={lab + n * cs + 4} role="img"
            aria-label="The matrix M: rows and columns are cells in topological order; marks show non-zero entries">
            {m.order.map((f, i) => (
              <g key={i}>
                <text x={lab + i * cs + cs / 2} y={12} fontSize={10} textAnchor="middle" fontWeight={700} fill="#334155">{cellName(f)}</text>
                <text x={9} y={lab + i * cs + cs / 2 + 4} fontSize={10} textAnchor="middle" fontWeight={700} fill="#334155">{cellName(f)}</text>
              </g>
            ))}
            {m.order.map((_, i) => m.order.map((__, j) => {
              const x = lab + j * cs, y = lab + i * cs;
              const isDiag = i === j;
              const isTree = m.dsIdx[i] === j || m.dsIdx[j] === i;
              const isExtra = nonTree && link && ((link[0] === i && link[1] === j) || (link[0] === j && link[1] === i));
              const isFill = fillSet.has(`${i},${j}`);
              const gone = fr.phase !== 'start' && (i <= fr.done || j <= fr.done) && !isDiag && fr.phase === 'fold';
              const hot = !nonTree && fr.phase === 'fold' && i === j && i === m.dsIdx[fr.active];
              return (
                <g key={`${i}-${j}`}>
                  <rect x={x} y={y} width={cs - 1} height={cs - 1} fill={hot ? '#fef3c7' : isFill ? '#fee2e2' : gone ? '#f1f5f9' : '#fff'} stroke="#e2e8f0" />
                  {isDiag && <circle cx={x + cs / 2} cy={y + cs / 2} r={4.5} fill={hot ? T.current : '#0f172a'} opacity={fr.phase === 'fold' && i <= fr.done ? 0.35 : 1} />}
                  {isTree && !isDiag && <text x={x + cs / 2} y={y + cs / 2 + 4} fontSize={10} textAnchor="middle" fill={gone ? '#94a3b8' : T.edge} fontWeight={700}>−1</text>}
                  {isExtra && <text x={x + cs / 2} y={y + cs / 2 + 4} fontSize={11} textAnchor="middle" fill={T.backward} fontWeight={700}>◆</text>}
                  {isFill && <text x={x + cs / 2} y={y + cs / 2 + 4} fontSize={12} textAnchor="middle" fill={T.bad} fontWeight={900}>✚</text>}
                </g>
              );
            }))}
            {!nonTree && m.order.map((_, i) => (
              <text key={`b${i}`} x={lab + n * cs + 6} y={lab + i * cs + cs / 2 + 4} fontSize={9.5} fontFamily="monospace" fill="#334155">
                {fr.phase === 'back' && Number.isFinite(fr.z[i]) ? `z=${f2(fr.z[i])}` : `b=${f2(fr.rhs[i])}`}
              </text>
            ))}
          </svg>
        </div>
        <p className="text-[11px] text-slate-500 mt-1">● diagonal · −1 = a cell and its downstream cell · grey = already folded{nonTree ? ' · ◆ the extra link · ✚ fill-in (a new non-zero)' : ''}</p>
        <div className="grid grid-cols-2 gap-2 mt-2">
          {nonTree
            ? <><Stat label="fill-in entries" value={`${fillNow.length} of ${fill.length}`} tone={fill.length ? 'red' : 'green'} /><Stat label="tree only" value="0 always" tone="green" /></>
            : <><Stat label="fill-in entries" value="0 ✓" tone="green" /><Stat label="check |M z − b|" value={solved ? resid.toExponential(0) : 'run to the end'} tone={solved ? 'green' : 'slate'} /></>}
        </div>
        {!nonTree && (
          <div className="mt-3">
            <Slider label="Storage term A/Δt on the diagonal" value={store} min={0.02} max={2} step={0.02} display={store.toFixed(2)} onChange={setStore}
              hint="Small = a huge time step. The solve still works: every row keeps a diagonal at least as big as its off-diagonals." />
          </div>
        )}
      </>
    );
  }

  return (
    <WidgetFrame
      title="One tree, three walks"
      idea="All three of MRRpy's channel schemes use the same tree, but they walk it differently, and only two of them care about the order."
    >
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <Toggle label="Scheme" value={walk} onChange={setWalk} options={[
          { value: 'explicit', label: '1 · Kinematic / diffusive' },
          { value: 'mc', label: '2 · Muskingum–Cunge' },
          { value: 'implicit', label: '3 · Semi-implicit' },
        ]} />
        {walk !== 'implicit' ? (
          <>
            <Toggle label="Visiting order" value={ok} onChange={setOk} options={[
              { value: 'natural', label: 'Upstream first (MRRpy)' }, { value: 'shuffled', label: 'Shuffled' }]} />
            {ok === 'shuffled' && <Btn onClick={() => setSeed((s) => s + 1)}>🔀 Reshuffle</Btn>}
          </>
        ) : (
          <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 cursor-pointer">
            <input type="checkbox" checked={nonTree} onChange={(e) => setNonTree(e.target.checked)} className="accent-sky-600" />
            Add one non-tree link (a cell sending water two ways, as MFD / D∞ do)
          </label>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-3">
        <Btn onClick={() => setK(0)}>⏮ Reset</Btn>
        <Btn onClick={() => setK((x) => Math.max(0, x - 1))} disabled={k === 0}>◀ Back</Btn>
        <Btn onClick={() => setK((x) => Math.min(nFrames - 1, x + 1))} disabled={k >= nFrames - 1}>Step ▶</Btn>
        <Btn primary onClick={() => { if (k >= nFrames - 1) setK(0); setPlay((p) => !p); }}>{play ? '⏸ Pause' : '▶ Play'}</Btn>
        <span className="text-xs text-slate-500 tabular-nums">frame {k + 1} / {nFrames}</span>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] items-start">
        <div>
          <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-3 items-start">
            <div>
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Map</p>
              <GridView m={m} size={40}
                extra={walk === 'implicit' && nonTree && link ? (f, x, y, s) => {
                  if (f !== m.order[link[0]]) return null;
                  const g = m.order[link[1]];
                  const x2 = (g % m.nx + 0.5) * s, y2 = (Math.floor(g / m.nx) + 0.5) * s;
                  return <line x1={x + s / 2} y1={y + s / 2} x2={x + s / 2 + (x2 - x - s / 2) * 0.8} y2={y + s / 2 + (y2 - y - s / 2) * 0.8}
                    stroke={T.backward} strokeWidth={3} strokeDasharray="4 3" pointerEvents="none" />;
                } : undefined} />
            </div>
            <div>
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Tree <span className="normal-case font-normal tracking-normal">· {caption}</span></p>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-1">
                <TreeView m={m} compact rowGap={56} nodeText={nodeText} nodeFill={nodeFill} nodeStroke={nodeStroke} />
              </div>
            </div>
          </div>
          <div className="mt-2"><RoleLegend /></div>
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[13px] text-slate-800 min-h-[64px]" aria-live="polite">{note}</div>
        </div>
        <div className="min-w-0">{side}</div>
      </div>

      <LookFor items={[
        <><b>Kinematic / diffusive:</b> shuffle as much as you like, the inflows come out the same. Order only matters inside a step when one cell needs another cell&apos;s <i>new</i> value.</>,
        <><b>Muskingum–Cunge</b> needs exactly that (O₂ needs this step&apos;s I₂), so it must go upstream-first. A shuffled order drops water at every ✗.</>,
        <><b>Semi-implicit:</b> folding leaves into parents never creates a new entry (no ✚), so the whole solve is two passes. Add one non-tree link and ✚ appears.</>,
      ]} />
    </WidgetFrame>
  );
}
