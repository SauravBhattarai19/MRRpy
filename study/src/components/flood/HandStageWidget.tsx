'use client';

// §7.1 — the whole idea of HAND in one picture. A real HAND flood map of the
// synthetic valley (computed live with MRRpy's algorithm), a slice across it,
// and a switch that redraws the slice as "height above the river each cell
// drains to": the valley floor goes flat and one level floods everything below.

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { handLevel, levelDepth, stageFromQ } from '@/lib/flood/hand';
import { useValley } from './useValley';
import {
  C, DepthBar, Legend, Loading, LookFor, RasterCanvas, Slider, Stat, Toggle, WidgetFrame,
  depthCss, depthRGB, qualRGB,
} from './ui';

const Q_MAX = 3; // largest flood on the slider [m³/s per km²]
const H_MAX = 12; // top of the height colour ramp [m]

// dark (low) → light (high): YlOrBr reversed, so water blue never mixes in
const RAMP: [number, number, number][] = [[102, 37, 6], [204, 76, 2], [254, 153, 41], [254, 227, 145], [255, 255, 229]];
function heightRGB(h: number, shade: number): [number, number, number] {
  const x = Math.min(Math.max(h / H_MAX, 0), 1) * (RAMP.length - 1);
  const k = Math.min(Math.floor(x), RAMP.length - 2), f = x - k;
  const m = 0.72 + 0.28 * shade;
  return [0, 1, 2].map((j) => Math.round((RAMP[k][j] + f * (RAMP[k + 1][j] - RAMP[k][j])) * m)) as [number, number, number];
}
const rampCss = `linear-gradient(90deg, ${RAMP.map((c) => `rgb(${c.join(',')})`).join(',')})`;
const HALF = 30; // cells either side of the main river in the slice

export default function HandStageWidget() {
  const v = useValley();
  const [q, setQ] = useState(0.3);
  const [row, setRow] = useState(130);
  const [view, setView] = useState<'elev' | 'hand'>('elev');
  const [t, setT] = useState(view === 'hand' ? 1 : 0); // 0 = elevation, 1 = HAND (animated)
  const [hover, setHover] = useState<number | null>(null);

  // morph animation
  const raf = useRef(0);
  useEffect(() => {
    const target = view === 'hand' ? 1 : 0;
    const t0 = performance.now(), from = t;
    const step = (now: number) => {
      const f = Math.min((now - t0) / 700, 1);
      const e = f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;
      setT(from + (target - from) * e);
      if (f < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  // HAND, reaches and rating curves: once (rating table sized for the largest flood)
  const lev = useMemo(() => {
    if (!v) return null;
    const qMax = Float64Array.from(v.q1, (x) => x * Q_MAX);
    return handLevel(v.grid, v.grid.river, v.data.aChannelKm2, { qPeak: qMax });
  }, [v]);

  // stages and depths for the chosen flood: only a table lookup per reach
  const flood = useMemo(() => {
    if (!lev) return null;
    const qR = Float64Array.from(lev.qPeak, (x) => (x * q) / Q_MAX);
    const stage = Float64Array.from(qR, (x, r) => stageFromQ(lev.rating.Q[r], lev.rating.y, x).stage);
    const depth = levelDepth(lev, stage);
    let wet = 0;
    for (const d of depth) if (d >= 0.01) wet++;
    return { qR, stage, depth, km2: (wet * v!.data.dx ** 2) / 1e6 };
  }, [lev, q, v]);

  // the slice: cells of one row around its largest river
  const slice = useMemo(() => {
    if (!v || !lev || !flood) return null;
    const { nx } = v.data, g = v.grid;
    let main = -1;
    for (let c = 0; c < nx; c++) {
      const i = row * nx + c;
      if (g.river[i] && (main < 0 || g.area[i] > g.area[row * nx + main])) main = c;
    }
    if (main < 0) return null;
    const c0 = Math.max(main - HALF, 0), c1 = Math.min(main + HALF, nx - 1);
    const iMain = row * nx + main;
    const rMain = lev.cellReach[iMain];
    const bedMain = lev.bed[iMain];
    const cells: { i: number; c: number; reach: number; zRel: number; hand: number; depth: number; stage: number; river: boolean }[] = [];
    for (let c = c0; c <= c1; c++) {
      const i = row * nx + c;
      const reach = lev.cellReach[i];
      cells.push({
        i, c, reach,
        zRel: g.zRaw[i] - bedMain,
        hand: lev.hand[i],
        depth: flood.depth[i],
        stage: reach >= 0 ? flood.stage[reach] : 0,
        river: !!g.river[i],
      });
    }
    const yMain = flood.stage[rMain];
    // lower than the main river's water, yet dry: drains to another stream
    let odd = -1;
    cells.forEach((cl, k) => {
      if (cl.depth < 0.01 && cl.zRel < yMain - 0.05 && cl.reach !== rMain && (odd < 0 || cl.zRel < cells[odd].zRel)) odd = k;
    });
    return { cells, main, c0, rMain, yMain, qMain: flood.qR[rMain], odd };
  }, [v, lev, flood, row]);

  if (!v || !lev || !flood || !slice) return <WidgetFrame title="Raise the river" idea="Loading…"><Loading /></WidgetFrame>;

  const { ny, nx, dx } = v.data;
  const g = v.grid;

  // ── map painter ──
  const zOut = lev.bed[v.data.outlet[0] * nx + v.data.outlet[1]];
  const paint = (i: number): [number, number, number] => {
    const d = flood.depth[i];
    if (g.river[i] && d < 0.01) return [20, 66, 122];
    if (d >= 0.01) return depthRGB(d);
    const h = Number.isNaN(lev.hand[i]) ? g.zRaw[i] - zOut : lev.hand[i];
    return heightRGB((1 - t) * (g.zRaw[i] - zOut) + t * h, v.shade[i]);
  };

  // ── slice geometry ──
  const W = 600, H = 300, PL = 52, PR = 14, PT = 18, PB = 58;
  const cells = slice.cells;
  const ground = cells.map((cl) => (1 - t) * cl.zRel + t * (Number.isNaN(cl.hand) ? cl.zRel : cl.hand));
  const yTop = Math.max(8, slice.yMain + 4);
  const yBot = -2;
  const xOf = (k: number) => PL + (k / cells.length) * (W - PL - PR);
  const yOf = (m: number) => PT + ((yTop - Math.min(Math.max(m, yBot), yTop)) / (yTop - yBot)) * (H - PT - PB);
  const cw = (W - PL - PR) / cells.length;
  const reachColour = (r: number) => (r === slice.rMain ? C.water : `rgb(${qualRGB(r + 3).join(',')})`);
  const hv = hover !== null ? cells[hover] : null;

  return (
    <WidgetFrame
      title="Raise the river: what floods?"
      idea={<>Every cell gets one number — how high it stands above the river its water drains to (HAND). A river that rises <i>y</i> metres floods every cell whose HAND is below <i>y</i>.</>}
    >
      <div className="flex flex-col lg:flex-row gap-5">
        {/* map */}
        <div className="lg:w-[230px] flex-shrink-0">
          <div className="text-xs font-semibold text-slate-600 mb-1">Map of the valley (click to move the slice)</div>
          <div className="relative rounded-lg overflow-hidden border border-slate-300">
            <RasterCanvas
              ny={ny} nx={nx} scale={2} paint={paint} deps={[flood, row, hover, t]}
              ariaLabel="Map of the valley with flooded cells in blue and the slice position as a yellow line"
              onCell={(r) => setRow(Math.min(Math.max(r, 5), ny - 6))}
              overlay={(ctx, s) => {
                ctx.fillStyle = 'rgba(251,191,36,0.95)';
                ctx.fillRect(slice.c0 * s, row * s - 1, cells.length * s, 3);
                if (hv) { ctx.strokeStyle = C.bad; ctx.lineWidth = 2; ctx.strokeRect(hv.c * s - 2, row * s - 2, s + 4, s + 4); }
                ctx.fillStyle = 'rgba(31,36,48,0.85)';
                ctx.font = `bold ${5 * s}px sans-serif`;
                ctx.fillText('flow ↓', 3 * s, 8 * s);
              }}
            />
          </div>
          <div className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-600">
            <span className="inline-block h-2.5 w-20 rounded" style={{ background: rampCss }} />
            <span>{t < 0.5 ? 'height above outlet' : 'height above its river'} · 0–{H_MAX} m</span>
          </div>
          <div className="mt-2">
            <Slider label="Slice position" value={row} min={5} max={ny - 6} step={1}
              display={`${((row * dx) / 1000).toFixed(2)} km down`} onChange={setRow} />
          </div>
        </div>

        {/* slice + controls */}
        <div className="flex-1 min-w-0 flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Toggle label="How to draw the slice" value={view} onChange={setView}
              options={[{ value: 'elev', label: 'Ground as it is' }, { value: 'hand', label: 'Height above its river (HAND)' }]} />
            <DepthBar />
          </div>

          <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-lg border border-slate-200 bg-gradient-to-b from-sky-50 to-white"
            role="img" aria-label="Slice across the valley showing ground and water" onMouseLeave={() => setHover(null)}>
            {/* water then ground, cell by cell */}
            {cells.map((cl, k) => {
              const g0 = ground[k];
              const top = g0 + cl.depth;
              return (
                <g key={cl.i} onMouseEnter={() => setHover(k)}>
                  <rect x={xOf(k)} y={PT} width={cw + 0.5} height={H - PT - PB} fill="transparent" />
                  {cl.depth >= 0.01 && (
                    <rect x={xOf(k)} y={yOf(top)} width={cw + 0.5} height={Math.max(yOf(g0) - yOf(top), 0)} fill={depthCss(cl.depth)} />
                  )}
                  <rect x={xOf(k)} y={yOf(g0)} width={cw + 0.5} height={Math.max(yOf(yBot) - yOf(g0), 0)} fill={C.groundFill} />
                  <line x1={xOf(k)} x2={xOf(k) + cw} y1={yOf(g0)} y2={yOf(g0)} stroke={cl.river ? C.river : C.ground} strokeWidth={cl.river ? 4 : 1.6} />
                </g>
              );
            })}
            {/* the river cell: its DEM surface is the zero of HAND */}
            {cells.map((cl, k) => cl.river && (
              <text key={`rv${cl.i}`} x={xOf(k) + cw / 2} y={yOf(ground[k]) + 14} textAnchor="middle" fontSize={10} fill={C.river} fontWeight={700}>river</text>
            ))}
            {/* the main river's water level */}
            <line x1={PL} x2={W - PR} y1={yOf(slice.yMain)} y2={yOf(slice.yMain)} stroke={C.water} strokeDasharray="6 4" strokeWidth={1.4} />
            <text x={W - PR - 4} y={yOf(slice.yMain) - 5} textAnchor="end" fontSize={11} fill={C.river} fontWeight={600}>
              {t > 0.5 ? `water level of the main river: y = ${slice.yMain.toFixed(2)} m` : `main river water level (+${slice.yMain.toFixed(2)} m)`}
            </text>
            {/* the dry cell below the water line */}
            {slice.odd >= 0 && (
              <g pointerEvents="none">
                <circle cx={xOf(slice.odd) + cw / 2} cy={yOf(ground[slice.odd])} r={9} fill="none" stroke={C.bad} strokeWidth={2} />
                <text x={xOf(slice.odd) + cw / 2} y={yOf(ground[slice.odd]) - 16} textAnchor="end" fontSize={10.5} fill={C.bad} fontWeight={600}>
                  {t < 0.5 ? 'lower than the water, but dry' : 'its own stream is small: dry'}
                </text>
              </g>
            )}
            {/* "which river does this cell drain to" ribbon */}
            {cells.map((cl, k) => (
              <rect key={`rb${cl.i}`} x={xOf(k)} y={H - PB + 8} width={cw + 0.5} height={10}
                fill={cl.reach >= 0 ? reachColour(cl.reach) : '#e2e8f0'} opacity={cl.reach === slice.rMain ? 0.9 : 0.75} />
            ))}
            <text x={PL} y={H - PB + 32} fontSize={10.5} fill={C.soft}>
              ▲ which river each cell drains to: blue = the main river, other colours = other streams
            </text>
            {/* axes */}
            <line x1={PL} x2={PL} y1={PT} y2={H - PB} stroke="#94a3b8" />
            {[0, 2, 4, 6, 8, 10, 12, 14].filter((m) => m <= yTop).map((m) => (
              <g key={m}>
                <line x1={PL - 4} x2={PL} y1={yOf(m)} y2={yOf(m)} stroke="#94a3b8" />
                <text x={PL - 7} y={yOf(m) + 3.5} textAnchor="end" fontSize={10} fill={C.soft} fontFamily="monospace">{m}</text>
              </g>
            ))}
            <text x={14} y={(PT + H - PB) / 2} fontSize={10.5} fill={C.ink} textAnchor="middle"
              transform={`rotate(-90 14 ${(PT + H - PB) / 2})`}>
              {t < 0.5 ? 'metres above the main river' : 'metres above its own river (HAND)'}
            </text>
            <text x={(PL + W - PR) / 2} y={H - 6} textAnchor="middle" fontSize={10.5} fill={C.ink}>
              across the valley, {((cells.length * dx) / 1000).toFixed(1)} km — one bar per 30 m cell
            </text>
          </svg>

          <Slider label="Flood size (discharge per km² of drainage area)" value={q} min={0.1} max={Q_MAX} step={0.05}
            display={`${q.toFixed(2)} m³/s per km²`} onChange={setQ}
            hint="Every river carries this much water for each km² that drains to it." />

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="Main river here" value={`${slice.qMain.toFixed(0)} m³/s`} />
            <Stat label="Its stage y" value={`${slice.yMain.toFixed(2)} m`} tone="sky" />
            <Stat label="Flooded land" value={`${flood.km2.toFixed(2)} km²`} tone="sky" />
            <Stat label={hv ? 'This cell' : 'Point at a bar'} value={hv
              ? <span className="text-sm">HAND {Number.isNaN(hv.hand) ? '—' : hv.hand.toFixed(2)} m · {hv.depth >= 0.01 ? `${hv.depth.toFixed(2)} m deep` : 'dry'}</span>
              : <span className="text-sm text-slate-400">—</span>} />
          </div>
          <Legend items={[
            { swatch: C.groundFill, label: 'ground' },
            { swatch: <span className="inline-block w-3.5 h-1 rounded" style={{ background: C.river }} />, label: 'river cell (its DEM surface = HAND 0)' },
            { swatch: depthCss(1.5), label: 'flood water' },
            { swatch: <span className="inline-block w-3.5 h-3.5 rounded-full border-2" style={{ borderColor: C.bad }} />, label: 'dry although lower than the water' },
          ]} />
        </div>
      </div>

      <LookFor items={[
        <>Drag <b>Flood size</b>: the blue spreads over the low land beside every river, on the map and in the slice.</>,
        <>Press <b>Height above its river</b>. On the map the valley floor, light at the top and dark at the bottom, turns evenly dark: measured from its own river, all of it is low. So one level <i>y</i> floods all of it.</>,
        <>The <span className="text-red-700 font-semibold">red ring</span> marks land lower than the main river&apos;s water that stays dry: its water drains to a smaller stream, and HAND compares it with <i>that</i> stream.</>,
      ]} />
    </WidgetFrame>
  );
}
