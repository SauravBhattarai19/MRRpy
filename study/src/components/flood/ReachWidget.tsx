'use client';

// §7.5 — reaches. A stage (one water level) belongs to a stretch of river.
// MRRpy cuts the river network into links (source/confluence → confluence)
// and each link into equal pieces of about 1 km (network.segment_reaches);
// every land cell then belongs to the reach its water drains to.

import React, { useMemo, useRef, useState } from 'react';
import { floodMap, handLevel, segmentReaches } from '@/lib/flood/hand';
import { useValley } from './useValley';
import { C, Legend, Loading, LookFor, RasterCanvas, Slider, Stat, Toggle, Unstable, WidgetFrame, qualRGB } from './ui';

type Mode = 'links' | 'reaches' | 'land';
const SCALE = 3;

export default function ReachWidget() {
  const v = useValley();
  const [len, setLen] = useState(1000);
  const [mode, setMode] = useState<Mode>('reaches');
  const [sel, setSel] = useState<number | null>(null); // selected reach id
  const floodCache = useRef(new Map<number, number>());

  // static network facts: links, confluences
  const net = useMemo(() => {
    if (!v) return null;
    const g = v.grid;
    const links = segmentReaches(g.order, g.ds, g.river, g.dist, 0);
    const nDon = new Int32Array(g.n);
    for (let i = 0; i < g.n; i++) if (g.river[i] && g.ds[i] >= 0 && g.river[g.ds[i]]) nDon[g.ds[i]]++;
    const conf: number[] = [];
    for (let i = 0; i < g.n; i++) if (g.river[i] && nDon[i] >= 2) conf.push(i);
    return { links, conf };
  }, [v]);

  // reaches for the chosen length
  const lev = useMemo(() => (v ? handLevel(v.grid, v.grid.river, v.data.aChannelKm2, { reachLenM: len, qPeak: v.q1 }) : null), [v, len]);

  // flooded area at 1 m³/s per km² for a reach length (cached per slider step)
  const flooded = (L: number) => {
    if (!v) return NaN;
    const c = floodCache.current.get(L);
    if (c !== undefined) return c;
    const fm = floodMap(v.grid, v.q1, { reachLenM: L });
    let wet = 0;
    for (const d of fm.depth) if (d >= 0.01) wet++;
    const km2 = (wet * v.data.dx ** 2) / 1e6;
    floodCache.current.set(L, km2);
    return km2;
  };
  const area = useMemo(() => (v ? { now: flooded(len), base: flooded(1000) } : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [v, len]);

  // per-reach cell counts
  const counts = useMemo(() => {
    if (!lev) return null;
    const riv = new Int32Array(lev.nReach), land = new Int32Array(lev.nReach);
    for (let i = 0; i < lev.cellReach.length; i++) {
      if (lev.reachOf[i] >= 0) riv[lev.reachOf[i]]++;
      else if (lev.cellReach[i] >= 0) land[lev.cellReach[i]]++;
    }
    return { riv, land };
  }, [lev]);

  if (!v || !lev || !net || !area || !counts) return <WidgetFrame title="A stage needs a stretch of river" idea="Loading…"><Loading /></WidgetFrame>;

  const { ny, nx, dx } = v.data;
  const g = v.grid;
  const ids = mode === 'links' ? net.links.reachOf : lev.reachOf;
  const nIds = mode === 'links' ? net.links.nLink : lev.nReach;
  const selReach = sel !== null && sel < lev.nReach ? sel : null;
  const change = (area.now / area.base - 1) * 100;
  const bad = !Number.isFinite(area.now) || !Number.isFinite(change);

  const paint = (i: number): [number, number, number] => {
    const s = v.shade[i];
    const k = 0.6 + 0.4 * s;
    const grey: [number, number, number] = [Math.round(232 * k), Math.round(228 * k), Math.round(218 * k)];
    if (mode === 'land') {
      const r = lev.cellReach[i];
      if (r < 0) return grey;
      const col = qualRGB(r);
      const dim = selReach !== null && r !== selReach ? 0.15 : 0.65;
      return [0, 1, 2].map((j) => Math.round(grey[j] * (1 - dim) + col[j] * dim)) as [number, number, number];
    }
    return grey;
  };

  const overlay = (ctx: CanvasRenderingContext2D, s: number) => {
    const cx = (i: number) => ((i % nx) + 0.5) * s, cy = (i: number) => (Math.floor(i / nx) + 0.5) * s;
    ctx.lineCap = 'round';
    // river lines, coloured by link / reach (dark ink on the land view)
    for (let i = 0; i < g.n; i++) {
      if (!g.river[i]) continue;
      const d = g.ds[i];
      const id = ids[i];
      const dim = mode !== 'links' && selReach !== null && lev.reachOf[i] !== selReach;
      ctx.strokeStyle = mode === 'land' ? (dim ? 'rgba(31,36,48,0.35)' : C.ink) : `rgba(${qualRGB(id).join(',')},${dim ? 0.3 : 1})`;
      ctx.lineWidth = mode === 'land' ? 1.6 : selReach !== null && !dim ? 5 : 3.4;
      ctx.beginPath();
      ctx.moveTo(cx(i), cy(i));
      if (d >= 0 && g.river[d]) ctx.lineTo(cx(d), cy(d)); else ctx.lineTo(cx(i) + 0.01, cy(i));
      ctx.stroke();
    }
    // confluences: open circles
    ctx.strokeStyle = C.bad; ctx.lineWidth = 1.8;
    for (const i of net.conf) { ctx.beginPath(); ctx.arc(cx(i), cy(i), 2.6 * s, 0, 2 * Math.PI); ctx.stroke(); }
    // reach outlets: triangles
    if (mode !== 'links') {
      ctx.fillStyle = C.ink;
      for (let r = 0; r < lev.nReach; r++) {
        const i = lev.outlet[r];
        if (i < 0) continue;
        const x = cx(i), y = cy(i), h = 1.9 * s;
        ctx.beginPath(); ctx.moveTo(x, y - h); ctx.lineTo(x + h, y + h * 0.8); ctx.lineTo(x - h, y + h * 0.8); ctx.closePath(); ctx.fill();
      }
    }
    ctx.fillStyle = 'rgba(31,36,48,0.85)';
    ctx.font = `bold ${4.5 * s}px sans-serif`;
    ctx.fillText('flow ↓', 3 * s, 7 * s);
  };

  const pick = (r: number, c: number) => {
    const i = r * nx + c;
    // nearest river cell within 2 cells, else the reach the cell drains to
    let best = -1, bd = 1e9;
    for (let dr = -2; dr <= 2; dr++) for (let dc = -2; dc <= 2; dc++) {
      const rr = r + dr, cc = c + dc;
      if (rr < 0 || rr >= ny || cc < 0 || cc >= nx) continue;
      const j = rr * nx + cc;
      if (lev.reachOf[j] >= 0 && dr * dr + dc * dc < bd) { bd = dr * dr + dc * dc; best = j; }
    }
    const reach = best >= 0 ? lev.reachOf[best] : lev.cellReach[i];
    setSel(reach >= 0 ? reach : null);
  };

  const card = selReach !== null ? (() => {
    const r = selReach;
    const out = lev.outlet[r];
    const link = out >= 0 ? net.links.reachOf[out] : -1;
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[12.5px] text-slate-700 leading-relaxed">
        <div className="font-bold text-slate-900 mb-0.5 flex items-center gap-2">
          <span className="inline-block w-3 h-3 rounded-sm" style={{ background: `rgb(${qualRGB(r).join(',')})` }} />
          Reach {r + 1} of {lev.nReach}
        </div>
        <div>length <b className="font-mono">{lev.L[r].toFixed(0)} m</b>{link >= 0 && <> (its link: {net.links.length[link].toFixed(0)} m)</>}</div>
        <div>mean bed slope <b className="font-mono">{lev.S[r].toFixed(4)}</b></div>
        <div>mean river width <b className="font-mono">{lev.W[r].toFixed(0)} m</b></div>
        <div>drainage area <b className="font-mono">{lev.area[r].toFixed(1)} km²</b></div>
        <div><b className="font-mono">{counts.riv[r]}</b> river cells, <b className="font-mono">{counts.land[r]}</b> land cells draining to it</div>
      </div>
    );
  })() : (
    <div className="rounded-lg border border-dashed border-slate-300 px-3 py-3 text-[12.5px] text-slate-500">
      Click a river (or any land) on the map, or use the reach buttons, to see one reach.
    </div>
  );

  return (
    <WidgetFrame
      title="A water level needs a stretch of river: reaches"
      idea={<>HAND gives one water level per <i>reach</i>. The river network is cut at every confluence into links, and each link into equal pieces of about 1 km. Every land cell belongs to the reach its water drains to.</>}
    >
      <div className="flex flex-col lg:flex-row gap-5">
        <div className="lg:w-[260px] flex-shrink-0">
          <div className="text-xs font-semibold text-slate-600 mb-1">The valley&apos;s rivers (click to pick a reach)</div>
          <div className="rounded-lg overflow-hidden border border-slate-300">
            <RasterCanvas ny={ny} nx={nx} scale={SCALE} paint={paint} overlay={overlay} deps={[lev, mode, selReach]}
              ariaLabel={`Map of the valley's rivers coloured by ${mode}`} onCell={(r, c) => pick(r, c)} />
          </div>
          <div className="text-[11px] text-slate-500 mt-1">{((nx * dx) / 1000).toFixed(1)} km × {((ny * dx) / 1000).toFixed(1)} km, 30 m cells</div>
        </div>

        <div className="flex-1 min-w-0 flex flex-col gap-3">
          <Toggle label="What to colour" value={mode} onChange={setMode} options={[
            { value: 'links', label: '1 · Links' }, { value: 'reaches', label: '2 · Reaches' }, { value: 'land', label: '3 · Land' }]} />
          <p className="text-[13px] text-slate-700 leading-snug">
            {mode === 'links' && <><b>Links</b> run from a source or a confluence (red circle) down to the next confluence. This network has <b>{net.links.nLink}</b> links, some much longer than 1 km.</>}
            {mode === 'reaches' && <><b>Reaches</b>: each link is cut into ⌈length / {len} m⌉ pieces of <i>equal</i> length, so there are no short leftovers. <b>{lev.nReach}</b> reaches; ▲ marks each reach&apos;s outlet, where its discharge is read.</>}
            {mode === 'land' && <><b>Land of each reach</b>: every cell takes the colour of the reach its water reaches first. The water level of that reach decides whether the cell floods.</>}
          </p>

          <Slider label="Reach length" value={len} min={250} max={3000} step={250} display={`${len} m${len === 1000 ? ' (MRRpy)' : ''}`}
            onChange={(x) => { setLen(x); setSel(null); }}
            hint="MRRpy always uses 1000 m. Try others to see how much it matters." />

          <div className="flex items-center gap-2 text-xs">
            <span className="font-semibold text-slate-600">Reach:</span>
            <button className="rounded border border-slate-300 px-2 py-1 hover:bg-sky-50" aria-label="Previous reach"
              onClick={() => setSel((s) => (s === null ? lev.nReach - 1 : (s - 1 + lev.nReach) % lev.nReach))}>◀</button>
            <button className="rounded border border-slate-300 px-2 py-1 hover:bg-sky-50" aria-label="Next reach"
              onClick={() => setSel((s) => (s === null ? 0 : (s + 1) % lev.nReach))}>▶</button>
            {selReach !== null && <button className="rounded border border-slate-300 px-2 py-1 hover:bg-sky-50" onClick={() => setSel(null)}>show all</button>}
          </div>
          {card}

          {bad ? <Unstable msg="the flooded area could not be computed." /> : (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <Stat label={`Flooded, ${len} m reaches`} value={`${area.now.toFixed(2)} km²`} tone="sky" />
              <Stat label="Change vs 1000 m" value={`${change >= 0 ? '+' : ''}${change.toFixed(1)} %`} tone={Math.abs(change) < 3 ? 'green' : 'red'} />
              <Stat label="Real basin (Khokana)" value={<span className="text-sm leading-tight block">500 m: −1.1 %<br />2000 m: +1.8 %</span>} />
            </div>
          )}
          <p className="text-[11.5px] text-slate-500 leading-snug">Flood of 1 m³/s per km² of drainage area, computed live with MRRpy&apos;s HAND method. The reach length barely changes the map, so it is fixed, not a setting.</p>

          <Legend items={[
            { swatch: <span className="inline-block w-4 h-1 rounded" style={{ background: `rgb(${qualRGB(0).join(',')})` }} />, label: mode === 'links' ? 'one colour per link' : 'one colour per reach' },
            { swatch: <span className="inline-block w-3 h-3 rounded-full border-2" style={{ borderColor: C.bad }} />, label: 'confluence' },
            ...(mode !== 'links' ? [{ swatch: <span className="text-[11px] leading-none">▲</span>, label: 'reach outlet' }] : []),
          ]} />
        </div>
      </div>

      <LookFor items={[
        <>Step through <b>1 · Links</b> → <b>2 · Reaches</b>: long links are cut into equal pieces; short links stay whole.</>,
        <>In <b>3 · Land</b> the valley splits into patches. Each patch floods to its own reach&apos;s level, so levels can jump at a patch boundary.</>,
        <>Move <b>Reach length</b> from 250 to 3000 m: the number of reaches changes a lot, the flooded area only by a few per cent.</>,
      ]} />
    </WidgetFrame>
  );
}
