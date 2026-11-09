'use client';

// §7.6 — a synthetic rating curve built from the map. One reach, a river strip
// and three land cells: each land cell becomes a strip a/L wide at its HAND,
// every wet strip carries Manning flow, and their sum is Q(y). Computed with
// the package's own rating code (lib/flood/hand → rating.rating_curves).
// Defaults are the worked example of the inundation guide (Q(1.5) = 96.81 m³/s).

import React, { useMemo, useRef, useState } from 'react';
import { floodplainArea, ratingCurves, slotConveyance, stageFromQ, stageGrid } from '@/lib/flood/hand';
import { C, Legend, LookFor, Slider, Stat, Toggle, Unstable, WidgetFrame } from './ui';

const L = 1000; // reach length [m]
const AREAS = [30000, 60000, 90000]; // plan area of the three land cells [m²]
const STRIP_COL = ['#E69F00', '#009E73', '#CC79A7']; // Okabe–Ito
const STRIP_NAME = ['strip 1', 'strip 2', 'strip 3'];
const RIVER_COL = '#2B6CB0';
const Y_MAX = 3.5; // top of both pictures [m]
const Q_AX = 650; // right end of the curve's Q axis [m³/s]

function f2(x: number) { return x.toFixed(2); }

// ── tab 1: build a rating curve ─────────────────────────────────────────────
function Builder() {
  const [W, setW] = useState(40);
  const [nCh, setNCh] = useState(0.035);
  const [S, setS] = useState(0.001);
  const [nFp, setNFp] = useState(0.06);
  const [hands, setHands] = useState([0.5, 1.0, 2.0]);
  const [y, setY] = useState(1.5);
  const [mode, setMode] = useState<'stage' | 'discharge'>('stage');
  const [qT, setQT] = useState(150);
  const drag = useRef(false);

  // the package's rating table: 5 cm stages, one reach, three land cells
  const table = useMemo(() => {
    const ys = stageGrid(10);
    const cr = new Int32Array([0, 0, 0]);
    const hand = Float64Array.from(hands);
    const rc = ratingCurves(cr, hand, Float64Array.from(AREAS), new Float64Array(3).fill(nFp), 900,
      [L], [S], [W], [0], [nCh], ys);
    return { y: ys, Q: rc.Q[0] };
  }, [W, nCh, S, nFp, hands]);

  // per-strip arithmetic at a stage (the same formula, written out)
  const parts = (yy: number) => {
    const s = Math.sqrt(S);
    const river = s * slotConveyance(W, 0, nCh, yy);
    const strips = hands.map((h, k) => (yy > h ? (s / nFp) * (AREAS[k] / L) * Math.pow(yy - h, 5 / 3) : 0));
    return { river, strips, total: river + strips.reduce((a, b) => a + b, 0) };
  };

  // stage shown: dragged/slid (stage mode) or read off the curve (discharge mode)
  const inv = useMemo(() => {
    const st = stageFromQ(table.Q, table.y, qT);
    let lo = 0;
    while (lo < table.y.length - 2 && table.Q[lo + 1] < qT) lo++;
    return { y: st.stage, lo, hi: lo + 1, clipped: st.clipped };
  }, [table, qT]);
  const yShow = mode === 'stage' ? y : inv.y;
  const P = parts(yShow);
  const bad = !Number.isFinite(P.total) || table.Q.some((q) => !Number.isFinite(q));

  // slope sensitivity: the stage of the same Q on a reach twice as steep
  const sens = useMemo(() => {
    const q = P.total;
    if (!(q > 0)) return null;
    const q2 = Float64Array.from(table.Q, (x) => x * Math.SQRT2);
    const y2 = stageFromQ(q2, table.y, q).stage;
    const y1 = stageFromQ(table.Q, table.y, q).stage;
    return y1 > 0 ? (y1 - y2) / y1 : null;
  }, [table, P.total]);

  // ── cross-section geometry (metres across) ──
  // left: strip 2 · river · strip 1 · strip 3, with dry high ground at both ends
  const HILL = 25;
  const layout: { kind: 'hill' | 'river' | 'strip'; k: number; w: number; h: number }[] = [
    { kind: 'hill', k: -1, w: HILL, h: Y_MAX },
    { kind: 'strip', k: 1, w: AREAS[1] / L, h: hands[1] },
    { kind: 'river', k: -1, w: W, h: 0 },
    { kind: 'strip', k: 0, w: AREAS[0] / L, h: hands[0] },
    { kind: 'strip', k: 2, w: AREAS[2] / L, h: hands[2] },
    { kind: 'hill', k: -1, w: HILL, h: Y_MAX },
  ];
  const totalW = layout.reduce((a, b) => a + b.w, 0);
  const XW = 470, XH = 320, PL = 46, PR = 10, PT = 16, PB = 34;
  const sx = (m: number) => PL + (m / totalW) * (XW - PL - PR);
  const sy = (h: number) => PT + ((Y_MAX - Math.min(Math.max(h, -0.3), Y_MAX)) / (Y_MAX + 0.3)) * (XH - PT - PB);
  const yFromPx = (py: number) => Y_MAX - ((py - PT) / (XH - PT - PB)) * (Y_MAX + 0.3);

  const svgY = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
    return ((e.clientY - r.top) / r.height) * XH;
  };
  const setFromPointer = (e: React.PointerEvent<SVGSVGElement>) => {
    const v = Math.round(Math.min(Math.max(yFromPx(svgY(e)), 0), 3.2) * 100) / 100;
    setMode('stage');
    setY(v);
  };

  // ── curve geometry: stage up, Q to the right (shares the stage axis) ──
  const CW = 330, CPL = 52, CPR = 14;
  const cx = (q: number) => CPL + (Math.min(q, Q_AX) / Q_AX) * (CW - CPL - CPR);
  const stack = useMemo(() => {
    // cumulative layers: river, +strip 1, +strip 2, +strip 3 at every 5 cm
    const ys = Array.from(table.y).filter((v) => v <= Y_MAX + 1e-9);
    return ys.map((yy) => {
      const p = parts(yy);
      let acc = p.river;
      const cum = [p.river];
      for (const s of p.strips) { acc += s; cum.push(acc); }
      return { y: yy, cum };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table]);
  const layerPath = (j: number) => {
    const top = stack.map((s) => `${cx(s.cum[j])},${sy(s.y)}`);
    const bot = stack.map((s) => `${cx(j === 0 ? 0 : s.cum[j - 1])},${sy(s.y)}`).reverse();
    return `M${top.join('L')}L${bot.join('L')}Z`;
  };
  const curveLine = stack.map((s) => `${cx(s.cum[3])},${sy(s.y)}`).join(' ');

  let xRun = 0;
  return (
    <div className="flex flex-col gap-4">
      {bad && <Unstable msg="the rating curve produced a non-finite number; reset the sliders." />}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Toggle label="What you choose" value={mode} onChange={setMode}
          options={[{ value: 'stage', label: 'I set the water level → Q' }, { value: 'discharge', label: 'I set the discharge → water level' }]} />
        <span className="text-xs text-slate-500">Drag the blue water line up and down in the left picture.</span>
      </div>

      <div className="flex flex-col lg:flex-row gap-3">
        {/* (b) strip cross-section */}
        <div className="flex-[1.35] min-w-0">
          <div className="text-xs font-semibold text-slate-600 mb-1">Cross-section: each land cell laid out as a strip (width = area ÷ reach length)</div>
          <svg viewBox={`0 0 ${XW} ${XH}`} className="w-full rounded-lg border border-slate-200 bg-gradient-to-b from-sky-50 to-white touch-none select-none"
            style={{ cursor: 'ns-resize' }} role="img" aria-label="Cross-section with strips and a draggable water line"
            onPointerDown={(e) => { drag.current = true; (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId); setFromPointer(e); }}
            onPointerMove={(e) => { if (drag.current) setFromPointer(e); }}
            onPointerUp={() => { drag.current = false; }}>
            <defs>
              <pattern id="rc-dry" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2="6" stroke="#cbb994" strokeWidth="2" />
              </pattern>
            </defs>
            {layout.map((s, j) => {
              const x0 = xRun; xRun += s.w;
              const X0 = sx(x0), X1 = sx(x0 + s.w), xm = (X0 + X1) / 2;
              const wet = yShow > s.h && s.kind !== 'hill';
              const q = s.kind === 'river' ? P.river : s.kind === 'strip' ? P.strips[s.k] : 0;
              const col = s.kind === 'river' ? RIVER_COL : s.kind === 'strip' ? STRIP_COL[s.k] : '#a8a29e';
              return (
                <g key={j}>
                  {wet && <rect x={X0} y={sy(yShow)} width={X1 - X0} height={sy(s.h) - sy(yShow)} fill="#9CC3E6" opacity={0.85} />}
                  <rect x={X0} y={sy(s.h)} width={X1 - X0} height={sy(-0.3) - sy(s.h)} fill={s.kind === 'hill' ? 'url(#rc-dry)' : C.groundFill} />
                  <line x1={X0} x2={X1} y1={sy(s.h)} y2={sy(s.h)} stroke={col} strokeWidth={s.kind === 'hill' ? 1.5 : 4} />
                  {/* width label under the strip */}
                  {s.kind !== 'hill' && (
                    <text x={xm} y={XH - PB + 13} textAnchor="middle" fontSize={10} fill={col} fontWeight={700}>
                      {s.kind === 'river' ? 'river' : STRIP_NAME[s.k]}
                    </text>
                  )}
                  {s.kind !== 'hill' && (
                    <text x={xm} y={XH - PB + 25} textAnchor="middle" fontSize={9.5} fill={C.soft}>{s.w.toFixed(0)} m</text>
                  )}
                  {/* flow in the strip */}
                  {s.kind !== 'hill' && (wet ? (
                    <text x={xm} y={Math.min(sy(yShow) + (sy(s.h) - sy(yShow)) / 2 + 4, sy(s.h) - 4)} textAnchor="middle" fontSize={10.5} fontWeight={700} fill={C.river}>
                      {q.toFixed(1)}
                    </text>
                  ) : (
                    <text x={xm} y={sy(s.h) - 6} textAnchor="middle" fontSize={10.5} fill={C.soft} fontStyle="italic">dry</text>
                  ))}
                </g>
              );
            })}
            {/* the water line (draggable) */}
            <line x1={PL} x2={XW - PR} y1={sy(yShow)} y2={sy(yShow)} stroke={C.water} strokeWidth={2.5} strokeDasharray="7 4" />
            <rect x={XW - PR - 92} y={sy(yShow) - 21} width={90} height={17} rx={4} fill={C.water} />
            <text x={XW - PR - 47} y={sy(yShow) - 9} textAnchor="middle" fontSize={11} fill="white" fontWeight={700}>⇕ y = {f2(yShow)} m</text>
            <text x={sx(HILL) + 4} y={PT + 10} fontSize={10} fill={C.soft}>numbers in the water: m³/s each strip carries</text>
            {/* stage axis */}
            <line x1={PL} x2={PL} y1={PT} y2={XH - PB} stroke="#94a3b8" />
            {[0, 0.5, 1, 1.5, 2, 2.5, 3].map((m) => (
              <g key={m}>
                <line x1={PL - 4} x2={PL} y1={sy(m)} y2={sy(m)} stroke="#94a3b8" />
                <text x={PL - 7} y={sy(m) + 3.5} textAnchor="end" fontSize={10} fill={C.soft} fontFamily="monospace">{m}</text>
              </g>
            ))}
            <text x={13} y={(PT + XH - PB) / 2} fontSize={10.5} fill={C.ink} textAnchor="middle" transform={`rotate(-90 13 ${(PT + XH - PB) / 2})`}>
              height above the river (m)
            </text>
          </svg>
        </div>

        {/* (c) rating curve */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-slate-600 mb-1">Rating curve: add up the strips at every water level</div>
          <svg viewBox={`0 0 ${CW} ${XH}`} className="w-full rounded-lg border border-slate-200 bg-white" role="img"
            aria-label="Rating curve, stage against discharge, stacked by strip">
            {[0, 1, 2, 3].map((j) => (
              <path key={j} d={layerPath(j)} fill={j === 0 ? RIVER_COL : STRIP_COL[j - 1]} opacity={j === 0 ? 0.55 : 0.6} />
            ))}
            <polyline points={curveLine} fill="none" stroke={C.ink} strokeWidth={2} />
            {/* reading the curve */}
            {mode === 'discharge' ? (
              <g>
                <line x1={cx(qT)} x2={cx(qT)} y1={XH - PB} y2={sy(inv.y)} stroke={C.bad} strokeDasharray="4 3" strokeWidth={1.4} />
                <line x1={CPL} x2={cx(qT)} y1={sy(inv.y)} y2={sy(inv.y)} stroke={C.bad} strokeDasharray="4 3" strokeWidth={1.4} />
                <text x={cx(qT) + 4} y={XH - PB - 6} fontSize={10} fill={C.bad} fontWeight={700}>Q = {qT}</text>
              </g>
            ) : (
              <line x1={CPL} x2={cx(P.total)} y1={sy(yShow)} y2={sy(yShow)} stroke={C.water} strokeDasharray="7 4" strokeWidth={1.5} />
            )}
            <circle cx={cx(P.total)} cy={sy(yShow)} r={5} fill={C.bad} stroke="white" strokeWidth={1.5} />
            <text x={Math.min(cx(P.total) + 8, CW - 92)} y={sy(yShow) - 8} fontSize={11} fontWeight={700} fill={C.ink}>
              Q = {P.total.toFixed(1)} m³/s
            </text>
            {/* axes */}
            <line x1={CPL} x2={CPL} y1={PT} y2={XH - PB} stroke="#94a3b8" />
            <line x1={CPL} x2={CW - CPR} y1={XH - PB} y2={XH - PB} stroke="#94a3b8" />
            {[0, 1, 2, 3].map((m) => (
              <text key={m} x={CPL - 6} y={sy(m) + 3.5} textAnchor="end" fontSize={10} fill={C.soft} fontFamily="monospace">{m}</text>
            ))}
            {[0, 200, 400, 600].map((q) => (
              <text key={q} x={cx(q)} y={XH - PB + 13} textAnchor="middle" fontSize={10} fill={C.soft} fontFamily="monospace">{q}</text>
            ))}
            <text x={(CPL + CW - CPR) / 2} y={XH - 8} textAnchor="middle" fontSize={10.5} fill={C.ink}>discharge Q (m³/s)</text>
            <text x={14} y={(PT + XH - PB) / 2} fontSize={10.5} fill={C.ink} textAnchor="middle" transform={`rotate(-90 14 ${(PT + XH - PB) / 2})`}>
              stage y (m)
            </text>
          </svg>
          <div className="mt-1">
            <Legend items={[
              { swatch: RIVER_COL, label: 'river strip' },
              ...STRIP_COL.map((c, k) => ({ swatch: c, label: STRIP_NAME[k] })),
            ]} />
          </div>
        </div>
      </div>

      {/* controls */}
      {mode === 'stage' ? (
        <Slider label="Water level y (stage above the river)" value={y} min={0} max={3.2} step={0.05}
          display={`${f2(y)} m`} onChange={setY} />
      ) : (
        <Slider label="Discharge Q arriving in the reach" value={qT} min={0} max={420} step={1}
          display={`${qT} m³/s`} onChange={setQT} />
      )}

      <div className="flex flex-col lg:flex-row gap-4">
        {/* (a) plan view + arithmetic */}
        <div className="flex-1 min-w-0 flex flex-col gap-3">
          <PlanView W={W} hands={hands} y={yShow} />
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs font-mono text-slate-700 leading-relaxed overflow-x-auto">
            <div className="font-sans font-bold text-sm text-slate-800 mb-1">The sum at y = {f2(yShow)} m (√S = {Math.sqrt(S).toFixed(6)})</div>
            <div>river: (1/{nCh})·{W.toFixed(0)}·{f2(yShow)}<sup>5/3</sup>·√S = <b>{P.river.toFixed(2)}</b></div>
            {hands.map((h, k) => (
              <div key={k} style={{ color: STRIP_COL[k] === '#E69F00' ? '#a16207' : STRIP_COL[k] === '#009E73' ? '#047857' : '#9d174d' }}>
                {STRIP_NAME[k]}: {yShow > h
                  ? <>(1/{nFp})·{(AREAS[k] / L).toFixed(0)}·{f2(yShow - h)}<sup>5/3</sup>·√S = <b>{P.strips[k].toFixed(2)}</b></>
                  : <>dry (HAND {f2(h)} &gt; {f2(yShow)})</>}
              </div>
            ))}
            <div className="mt-1 text-slate-900">Q({f2(yShow)}) = <b>{P.total.toFixed(2)} m³/s</b></div>
            {mode === 'discharge' && !inv.clipped && qT > 0 && (
              <div className="mt-2 font-sans text-slate-700">
                Reading the table backwards: Q = {qT} lies between y = {f2(table.y[inv.lo])} (Q = {table.Q[inv.lo].toFixed(2)}) and
                y = {f2(table.y[inv.hi])} (Q = {table.Q[inv.hi].toFixed(2)}), so<br />
                <span className="font-mono">y = {f2(table.y[inv.lo])} + 0.05 × ({qT} − {table.Q[inv.lo].toFixed(2)}) / ({table.Q[inv.hi].toFixed(2)} − {table.Q[inv.lo].toFixed(2)}) = <b>{inv.y.toFixed(3)} m</b></span>
              </div>
            )}
          </div>
        </div>

        {/* sliders */}
        <div className="lg:w-80 flex flex-col gap-2.5">
          <Slider label="River width W" value={W} min={5} max={100} step={1} display={`${W} m`} onChange={setW} />
          <Slider label="River roughness n (channel)" value={nCh} min={0.02} max={0.08} step={0.001} display={nCh.toFixed(3)} onChange={setNCh} />
          <Slider label="Land roughness n (floodplain)" value={nFp} min={0.02} max={0.15} step={0.005} display={nFp.toFixed(3)} onChange={setNFp} />
          <Slider label="Bed slope S" value={Math.log10(S)} min={-4} max={-2} step={0.05} display={S.toExponential(1)}
            onChange={(v) => setS(Math.round(Math.pow(10, v) * 1e6) / 1e6)} />
          {hands.map((h, k) => (
            <Slider key={k} label={`HAND of ${STRIP_NAME[k]}`} value={h} min={0} max={3} step={0.05} display={`${f2(h)} m`}
              onChange={(v) => setHands(hands.map((x, j) => (j === k ? v : x)))} />
          ))}
          <button onClick={() => { setW(40); setNCh(0.035); setS(0.001); setNFp(0.06); setHands([0.5, 1, 2]); setY(1.5); setQT(150); }}
            className="self-start text-xs font-semibold rounded-lg border border-slate-300 px-3 py-1.5 text-slate-600 hover:bg-sky-50">
            Reset to the worked example
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <Stat label="Discharge at this level" value={`${P.total.toFixed(1)} m³/s`} tone="sky" />
        <Stat label="Share in the river strip" value={`${P.total > 0 ? ((100 * P.river) / P.total).toFixed(0) : '—'} %`} />
        <Stat label="Twice as steep a reach" value={sens !== null ? `stage ${(100 * sens).toFixed(0)} % lower` : '—'} tone="red" />
      </div>
      <p className="text-[12px] text-slate-500 -mt-2">
        Every term has √S, so the same Q stands lower on a steeper reach: stage ∝ S<sup>−0.3</sup> roughly, about 19 % lower for twice the slope.
        A wrong slope therefore moves the map.
      </p>
    </div>
  );
}

/** (a) the reach seen from above: the river strip and three land cells. */
function PlanView({ W, hands, y }: { W: number; hands: number[]; y: number }) {
  const PW = 470, PH = 110;
  const kx = (PW - 20) / L; // px per metre along the reach
  const rH = Math.max(Math.min(W * 0.5, 40), 3); // river drawn W·0.5 px wide
  const rY = PH / 2;
  const bh = (PH - rH) / 2 - 6; // land block height
  // blocks as wide as their area (same height): 90 000 m² → 200 px
  const blocks = [
    { k: 1, side: -1, x: 70 },
    { k: 0, side: 1, x: 40 },
    { k: 2, side: 1, x: 200 },
  ];
  return (
    <div>
      <div className="text-xs font-semibold text-slate-600 mb-1">Seen from above: one 1 km reach and the three land cells that drain to it</div>
      <svg viewBox={`0 0 ${PW} ${PH}`} className="w-full rounded-lg border border-slate-200 bg-[#f6f1e4]" role="img" aria-label="Plan view of the reach">
        <rect x={10} y={rY - rH / 2} width={L * kx} height={rH} fill={RIVER_COL} opacity={0.85} />
        <text x={PW - 14} y={rY + 4} textAnchor="end" fontSize={10} fill="white" fontWeight={700}>river, W = {W} m, 1 km long →</text>
        {blocks.map(({ k, side, x }) => {
          const w = (AREAS[k] / 90000) * 240;
          const yy = side < 0 ? rY - rH / 2 - bh - 3 : rY + rH / 2 + 3;
          const wet = y > hands[k];
          return (
            <g key={k}>
              <rect x={x} y={yy} width={w} height={bh} fill={STRIP_COL[k]} opacity={0.75} rx={2}
                stroke={wet ? C.water : '#78716c'} strokeWidth={wet ? 3 : 1} strokeDasharray={wet ? undefined : '3 2'} />
              <text x={x + w / 2} y={yy + bh / 2 - 2} textAnchor="middle" fontSize={9} fill={C.ink} fontWeight={600}>
                {(AREAS[k] / 1000).toFixed(0)} 000 m²
              </text>
              <text x={x + w / 2} y={yy + bh / 2 + 9} textAnchor="middle" fontSize={9} fill={C.ink}>
                HAND {hands[k].toFixed(1)}{wet ? ' · wet' : ' · dry'}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="text-[11px] text-slate-500 mt-0.5">Each cell is spread along the whole reach as a strip a ÷ 1000 m wide. Wet cells have a solid blue border.</div>
    </div>
  );
}

// ── tab 2: check against an exact answer ────────────────────────────────────
const VS = 1e-3, VN = 0.05, SV = 0.02;

function Check() {
  const [dx, setDx] = useState(30);
  const [yv, setYv] = useState(4);
  const res = useMemo(() => {
    const ys = stageGrid(6);
    const exact = Float64Array.from(ys, (y) => (Math.sqrt(VS) / VN) * (2 / SV) * (3 / 8) * Math.pow(y, 8 / 3));
    // the guide's construction (teach_hydraulics.fig_rating_verify): 20 rows of cells across the valley
    const J = Math.trunc(500 / dx), M = 20;
    const nAcross = 2 * J + 1;
    const hand = new Float64Array(nAcross * M), drain = new Uint8Array(nAcross * M);
    for (let m = 0; m < M; m++) for (let j = -J; j <= J; j++) {
      const i = m * nAcross + j + J;
      hand[i] = Math.abs(j) * dx * SV;
      drain[i] = j === 0 ? 1 : 0;
    }
    const n = hand.length;
    const cr = new Int32Array(n);
    const a = floodplainArea(cr, hand, drain, new Float64Array(n), new Float64Array(n).fill(dx), dx * dx, dx, 1);
    const rc = ratingCurves(cr, hand, a, new Float64Array(n).fill(VN), dx * dx, [M * dx], [VS], [0], [0], [VN], ys);
    const Q = rc.Q[0];
    const K = ys.length - 1;
    return { ys, exact, Q, err6: Math.abs(Q[K] - exact[K]) / exact[K], J };
  }, [dx]);
  const k = Math.round(yv / 0.05);
  const errY = res.exact[k] > 0 ? Math.abs(res.Q[k] - res.exact[k]) / res.exact[k] : 0;

  // V-valley picture
  const VW = 360, VH = 230, half = 400;
  const vx = (m: number) => 10 + ((m + half) / (2 * half)) * (VW - 20);
  const vy = (h: number) => 12 + ((8 - h) / 8) * (VH - 40);
  const steps = [];
  for (let j = -res.J; j <= res.J; j++) {
    const x0 = j * dx - dx / 2, x1 = j * dx + dx / 2;
    if (x1 < -half || x0 > half) continue;
    steps.push({ x0: Math.max(x0, -half), x1: Math.min(x1, half), h: Math.abs(j) * dx * SV });
  }
  // curve picture
  const CW = 360, CH = 230, cpl = 50;
  const qMax = res.exact[res.exact.length - 1] * 1.05;
  const qx = (y: number) => cpl + (y / 6) * (CW - cpl - 12);
  const qy = (q: number) => 12 + (1 - q / qMax) * (CH - 42);
  const line = (arr: Float64Array) => Array.from(res.ys, (y, i) => `${qx(y)},${qy(arr[i])}`).join(' ');

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-slate-600">
        A V-shaped valley with 2 % side slopes has an exact rating curve. Cut it into DEM cells, let the package&apos;s strips
        add them up, and compare.
      </p>
      <div className="flex flex-col lg:flex-row gap-3">
        <svg viewBox={`0 0 ${VW} ${VH}`} className="w-full lg:flex-1 min-w-0 rounded-lg border border-slate-200 bg-gradient-to-b from-sky-50 to-white" role="img" aria-label="V-shaped valley cut into cells">
          <polygon points={`${vx(-half)},${vy(half * SV)} ${vx(0)},${vy(0)} ${vx(half)},${vy(half * SV)} ${vx(half)},${vy(-0.4)} ${vx(-half)},${vy(-0.4)}`} fill={C.groundFill} />
          {steps.map((s, i) => yv > s.h && (
            <rect key={`w${i}`} x={vx(s.x0)} y={vy(yv)} width={vx(s.x1) - vx(s.x0)} height={vy(s.h) - vy(yv)} fill="#9CC3E6" opacity={0.85} />
          ))}
          <line x1={vx(-half)} y1={vy(half * SV)} x2={vx(0)} y2={vy(0)} stroke={C.ground} strokeWidth={1.4} />
          <line x1={vx(0)} y1={vy(0)} x2={vx(half)} y2={vy(half * SV)} stroke={C.ground} strokeWidth={1.4} />
          {steps.map((s, i) => (
            <line key={i} x1={vx(s.x0)} x2={vx(s.x1)} y1={vy(s.h)} y2={vy(s.h)} stroke={C.ink} strokeWidth={1.6} />
          ))}
          <text x={VW / 2} y={vy(yv) - 5} textAnchor="middle" fontSize={10.5} fill={C.river} fontWeight={700}>stage y = {yv.toFixed(2)} m</text>
          <text x={VW / 2} y={VH - 8} textAnchor="middle" fontSize={10} fill={C.soft}>black steps: the HAND of {dx} m cells · brown: the true valley</text>
        </svg>
        <svg viewBox={`0 0 ${CW} ${CH}`} className="w-full lg:flex-1 min-w-0 rounded-lg border border-slate-200 bg-white" role="img" aria-label="Exact and computed rating curves">
          <polyline points={line(res.exact)} fill="none" stroke={C.ink} strokeWidth={3} />
          <polyline points={line(res.Q)} fill="none" stroke="#D55E00" strokeWidth={2} strokeDasharray="6 4" />
          <line x1={qx(yv)} x2={qx(yv)} y1={12} y2={CH - 30} stroke="#94a3b8" strokeDasharray="3 3" />
          <line x1={cpl} x2={CW - 12} y1={CH - 30} y2={CH - 30} stroke="#94a3b8" />
          <line x1={cpl} x2={cpl} y1={12} y2={CH - 30} stroke="#94a3b8" />
          {[0, 2, 4, 6].map((v) => <text key={v} x={qx(v)} y={CH - 17} textAnchor="middle" fontSize={10} fill={C.soft} fontFamily="monospace">{v}</text>)}
          {[0, 1000, 2000, 3000].filter((q) => q <= qMax).map((q) => <text key={q} x={cpl - 5} y={qy(q) + 3} textAnchor="end" fontSize={10} fill={C.soft} fontFamily="monospace">{q}</text>)}
          <text x={(cpl + CW) / 2} y={CH - 3} textAnchor="middle" fontSize={10.5} fill={C.ink}>stage y (m) · up: Q (m³/s)</text>
          <text x={cpl + 8} y={26} fontSize={10.5} fill={C.ink} fontWeight={700}>── exact: (√S/n)(2/s_v)(3/8) y^8/3</text>
          <text x={cpl + 8} y={41} fontSize={10.5} fill="#D55E00" fontWeight={700}>- - MRRpy strips, {dx} m cells</text>
        </svg>
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        <Slider label="DEM cell size" value={dx} min={10} max={90} step={5} display={`${dx} m`} onChange={setDx} />
        <Slider label="Stage y" value={yv} min={0.5} max={6} step={0.05} display={`${yv.toFixed(2)} m`} onChange={setYv} />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <Stat label={`Exact Q at ${yv.toFixed(2)} m`} value={`${res.exact[k].toFixed(1)} m³/s`} />
        <Stat label="Strips differ by" value={`${(100 * errY).toFixed(1)} %`} tone={errY < 0.01 ? 'green' : 'red'} />
        <Stat label="At 6 m (guide: 0.4 % at 30 m)" value={`${(100 * res.err6).toFixed(1)} %`} tone={res.err6 < 0.01 ? 'green' : 'red'} />
      </div>
    </div>
  );
}

export default function RatingCurveWidget() {
  const [tab, setTab] = useState<'build' | 'check'>('build');
  return (
    <WidgetFrame
      title="Build a rating curve from the map"
      idea={<>Each cell that drains to a reach becomes a strip of floodplain at its HAND. Raise the water: every wet strip carries Manning flow, and their sum is the discharge Q(y) for that level.</>}
    >
      <div className="mb-4">
        <Toggle label="Tab" value={tab} onChange={setTab}
          options={[{ value: 'build', label: 'Build the curve' }, { value: 'check', label: 'Check against an exact answer' }]} />
      </div>
      {tab === 'build' ? <Builder /> : <Check />}
      <LookFor items={tab === 'build' ? [
        <>Drag the <b>water line</b>. A strip joins in only once the water is above its HAND, and the curve on the right bends there.</>,
        <>At low water the <span className="font-semibold text-sky-800">river strip</span> carries almost everything. Once the land goes under, the wide floodplain strips take over.</>,
        <>Switch to <b>I set the discharge</b>: the routed Q goes in, and the water level that the map draws comes out (Q = 150 m³/s gives y = 1.844 m).</>,
      ] : [
        <>The black steps are what a DEM sees: every cell is flat at its HAND.</>,
        <>At 30 m cells the strips stay within about 1 % of the exact curve (0.4 % at 6 m): the two lines lie on top of each other.</>,
        <>Make the cells smaller and the error goes to zero. The strip method is the integral, cut into cells.</>,
      ]} />
    </WidgetFrame>
  );
}
