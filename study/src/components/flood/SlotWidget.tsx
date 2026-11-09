'use client';

// §7.8 — why the flood maps cut no channel below the DEM. The DEM's river cell
// is already a water surface; a bankfull slot dug below it counts the river's
// capacity twice and pushes the mapped water down by about the slot depth.
// Live on the course valley with the package's rating code (D = slot depth).

import React, { useMemo, useState } from 'react';
import { handLevel, levelDepth, slotConveyance, stageFromQ } from '@/lib/flood/hand';
import { useValley } from './useValley';
import { C, DepthBar, Legend, Loading, LookFor, RasterCanvas, Slider, Stat, WidgetFrame, depthCss, depthRGB } from './ui';

const ROW = 130; // the slice of §7.1
const SIDE = 9; // land cells drawn either side of the river
const SLOT_COL = '#D97A1E';
const Y_TOP = 4, Y_BOT = -3.3;

export default function SlotWidget() {
  const v = useValley();
  const [D, setD] = useState(2.5);

  // HAND, reaches and the floodplain part of every rating curve: once
  const base = useMemo(() => {
    if (!v) return null;
    const g = v.grid, nx = v.data.nx;
    const lev = handLevel(g, g.river, v.data.aChannelKm2, { qPeak: v.q1 });
    const y = lev.rating.y;
    // floodplain conveyance part = total − river strip at D = 0 (independent of D)
    const Qfp = lev.rating.Q.map((Q, r) => Float64Array.from(Q, (q, k) => q - Math.sqrt(lev.S[r]) * slotConveyance(lev.W[r], 0, lev.nCh[r], y[k])));
    let main = -1;
    for (let c = 0; c < nx; c++) {
      const i = ROW * nx + c;
      if (g.river[i] && (main < 0 || g.area[i] > g.area[ROW * nx + main])) main = c;
    }
    const iMain = ROW * nx + main;
    const r = lev.cellReach[iMain];
    const side = (dir: number) => {
      const out: number[] = [];
      for (let k = 1; k <= SIDE; k++) {
        const c = main + dir * k;
        if (c >= 0 && c < nx) out.push(Number.isNaN(lev.hand[ROW * nx + c]) ? 9 : lev.hand[ROW * nx + c]);
      }
      return out;
    };
    return { lev, y, Qfp, r, left: side(-1).reverse(), right: side(1) };
  }, [v]);

  // the rating curves with a slot of depth d, every reach
  const curves = (d: number) => base!.Qfp.map((fp, r) =>
    Float64Array.from(fp, (q, k) => q + Math.sqrt(base!.lev.S[r]) * slotConveyance(base!.lev.W[r], d, base!.lev.nCh[r], base!.y[k])));
  const run = (d: number) => {
    const Q = curves(d);
    const stage = Float64Array.from(base!.lev.qPeak, (q, r) => stageFromQ(Q[r], base!.y, q).stage);
    const depth = levelDepth(base!.lev, stage);
    let wet = 0;
    for (const x of depth) if (x >= 0.01) wet++;
    return { Q, stage, depth, km2: (wet * v!.data.dx ** 2) / 1e6 };
  };
  const now = useMemo(() => (base ? run(0) : null), [base]); // eslint-disable-line react-hooks/exhaustive-deps
  const old = useMemo(() => (base ? run(D) : null), [base, D]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!v || !base || !now || !old) return <WidgetFrame title="No channel below the DEM" idea="Loading…"><Loading /></WidgetFrame>;

  const { lev, y, r } = base;
  const q = lev.qPeak[r];
  const W = lev.W[r];
  const y0 = now.stage[r], yD = old.stage[r];
  const q0slot = old.Q[r][0];
  const { ny, nx } = v.data;

  // ── picture 1: cross-section (metres across) ──
  const cellW = v.data.dx;
  const cells = [
    ...base.left.map((h) => ({ w: cellW, h, river: false })),
    { w: W, h: 0, river: true },
    ...base.right.map((h) => ({ w: cellW, h, river: false })),
  ];
  const totW = cells.reduce((a, b) => a + b.w, 0);
  const XW = 470, XH = 330, PL = 44, PR = 8, PT = 14, PB = 26;
  const sx = (m: number) => PL + (m / totW) * (XW - PL - PR);
  const sy = (h: number) => PT + ((Y_TOP - Math.min(Math.max(h, Y_BOT), Y_TOP)) / (Y_TOP - Y_BOT)) * (XH - PT - PB);
  let run0 = 0;
  const geo = cells.map((c) => { const x0 = run0; run0 += c.w; return { ...c, X0: sx(x0), X1: sx(x0 + c.w) }; });
  const riv = geo.find((c) => c.river)!;

  // ── picture 2: rating curves (stage up, Q right) ──
  const CW = 330, CPL = 50, CPR = 12;
  const kTop = y.findIndex((s) => s > Y_TOP + 1e-9);
  const K = kTop < 0 ? y.length : kTop;
  const qAx = Math.ceil(Math.max(2.6 * q, 1.5 * now.Q[r][0] + 1, 1.5 * q0slot) / 200) * 200;
  const cx = (qq: number) => CPL + (Math.min(qq, qAx) / qAx) * (CW - CPL - CPR);
  const CB = XH - 46; // bottom of the curve plot
  const cy = (s: number) => PT + ((Y_TOP - s) / Y_TOP) * (CB - PT);
  const line = (Q: Float64Array) => {
    const pts: string[] = [];
    for (let k = 0; k < K && Q[k] <= qAx; k++) pts.push(`${cx(Q[k])},${cy(y[k])}`);
    return pts.join(' ');
  };

  const paintOf = (depth: Float64Array) => (i: number): [number, number, number] => {
    const d = depth[i];
    if (d >= 0.01) return depthRGB(d);
    if (v.grid.river[i]) return [20, 66, 122];
    const k = 0.62 + 0.38 * v.shade[i];
    return [Math.round(232 * k), Math.round(224 * k), Math.round(206 * k)];
  };

  return (
    <WidgetFrame
      title="No channel below the DEM"
      idea={<>The DEM&apos;s river cell is already water: it shows the river surface on the day the DEM was made. Dig a channel below it as well, and the river&apos;s capacity is counted twice. The mapped flood sinks by about the depth of that channel.</>}
    >
      <div className="flex flex-col lg:flex-row gap-3">
        {/* picture 1 */}
        <div className="flex-[1.35] min-w-0">
          <div className="text-xs font-semibold text-slate-600 mb-1">The same {q.toFixed(0)} m³/s on two grounds (slice of §7.1, main river)</div>
          <svg viewBox={`0 0 ${XW} ${XH}`} className="w-full rounded-lg border border-slate-200 bg-gradient-to-b from-sky-50 to-white" role="img"
            aria-label="Cross-section with a channel cut below the DEM">
            <defs>
              <pattern id="slot-h" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2="7" stroke={SLOT_COL} strokeWidth="2.2" />
              </pattern>
            </defs>
            {/* water on the DEM as it is (D = 0) */}
            {geo.map((c, k) => y0 > c.h && (
              <rect key={`w${k}`} x={c.X0} y={sy(y0)} width={c.X1 - c.X0 + 0.4} height={sy(c.h) - sy(y0)} fill={depthCss(1.5)} opacity={0.75} />
            ))}
            {/* ground */}
            {geo.map((c, k) => (
              <g key={k}>
                <rect x={c.X0} y={sy(c.h)} width={c.X1 - c.X0 + 0.4} height={sy(Y_BOT) - sy(c.h)} fill={C.groundFill} />
                <line x1={c.X0} x2={c.X1} y1={sy(c.h)} y2={sy(c.h)} stroke={c.river ? C.river : C.ground} strokeWidth={c.river ? 4 : 1.5} />
              </g>
            ))}
            {/* the slot */}
            {D > 0 && (
              <g>
                <rect x={riv.X0} y={sy(0)} width={riv.X1 - riv.X0} height={sy(-D) - sy(0)} fill="#cfe2f3" />
                <rect x={riv.X0} y={sy(0)} width={riv.X1 - riv.X0} height={sy(-D) - sy(0)} fill="url(#slot-h)" opacity={0.55} />
                <polyline points={`${riv.X0},${sy(0)} ${riv.X0},${sy(-D)} ${riv.X1},${sy(-D)} ${riv.X1},${sy(0)}`} fill="none" stroke={SLOT_COL} strokeWidth={2} strokeDasharray="5 3" />
                <text x={(riv.X0 + riv.X1) / 2} y={sy(-D / 2) - 9} textAnchor="middle" fontSize={10} fontWeight={700} fill="#9a3412">channel cut</text>
                <text x={(riv.X0 + riv.X1) / 2} y={sy(-D / 2) + 3} textAnchor="middle" fontSize={10} fontWeight={700} fill="#9a3412">D = {D.toFixed(1)} m</text>
                <text x={(riv.X0 + riv.X1) / 2} y={sy(-D / 2) + 15} textAnchor="middle" fontSize={9.5} fill="#9a3412">holds {q0slot.toFixed(0)} m³/s</text>
              </g>
            )}
            <text x={(riv.X0 + riv.X1) / 2} y={sy(0) - 5} textAnchor="middle" fontSize={9.5} fill={C.river} fontWeight={700}>DEM river surface: already water</text>
            {/* levels */}
            <line x1={PL} x2={XW - PR} y1={sy(y0)} y2={sy(y0)} stroke={C.water} strokeWidth={2} />
            <text x={PL + 4} y={sy(y0) - 5} fontSize={10.5} fill={C.river} fontWeight={700}>on the DEM as it is: {y0.toFixed(2)} m</text>
            {D > 0 && (
              <g>
                <line x1={PL} x2={XW - PR} y1={sy(yD)} y2={sy(yD)} stroke={SLOT_COL} strokeWidth={2} strokeDasharray="7 4" />
                <text x={PL + 4} y={sy(yD) + 13} fontSize={10.5} fill="#9a3412" fontWeight={700}>
                  {yD < 0.01 ? 'with the channel: 0 m, it all fits inside' : `with the channel: ${yD.toFixed(2)} m`}
                </text>
              </g>
            )}
            {/* axis */}
            <line x1={PL} x2={PL} y1={PT} y2={XH - PB} stroke="#94a3b8" />
            {[-3, -2, -1, 0, 1, 2, 3, 4].map((m) => (
              <g key={m}>
                <line x1={PL - 4} x2={PL} y1={sy(m)} y2={sy(m)} stroke="#94a3b8" />
                <text x={PL - 7} y={sy(m) + 3.5} textAnchor="end" fontSize={10} fill={C.soft} fontFamily="monospace">{m}</text>
              </g>
            ))}
            <text x={13} y={(PT + XH - PB) / 2} fontSize={10.5} fill={C.ink} textAnchor="middle" transform={`rotate(-90 13 ${(PT + XH - PB) / 2})`}>
              height above the DEM river (m)
            </text>
            <text x={(PL + XW) / 2} y={XH - 8} textAnchor="middle" fontSize={10} fill={C.soft}>
              river strip {W.toFixed(0)} m wide · land cells 30 m · ground drawn at HAND
            </text>
          </svg>
        </div>

        {/* picture 2 */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-slate-600 mb-1">The reach&apos;s rating curve, without and with the channel</div>
          <svg viewBox={`0 0 ${CW} ${XH}`} className="w-full rounded-lg border border-slate-200 bg-white" role="img" aria-label="Rating curves with and without the channel">
            {D > 0 && (
              <g>
                <line x1={cx(0)} x2={cx(q0slot)} y1={cy(0) - 8} y2={cy(0) - 8} stroke={SLOT_COL} strokeWidth={2} markerEnd="url(#arr)" />
                <defs>
                  <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
                    <path d="M0,0 L10,5 L0,10 z" fill={SLOT_COL} />
                  </marker>
                </defs>
                <text x={CPL + 4} y={cy(0) - 14} fontSize={10} fill="#9a3412" fontWeight={700}>
                  {q0slot.toFixed(0)} m³/s fit inside a {D.toFixed(1)} m channel
                </text>
              </g>
            )}
            <polyline points={line(now.Q[r])} fill="none" stroke={C.water} strokeWidth={2.5} />
            {D > 0 && <polyline points={line(old.Q[r])} fill="none" stroke={SLOT_COL} strokeWidth={2.5} strokeDasharray="7 4" />}
            <line x1={cx(q)} x2={cx(q)} y1={PT} y2={CB} stroke="#94a3b8" strokeDasharray="3 3" />
            <text x={cx(q) + 4} y={CB - 50} fontSize={10} fill={C.soft}>this flood, {q.toFixed(0)} m³/s</text>
            <circle cx={cx(q)} cy={cy(y0)} r={5} fill={C.water} stroke="white" strokeWidth={1.5} />
            {D > 0 && <circle cx={cx(q)} cy={cy(yD)} r={5} fill={SLOT_COL} stroke="white" strokeWidth={1.5} />}
            <line x1={CPL} x2={CPL} y1={PT} y2={CB} stroke="#94a3b8" />
            <line x1={CPL} x2={CW - CPR} y1={CB} y2={CB} stroke="#94a3b8" />
            {[0, 1, 2, 3, 4].map((m) => (
              <text key={m} x={CPL - 6} y={cy(m) + 3.5} textAnchor="end" fontSize={10} fill={C.soft} fontFamily="monospace">{m}</text>
            ))}
            {[0, 0.25, 0.5, 0.75, 1].map((f) => (
              <text key={f} x={cx(f * qAx)} y={CB + 13} textAnchor="middle" fontSize={10} fill={C.soft} fontFamily="monospace">{Math.round(f * qAx)}</text>
            ))}
            <text x={(CPL + CW) / 2} y={CB + 27} textAnchor="middle" fontSize={10.5} fill={C.ink}>discharge Q (m³/s)</text>
            <text x={14} y={(PT + CB) / 2} fontSize={10.5} fill={C.ink} textAnchor="middle" transform={`rotate(-90 14 ${(PT + CB) / 2})`}>
              stage above the DEM river (m)
            </text>
            <text x={CPL + 6} y={PT + 26} fontSize={10} fill={C.river} fontWeight={700}>── on the DEM as it is (D = 0)</text>
            <text x={CPL + 6} y={PT + 40} fontSize={10} fill="#9a3412" fontWeight={700}>- - with a {D.toFixed(1)} m channel below</text>
          </svg>
        </div>
      </div>

      <div className="mt-3">
        <Slider label="Channel cut below the DEM, D" value={D} min={0} max={3} step={0.1} display={`${D.toFixed(1)} m`} onChange={setD}
          hint="Before 15 October 2026 the maps used the routing's bankfull depth here (2.5–3.2 m at Kathmandu). Now D = 0." />
      </div>

      <div className="mt-4 flex flex-col lg:flex-row gap-4">
        {/* picture 3: the two maps */}
        <div className="flex gap-3 lg:w-[300px] flex-shrink-0">
          {[{ f: now, lab: 'On the DEM as it is' }, { f: old, lab: `With a ${D.toFixed(1)} m channel` }].map(({ f, lab }, k) => (
            <div key={k} className="flex-1 min-w-0">
              <div className="text-[11px] font-semibold text-slate-600 mb-1 leading-tight">{lab}</div>
              <div className="rounded-md overflow-hidden border border-slate-300">
                <RasterCanvas ny={ny} nx={nx} scale={1} paint={paintOf(f.depth)} deps={[f]} ariaLabel={`Flood map: ${lab}`} />
              </div>
              <div className="text-[12px] font-bold text-sky-800 mt-0.5 tabular-nums">{f.km2.toFixed(2)} km² flooded</div>
            </div>
          ))}
        </div>

        {/* evidence */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-slate-600 mb-2">Measured at real floods: how much of what was observed the HAND map covered</div>
          <Evidence />
          <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-[12.5px] text-sky-900 leading-snug">
            <b>The routing keeps its channel.</b> A 90 m routing cell is much wider than most rivers, so the router gives river
            cells a channel sized for the bankfull flow (the <code>CHANNEL_*</code> settings). The flood maps are drawn on the
            DEM as it is: no channel below it.
          </div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat label="Stage, DEM as it is" value={`${y0.toFixed(2)} m`} tone="sky" />
        <Stat label={`Stage, ${D.toFixed(1)} m channel`} value={`${yD.toFixed(2)} m`} tone="red" />
        <Stat label="Fits in the channel" value={`${q0slot.toFixed(0)} m³/s`} />
        <Stat label="Flooded land lost" value={`${(now.km2 - old.km2).toFixed(2)} km²`} tone="red" />
      </div>
      <div className="mt-2"><DepthBar /></div>

      <LookFor items={[
        <>Slide <b>D</b> up: the orange curve moves right by everything the channel holds, so the same flood stands lower.</>,
        <>At about 2.5 m the whole {q.toFixed(0)} m³/s fits in the channel. Stage 0: the right-hand map shows no flood beside the river.</>,
        <>At real floods, dropping the channel took the HAND maps from covering a quarter of the observed flood traces to more than half.</>,
      ]} />
    </WidgetFrame>
  );
}

const EVIDENCE: { place: string; what: string; bars: { lab: string; v: number; slot: boolean }[] }[] = [
  {
    place: 'Kathmandu, Sept 2024', what: 'share of Sentinel-2 flood traces inside the map',
    bars: [{ lab: 'full channel', v: 0.25, slot: true }, { lab: 'half channel', v: 0.38, slot: true }, { lab: 'no channel', v: 0.54, slot: false }],
  },
  {
    place: 'Bagmati above the confluence', what: 'share of flood traces inside the map',
    bars: [{ lab: 'full channel', v: 0.09, slot: true }, { lab: 'no channel', v: 0.76, slot: false }],
  },
  {
    place: 'Montpelier, July 2023', what: 'USGS high-water marks inside the flood',
    bars: [{ lab: 'full channel', v: 0.45, slot: true }, { lab: 'no channel', v: 0.78, slot: false }],
  },
  {
    place: 'Pearl River, Feb 2020', what: 'Sentinel-2 water covered',
    bars: [{ lab: 'full channel', v: 0.28, slot: true }, { lab: 'no channel', v: 0.49, slot: false }],
  },
];

function Evidence() {
  return (
    <div className="flex flex-col gap-2.5">
      {EVIDENCE.map((e) => (
        <div key={e.place}>
          <div className="text-[12px] text-slate-700"><b>{e.place}</b> <span className="text-slate-500">— {e.what}</span></div>
          {e.bars.map((b) => (
            <div key={b.lab} className="flex items-center gap-2 mt-0.5">
              <span className="w-24 flex-shrink-0 text-[11px] text-slate-600 text-right">{b.lab}</span>
              <div className="flex-1 h-3.5 bg-slate-100 rounded-sm overflow-hidden">
                <div className="h-full rounded-sm" style={{
                  width: `${b.v * 100}%`,
                  background: b.slot ? `repeating-linear-gradient(45deg, ${SLOT_COL} 0 4px, #fde9cf 4px 7px)` : C.water,
                }} />
              </div>
              <span className="w-10 text-[11px] font-mono text-slate-800 tabular-nums">{Math.round(b.v * 100)} %</span>
            </div>
          ))}
        </div>
      ))}
      <Legend items={[
        { swatch: <span className="inline-block w-3.5 h-3.5 rounded-sm" style={{ background: `repeating-linear-gradient(45deg, ${SLOT_COL} 0 3px, #fde9cf 3px 5px)` }} />, label: 'with a channel below the DEM (old)' },
        { swatch: C.water, label: 'on the DEM as it is (now)' },
      ]} />
    </div>
  );
}
