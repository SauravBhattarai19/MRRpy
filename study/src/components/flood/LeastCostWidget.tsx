'use client';

// §7.3 — never map on the filled DEM. A small valley with an embankment (a
// bridge or DEM "dam") across it. Left: the usual conditioning — fill the DEM,
// then follow D8: the land behind the embankment becomes a flat and the river
// crosses it in straight lines. Right: MRRpy's least-cost search on the DEM as
// it is (leastCostD8): the river stays in its channel. The search can be
// stepped through: cells are reached lowest first, like a lake rising from
// the outlet, and each drains to the cell it was reached from.

import React, { useEffect, useMemo, useState } from 'react';
import {
  MOVE, downstreamFirstOrder, downstreamFromD8, leastCostD8, upstreamArea, type SearchStep,
} from '@/lib/flood/hand';
import { C, Legend, LookFor, Slider, Stat, Unstable, WidgetFrame } from './ui';

const NY = 26, NX = 21, DX = 30;
const EMB_ROW = 16;
const ENTER_CELLS = 300; // drainage entering at the top, in cells
const RIVER_CELLS = 40; // a cell is a river cell when this many cells drain to it
const CS = 20; // drawing size of a cell

function noise(r: number, c: number) {
  const s = Math.sin(r * 12.9898 + c * 78.233) * 43758.5453;
  return (s - Math.floor(s) - 0.5) * 0.16;
}

function baseDem(emb: number): Float64Array {
  const z = new Float64Array(NY * NX);
  const vc = 10 * DX;
  for (let r = 0; r < NY; r++) for (let c = 0; c < NX; c++) {
    const y = r * DX, x = c * DX;
    const xc = vc + 3 * DX * Math.sin((2 * Math.PI * r) / 20);
    const dv = Math.abs(x - vc), d = Math.abs(x - xc);
    let v = 100 - 0.004 * y + (dv < 240 ? 0.004 * dv : 0.96 + 0.12 * (dv - 240));
    v -= d < 20 ? 1.2 : d < 45 ? (1.2 * (45 - d)) / 25 : 0; // the river channel
    v += noise(r, c);
    if (r === EMB_ROW && dv < 260) v = Math.max(v, 100 - 0.004 * EMB_ROW * DX + emb); // embankment
    z[r * NX + c] = v;
  }
  return z;
}

// green-grey land ramp, so the orange of raised cells stands out
const RAMP: [number, number, number][] = [[38, 70, 53], [74, 116, 82], [134, 166, 116], [200, 212, 176], [244, 244, 232]];
function rampCss(t: number) {
  const x = Math.min(Math.max(t, 0), 1) * (RAMP.length - 1);
  const k = Math.min(Math.floor(x), RAMP.length - 2), f = x - k;
  return `rgb(${[0, 1, 2].map((j) => Math.round(RAMP[k][j] + f * (RAMP[k + 1][j] - RAMP[k][j]))).join(',')})`;
}

interface Net { d8: Uint8Array; ds: Int32Array; dist: Float64Array; acc: Float64Array; riverKm: number }
function network(z: Float64Array, d8: Uint8Array, entry: number): Net {
  const { ds, dist } = downstreamFromD8(d8, NY, NX, DX);
  const order = downstreamFirstOrder(ds);
  const extra = new Float64Array(NY * NX);
  extra[entry] = ENTER_CELLS;
  const acc = upstreamArea(order, ds, 1, extra);
  let len = 0;
  for (let i = 0; i < acc.length; i++) if (acc[i] >= RIVER_CELLS && ds[i] >= 0) len += dist[i];
  return { d8, ds, dist, acc, riverKm: len / 1000 };
}

export default function LeastCostWidget() {
  const [emb, setEmb] = useState(2.5);
  const [edits, setEdits] = useState<Float64Array>(() => new Float64Array(NY * NX));
  const [k, setK] = useState<number | null>(null); // search step shown (null = finished)
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(6);

  const model = useMemo(() => {
    const z = baseDem(emb);
    for (let i = 0; i < z.length; i++) z[i] += edits[i];
    let out = 0;
    for (let c = 1; c < NX; c++) if (z[(NY - 1) * NX + c] < z[(NY - 1) * NX + out]) out = c;
    let ent = 0;
    for (let c = 1; c < NX; c++) if (z[c] < z[ent]) ent = c;
    const noOutlet = new Uint8Array(NY * NX).fill(1);
    noOutlet[(NY - 1) * NX + out] = 0;
    const filled = leastCostD8(z, NY, NX, { noOutlet, fill: true });
    const steps: SearchStep[] = [];
    const lc = leastCostD8(z, NY, NX, { noOutlet, steps });
    const reachedAt = new Int32Array(NY * NX).fill(-1);
    steps.forEach((s, j) => s.reached.forEach((c) => { reachedAt[c] = j; }));
    const raise = Float64Array.from(filled.zFilled, (v, i) => v - z[i]);
    let nRaised = 0, maxRaise = 0;
    for (const r of raise) { if (r > 0.05) nRaised++; maxRaise = Math.max(maxRaise, r); }
    let zLo = Infinity, zHi = -Infinity;
    for (const v of z) { zLo = Math.min(zLo, v); zHi = Math.max(zHi, v); }
    return {
      z, zLo, zHi: Math.min(zHi, zLo + 6), outlet: (NY - 1) * NX + out, raise, nRaised, maxRaise,
      fill: network(filled.zFilled, filled.d8, ent), lc: network(z, lc.d8, ent),
      steps, order: lc.reachOrder, reachedAt,
    };
  }, [emb, edits]);

  const total = model.steps.length;
  const kk = k === null ? total : Math.min(k, total);

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setK((x) => {
        const nx = (x === null ? total : x) + speed;
        if (nx >= total) { setPlaying(false); return null; }
        return nx;
      });
    }, 60);
    return () => clearInterval(id);
  }, [playing, speed, total]);

  const ok = model.z.every(Number.isFinite) && Number.isFinite(model.maxRaise);

  const edit = (i: number, e: React.MouseEvent) => {
    const d = e.type === 'contextmenu' || e.button === 2 ? -1 : 1;
    setEdits((old) => { const n = Float64Array.from(old); n[i] += d; return n; });
  };

  // queue at step kk: reached, not yet taken
  const queue = useMemo(() => {
    if (kk >= total) return [];
    const q: number[] = [];
    for (let i = 0; i < NY * NX; i++) {
      const reached = i === model.outlet || (model.reachedAt[i] >= 0 && model.reachedAt[i] < kk);
      if (reached && model.order[i] >= kk) q.push(i);
    }
    q.sort((a, b) => model.z[a] - model.z[b] || model.reachedAt[a] - model.reachedAt[b]);
    return q;
  }, [kk, total, model]);

  const cur = kk > 0 && kk <= total && kk < total ? model.steps[kk - 1] : null;

  return (
    <WidgetFrame tone="earth"
      title="Never map on a filled DEM"
      idea={<>Filling a DEM raises the land behind a bridge or embankment into a flat, and the river then crosses the flat in straight lines. The least-cost search keeps every elevation as it is: the river stays in its channel and crosses the embankment at its lowest point.</>}>
      {!ok && <Unstable msg="a cell elevation became non-finite; press Reset edits." />}
      <div className="flex flex-col lg:flex-row gap-4">
        <Panel title="(a) Fill the DEM, then follow D8" subtitle="what most tools map on" model={model} net={model.fill}
          mode="fill" onEdit={edit} />
        <Panel title="(b) Least-cost search on the DEM as it is" subtitle="what MRRpy maps on" model={model} net={model.lc}
          mode="lc" step={kk} cur={cur} onEdit={edit} />
      </div>

      <div className="mt-3 flex flex-col lg:flex-row gap-4">
        <div className="flex-1 flex flex-col gap-3">
          <Slider label="Embankment height above the valley floor" value={emb} min={0} max={5} step={0.25}
            display={`+${emb.toFixed(2)} m`} onChange={(v) => { setEmb(v); setK(null); }}
            hint="Left click a cell: +1 m. Right click: −1 m. Try building a second embankment." />
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-slate-600 mr-1">Watch the search in (b):</span>
            <Btn onClick={() => { setK(0); setPlaying(true); }}>▶ Play from start</Btn>
            <Btn onClick={() => setPlaying((p) => !p)} disabled={k === null && !playing}>{playing ? '❚❚ Pause' : '▶ Resume'}</Btn>
            <Btn onClick={() => { setPlaying(false); setK(Math.max((k ?? total) - 1, 0)); }}>◀ Back</Btn>
            <Btn onClick={() => { setPlaying(false); const n = (k ?? total) + 1; setK(n >= total ? null : n); }}>Step ▶</Btn>
            <Btn onClick={() => { setPlaying(false); setK(null); }}>Show result</Btn>
            <Btn onClick={() => { setEdits(new Float64Array(NY * NX)); setK(null); }}>Reset edits</Btn>
          </div>
          <Slider label="Search speed" value={speed} min={1} max={30} step={1} display={`${speed} cells per tick`} onChange={setSpeed} />
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="Cells raised by filling" value={`${model.nRaised}`} tone="red" />
            <Stat label="Largest raise" value={`${model.maxRaise.toFixed(1)} m`} tone="red" />
            <Stat label="River length (a)" value={`${model.fill.riverKm.toFixed(2)} km`} />
            <Stat label="River length (b)" value={`${model.lc.riverKm.toFixed(2)} km`} tone="sky" />
          </div>
        </div>
        <div className="lg:w-72 flex flex-col gap-3">
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[12px] text-slate-700">
            <div className="font-semibold text-slate-800 mb-1">
              {kk < total ? `Search step ${kk} of ${total}` : 'Next lowest cells in the queue'}
            </div>
            {kk < total ? (
              <ol className="font-mono text-[11.5px] leading-5">
                {queue.slice(0, 6).map((i, j) => (
                  <li key={i} className={j === 0 ? 'text-amber-700 font-bold' : ''}>
                    {j === 0 ? '→ ' : '  '}row {Math.floor(i / NX)}, col {i % NX}: z = {model.z[i].toFixed(2)} m
                  </li>
                ))}
                {queue.length > 6 && <li className="text-slate-400">… {queue.length - 6} more</li>}
              </ol>
            ) : (
              <p>Press <b>Play from start</b>: the search starts at the outlet, always takes the lowest cell it has reached, and lets its new neighbours drain to it.</p>
            )}
          </div>
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-[12px] text-amber-900 leading-snug">
            <b>Kathmandu, 2024.</b> On the filled DEM, 31% of a central window was raised by more than 0.5 m (up to 17 m) and
            the first maps showed straight flood stripes across the city. On the DEM as it is, with least-cost paths, the flooded
            area of a design storm fell from 29.7 to 11.0 km² (30 m maps), and the rivers followed their real courses.
          </div>
        </div>
      </div>

      <Legend items={[
        { swatch: rampCss(0.1), label: 'low ground' },
        { swatch: rampCss(0.9), label: 'high ground' },
        { swatch: C.raised, label: 'raised by filling (+m written in)' },
        { swatch: <span className="inline-block w-4 h-1.5 rounded" style={{ background: C.river }} />, label: 'river (≥ 40 cells drain to it)' },
        { swatch: <span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: C.bad }} />, label: 'embankment' },
        { swatch: 'rgba(127,179,221,0.88)', label: 'already reached by the search' },
        { swatch: C.current, label: 'cell being taken' },
        { swatch: C.downstream, label: 'its neighbours, now draining to it' },
      ]} />
      <LookFor items={[
        <>In <b>(a)</b> the orange cells were raised into a flat behind the embankment; the navy river crosses it in straight lines towards the spill point.</>,
        <>In <b>(b)</b> nothing is raised: the river follows its meandering channel and crosses the embankment where it is lowest.</>,
        <>Press <b>Play from start</b>: blue spreads uphill from the outlet, lowest cells first, like a lake rising. Each cell drains to the one that reached it.</>,
      ]} />
    </WidgetFrame>
  );
}

function Btn({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled}
      className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-amber-50 disabled:opacity-40">
      {children}
    </button>
  );
}

function Panel({ title, subtitle, model, net, mode, step, cur, onEdit }: {
  title: string; subtitle: string;
  model: { z: Float64Array; zLo: number; zHi: number; raise: Float64Array; order: Int32Array; reachedAt: Int32Array; outlet: number };
  net: Net; mode: 'fill' | 'lc'; step?: number; cur?: SearchStep | null;
  onEdit: (i: number, e: React.MouseEvent) => void;
}) {
  const W = NX * CS, H = NY * CS;
  const searching = mode === 'lc' && step !== undefined && step < (model.order.reduce((m, v) => Math.max(m, v), 0) + 1);
  const reachedSet = new Set(cur?.reached ?? []);
  const cells: React.ReactNode[] = [];
  const arrows: React.ReactNode[] = [];
  const texts: React.ReactNode[] = [];
  for (let i = 0; i < NY * NX; i++) {
    const r = Math.floor(i / NX), c = i % NX;
    const x = c * CS, y = r * CS;
    let fill = rampCss((model.z[i] - model.zLo) / (model.zHi - model.zLo));
    if (mode === 'fill' && model.raise[i] > 0.05) fill = C.raised;
    cells.push(
      <rect key={i} x={x} y={y} width={CS} height={CS} fill={fill} stroke="rgba(0,0,0,0.06)"
        onClick={(e) => onEdit(i, e)} onContextMenu={(e) => { e.preventDefault(); onEdit(i, e); }} style={{ cursor: 'pointer' }} />,
    );
    if (searching) {
      const taken = model.order[i] >= 0 && model.order[i] < step!;
      if (taken) cells.push(<rect key={`t${i}`} x={x} y={y} width={CS} height={CS} fill="rgba(127,179,221,0.88)" pointerEvents="none" />);
      if (cur && cur.cell === i) cells.push(<rect key={`c${i}`} x={x + 1} y={y + 1} width={CS - 2} height={CS - 2} fill={C.current} stroke={C.ink} pointerEvents="none" />);
      if (reachedSet.has(i)) cells.push(<rect key={`n${i}`} x={x + 2} y={y + 2} width={CS - 4} height={CS - 4} fill={C.downstream} pointerEvents="none" />);
    }
    if (mode === 'fill' && model.raise[i] > 1.45) {
      texts.push(<text key={`r${i}`} x={x + CS / 2} y={y + CS / 2 + 3} textAnchor="middle" fontSize={7} fill="#7c2d12" pointerEvents="none">+{model.raise[i].toFixed(1)}</text>);
    }
    // D8 arrow (during the search: only for cells already reached)
    const m = MOVE[net.d8[i]];
    const known = !searching || (model.reachedAt[i] >= 0 && model.reachedAt[i] < step!);
    if (m && known && !(mode === 'fill' && model.raise[i] > 1.45)) {
      const cx = x + CS / 2, cy = y + CS / 2;
      const ex = cx + m[1] * CS * 0.36, ey = cy + m[0] * CS * 0.36;
      arrows.push(<line key={`a${i}`} x1={cx - m[1] * CS * 0.2} y1={cy - m[0] * CS * 0.2} x2={ex} y2={ey}
        stroke="rgba(31,36,48,0.45)" strokeWidth={0.9} markerEnd="url(#lc-head)" pointerEvents="none" />);
    }
  }
  // the river: a thick line from every river cell to its downstream cell
  const river: React.ReactNode[] = [];
  if (!searching) for (let i = 0; i < NY * NX; i++) {
    const d = net.ds[i];
    if (net.acc[i] < RIVER_CELLS || d < 0) continue;
    const r = Math.floor(i / NX), c = i % NX, rd = Math.floor(d / NX), cd = d % NX;
    river.push(<line key={`v${i}`} x1={c * CS + CS / 2} y1={r * CS + CS / 2} x2={cd * CS + CS / 2} y2={rd * CS + CS / 2}
      stroke={C.river} strokeWidth={4.5} strokeLinecap="round" pointerEvents="none" />);
  }
  const or = Math.floor(model.outlet / NX), oc = model.outlet % NX;
  return (
    <div className="flex-1 min-w-0">
      <div className="text-sm font-bold text-slate-800">{title}</div>
      <div className="text-[11px] text-slate-500 mb-1">{subtitle}</div>
      <svg viewBox={`-2 -2 ${W + 4} ${H + 18}`} className="w-full rounded-lg border border-slate-300 bg-white select-none"
        role="img" aria-label={`${title}: grid of cells with flow arrows and the river path`}>
        <defs>
          <marker id="lc-head" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" orient="auto">
            <path d="M0,0 L6,3 L0,6 z" fill="rgba(31,36,48,0.6)" />
          </marker>
        </defs>
        {cells}
        {texts}
        {arrows}
        {river}
        <line x1={0} x2={W} y1={EMB_ROW * CS + CS / 2} y2={EMB_ROW * CS + CS / 2} stroke={C.bad} strokeWidth={1.2} strokeDasharray="5 4" pointerEvents="none" opacity={0.7} />
        <text x={4} y={EMB_ROW * CS - 3} fontSize={10} fill={C.bad} fontWeight={700} stroke="white" strokeWidth={3} paintOrder="stroke" pointerEvents="none">embankment</text>
        <text x={W / 2} y={11} textAnchor="middle" fontSize={10} fill={C.ink} fontWeight={600} stroke="white" strokeWidth={3} paintOrder="stroke" pointerEvents="none">river enters ↓</text>
        <text x={oc * CS + CS / 2} y={H + 13} textAnchor="middle" fontSize={10} fill={C.ink} fontWeight={700}>outlet ↓</text>
        <rect x={oc * CS} y={or * CS} width={CS} height={CS} fill="none" stroke={C.ink} strokeWidth={2} pointerEvents="none" />
      </svg>
    </div>
  );
}
