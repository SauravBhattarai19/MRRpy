'use client';

// §7.7 — levels. Near a confluence D8 sends the land at a tributary's mouth
// to the tributary, whose small flow gives a low level. MRRpy repeats HAND
// with only the main stems as drains (level 1, 2, …) and keeps the deepest
// water of all levels (mapping.FloodModel). A spatial maximum, not backwater.

import React, { useMemo, useState } from 'react';
import { floodMap, levelDepth } from '@/lib/flood/hand';
import { useValley } from './useValley';
import { C, DepthBar, Legend, Loading, LookFor, RasterCanvas, Slider, Stat, Toggle, Unstable, WidgetFrame, depthCss, depthRGB } from './ui';

// zoom window on the tributary mouth (rows/cols of the 30 m valley grid)
const R0 = 77, R1 = 150, C0 = 40, C1 = 120;
const SMALL_KM2 = 50; // streams below this are "side streams" (drawn red)
type Mode = 'l0' | 'l1' | 'map';

export default function LevelsWidget() {
  const v = useValley();
  const [q, setQ] = useState(1);
  const [mode, setMode] = useState<Mode>('map');

  const res = useMemo(() => {
    if (!v) return null;
    const fm = floodMap(v.grid, Float64Array.from(v.q1, (x) => x * q));
    const d = fm.levels.map((lev) => levelDepth(lev, lev.stage));
    let w0 = 0, wMap = 0;
    for (let i = 0; i < v.grid.n; i++) { if (d[0][i] >= 0.01) w0++; if (fm.depth[i] >= 0.01) wMap++; }
    const km2 = (n: number) => (n * v.data.dx ** 2) / 1e6;
    return { fm, d, a0: km2(w0), aMap: km2(wMap) };
  }, [v, q]);

  if (!v || !res) return <WidgetFrame title="Main rivers back up into side streams" idea="Loading…"><Loading /></WidgetFrame>;

  const { nx, dx } = v.data;
  const g = v.grid;
  const ny2 = R1 - R0 + 1, nx2 = C1 - C0 + 1;
  const at = (k: number) => (R0 + Math.floor(k / nx2)) * nx + C0 + (k % nx2);
  const thr = res.fm.levels.map((l) => l.threshold);
  const shown = mode === 'l0' ? res.d[0] : mode === 'l1' ? (res.d[1] ?? res.d[0]) : res.fm.depth;
  const added = (i: number) => mode === 'map' && res.fm.depth[i] >= 0.01 && res.d[0][i] < 0.01;
  const bad = !Number.isFinite(res.aMap) || !Number.isFinite(res.a0);
  const pct = res.a0 > 0 ? (res.aMap / res.a0 - 1) * 100 : 0;

  const paint = (k: number): [number, number, number] => {
    const i = at(k);
    const d = shown[i];
    if (added(i)) return [253, 186, 116];
    if (d >= 0.01) return depthRGB(d);
    const s = v.shade[i], m = 0.6 + 0.4 * s;
    return [Math.round(232 * m), Math.round(226 * m), Math.round(212 * m)];
  };

  const overlay = (ctx: CanvasRenderingContext2D, s: number) => {
    const cx = (i: number) => ((i % nx) - C0 + 0.5) * s, cy = (i: number) => (Math.floor(i / nx) - R0 + 0.5) * s;
    // orange hatch on cells wet only because of a higher level
    ctx.strokeStyle = 'rgba(154,52,18,0.85)'; ctx.lineWidth = 1;
    for (let k = 0; k < ny2 * nx2; k++) {
      const i = at(k);
      if (!added(i)) continue;
      const x = (k % nx2) * s, y = Math.floor(k / nx2) * s;
      ctx.beginPath(); ctx.moveTo(x, y + s); ctx.lineTo(x + s, y); ctx.stroke();
    }
    // rivers: main stem navy, side streams red; drains of this level solid, others dashed
    ctx.lineCap = 'round';
    for (let k = 0; k < ny2 * nx2; k++) {
      const i = at(k);
      if (!g.river[i]) continue;
      const d = g.ds[i];
      const small = g.area[i] < SMALL_KM2;
      const isDrain = mode === 'l0' || mode === 'map' || g.area[i] >= thr[1];
      ctx.strokeStyle = small ? C.bad : C.river;
      ctx.lineWidth = small ? 2.4 : 3.6;
      ctx.setLineDash(isDrain ? [] : [3, 3]);
      ctx.beginPath(); ctx.moveTo(cx(i), cy(i));
      if (d >= 0 && g.river[d]) ctx.lineTo(cx(d), cy(d)); else ctx.lineTo(cx(i) + 0.01, cy(i));
      ctx.stroke();
    }
    ctx.setLineDash([]);
    // labels on the picture
    ctx.font = `bold ${2.6 * s}px sans-serif`;
    ctx.fillStyle = C.river; ctx.fillText('main river', 2 * s, 4 * s);
    ctx.fillStyle = C.bad; ctx.fillText('tributary', 52 * s, 12 * s);
    ctx.fillStyle = 'rgba(31,36,48,0.8)'; ctx.fillText('flow ↓', (nx2 - 12) * s, 4 * s);
  };

  const caption = {
    l0: <>Level 0: <b>every river is a drain</b> (≥ {thr[0]} km²). Land at the tributary&apos;s mouth drains to the tributary, whose small flow stands low.</>,
    l1: <>Level 1: <b>only main stems are drains</b> (≥ {thr[1]} km², dashed streams are ignored). The mouth now drains to the main river and gets its higher level.</>,
    map: <>The map keeps the <b>deeper water</b> of all {thr.length} levels at every cell. <span className="text-orange-800 font-semibold">Hatched orange</span> cells are wet only because of a main-stem level.</>,
  }[mode];

  return (
    <WidgetFrame
      title="Main rivers back up into side streams: levels"
      idea={<>D8 sends land at a tributary&apos;s mouth to the tributary, so it would get the tributary&apos;s low water. MRRpy repeats HAND with only the big rivers as drains and keeps the deepest water.</>}
    >
      <div className="flex flex-col lg:flex-row gap-5">
        <div className="lg:w-[380px] flex-shrink-0">
          <div className="text-xs font-semibold text-slate-600 mb-1">Zoom on the tributary mouth ({((nx2 * dx) / 1000).toFixed(1)} × {((ny2 * dx) / 1000).toFixed(1)} km)</div>
          <div className="rounded-lg overflow-hidden border border-slate-300">
            <RasterCanvas ny={ny2} nx={nx2} scale={5} paint={paint} overlay={overlay} deps={[res, mode]}
              ariaLabel="Flood depth at the tributary mouth; hatched orange cells are wet only because of the main river's level" />
          </div>
        </div>
        <div className="flex-1 min-w-0 flex flex-col gap-3">
          <Toggle label="Which level to show" value={mode} onChange={setMode} options={[
            { value: 'l0', label: 'Level 0' }, { value: 'l1', label: 'Level 1' }, { value: 'map', label: 'The map' }]} />
          <p className="text-[13px] text-slate-700 leading-snug min-h-[3.5em]">{caption}</p>
          <Slider label="Flood size (discharge per km² of drainage area)" value={q} min={0.2} max={3} step={0.05}
            display={`${q.toFixed(2)} m³/s per km²`} onChange={setQ} />
          {bad ? <Unstable msg="the flooded area could not be computed." /> : (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <Stat label="Level 0 only" value={`${res.a0.toFixed(2)} km²`} />
              <Stat label="The map" value={`${res.aMap.toFixed(2)} km²`} tone="sky" />
              <Stat label="Added by levels" value={`+${pct.toFixed(1)} %`} tone="sky" />
            </div>
          )}
          <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-[12.5px] text-amber-900 leading-snug">
            This is a <b>spatial maximum, not a backwater computation</b>: no water flows up the tributary. At Khokana it added only 0.5 % to the flooded area, but it fills the tributary mouths, where people see water back up.
          </div>
          <div className="flex flex-col gap-1.5">
            <DepthBar />
            <Legend items={[
              { swatch: <span className="inline-block w-4 h-1 rounded" style={{ background: C.river }} />, label: 'main river' },
              { swatch: <span className="inline-block w-4 h-1 rounded" style={{ background: C.bad }} />, label: `side streams (< ${SMALL_KM2} km²)` },
              { swatch: <span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: C.bad }} />, label: 'not a drain at this level' },
              { swatch: <span className="inline-block w-3.5 h-3.5 rounded-sm border border-orange-800" style={{ background: 'repeating-linear-gradient(135deg, #fdba74 0 3px, #9a3412 3px 4px)' }} />, label: 'wet only because of the main river’s level' },
              { swatch: depthCss(1.5), label: 'flood water' },
            ]} />
          </div>
        </div>
      </div>
      <LookFor items={[
        <>Start at <b>Level 0</b>: the tributary&apos;s mouth is barely wet although the main river beside it is high.</>,
        <>Switch to <b>Level 1</b>: the tributary (dashed) is no longer a drain, so its mouth takes the main river&apos;s level.</>,
        <><b>The map</b> keeps the deeper of the two. The hatched orange area is what the levels add.</>,
      ]} />
    </WidgetFrame>
  );
}
