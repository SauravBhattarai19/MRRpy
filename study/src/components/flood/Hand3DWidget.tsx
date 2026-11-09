'use client';

// §7.2 — HAND in 3-D. The synthetic valley as a drag-to-rotate block model
// (orthographic projection and painter's algorithm, as Chapter 1's 3-D view),
// with the HAND flood water on it. The switch morphs every cell's height from
// its elevation to its height above its river: the sloping valley floor sinks
// onto one level plane and the flood becomes one flat sheet.

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { handLevel, levelDepth, stageFromQ } from '@/lib/flood/hand';
import { useValley } from './useValley';
import { C, DepthBar, Legend, Loading, LookFor, Slider, Stat, Toggle, Unstable, WidgetFrame, depthRGB } from './ui';

const Q_MAX = 3; // largest flood on the slider [m³/s per km²]
const CAP = 14; // displayed heights are capped here [m] so hills don't dwarf the floor
const STRIDE = 2; // draw every 2nd cell (60 m blocks)
const H_RAMP = 12; // colour ramp top [m]
const RAMP: [number, number, number][] = [[102, 37, 6], [204, 76, 2], [254, 153, 41], [254, 227, 145], [255, 255, 229]];
function ramp(h: number): [number, number, number] {
  const x = Math.min(Math.max(h / H_RAMP, 0), 1) * (RAMP.length - 1);
  const k = Math.min(Math.floor(x), RAMP.length - 2), f = x - k;
  return [0, 1, 2].map((j) => RAMP[k][j] + f * (RAMP[k + 1][j] - RAMP[k][j])) as [number, number, number];
}
const rgb = (c: number[], m = 1, a = 1) => `rgba(${Math.round(c[0] * m)},${Math.round(c[1] * m)},${Math.round(c[2] * m)},${a})`;

const PRESETS = [
  { name: 'Oblique', az: 30, tilt: 50 },
  { name: 'From the outlet', az: 0, tilt: 35 },
  { name: 'Low angle', az: 20, tilt: 24 },
  { name: 'Bird’s eye', az: 20, tilt: 80 },
];

export default function Hand3DWidget() {
  const v = useValley();
  const [q, setQ] = useState(0.25);
  const [view, setView] = useState<'elev' | 'hand'>('elev');
  const [t, setT] = useState(view === 'hand' ? 1 : 0);
  const [exag, setExag] = useState(30);
  const [az, setAz] = useState(30);
  const [tilt, setTilt] = useState(50);
  const [shadeOn, setShadeOn] = useState<'on' | 'off'>('on');
  const [hud, setHud] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tops = useRef<{ poly: number[]; label: string }[]>([]);
  const dragRef = useRef<{ x: number; y: number; az: number; tilt: number } | null>(null);

  // morph animation between elevation (0) and HAND (1)
  const raf = useRef(0);
  useEffect(() => {
    const target = view === 'hand' ? 1 : 0;
    const t0 = performance.now(), from = t;
    const step = (now: number) => {
      const f = Math.min((now - t0) / 900, 1);
      const e = f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;
      setT(from + (target - from) * e);
      if (f < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  const lev = useMemo(() => {
    if (!v) return null;
    return handLevel(v.grid, v.grid.river, v.data.aChannelKm2, { qPeak: Float64Array.from(v.q1, (x) => x * Q_MAX) });
  }, [v]);

  const flood = useMemo(() => {
    if (!lev || !v) return null;
    const stage = Float64Array.from(lev.qPeak, (x, r) => stageFromQ(lev.rating.Q[r], lev.rating.y, (x * q) / Q_MAX).stage);
    const depth = levelDepth(lev, stage);
    let wet = 0;
    for (const d of depth) if (d >= 0.01) wet++;
    return { depth, km2: (wet * v.data.dx ** 2) / 1e6 };
  }, [lev, q, v]);

  // coarse grid: elevation above the outlet's bed and HAND, both capped
  const coarse = useMemo(() => {
    if (!v || !lev || !flood) return null;
    const { ny, nx } = v.data;
    const R = Math.ceil(ny / STRIDE), Cc = Math.ceil(nx / STRIDE);
    const zOut = lev.bed[v.data.outlet[0] * nx + v.data.outlet[1]];
    const zRel = new Float64Array(R * Cc), hand = new Float64Array(R * Cc), depth = new Float64Array(R * Cc);
    const idx = new Int32Array(R * Cc), river = new Uint8Array(R * Cc);
    for (let r = 0; r < R; r++) for (let c = 0; c < Cc; c++) {
      const i = r * STRIDE * nx + c * STRIDE, k = r * Cc + c;
      idx[k] = i;
      zRel[k] = Math.min(Math.max(v.grid.zRaw[i] - zOut, 0), CAP);
      hand[k] = Math.min(Number.isNaN(lev.hand[i]) ? zRel[k] : lev.hand[i], CAP);
      depth[k] = flood.depth[i];
      river[k] = v.grid.river[i];
    }
    return { R, Cc, zRel, hand, depth, idx, river };
  }, [v, lev, flood]);

  const ok = !coarse || (coarse.zRel.every(Number.isFinite) && coarse.hand.every(Number.isFinite) && coarse.depth.every(Number.isFinite));

  // ── render (only when something changes) ──
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !coarse || !ok) return;
    const ctx = cv.getContext('2d')!;
    const W = cv.width, H = cv.height;
    const { R, Cc } = coarse;
    const cellM = (v!.data.dx * STRIDE);
    const hs = exag / cellM; // metres → grid units
    const ground = Float64Array.from(coarse.zRel, (z, k) => ((1 - t) * z + t * coarse.hand[k]));
    const wTop = Float64Array.from(ground, (g, k) => (coarse.depth[k] >= 0.01 ? g + coarse.depth[k] : -Infinity));
    const phi = (az * Math.PI) / 180, th = (tilt * Math.PI) / 180;
    const cp = Math.cos(phi), sp = Math.sin(phi), ct = Math.cos(th), st = Math.sin(th);
    const scale = (0.8 * Math.min(W, H * 1.45)) / Math.hypot(R, Cc);
    const proj = (wx: number, wy: number, wz: number): [number, number] => [
      (wx * cp - wz * sp) * scale + W / 2,
      (wx * sp * st - wy * ct + wz * cp * st) * scale + H / 2 + 0.25 * CAP * hs * ct * scale,
    ];
    // NW sun, Lambert on the per-cell gradient normal (world: x east, y up, z south)
    const L = [-1, 1.3, -1];
    const ln = Math.hypot(L[0], L[1], L[2]);
    const lambert = (k: number, r: number, c: number) => {
      const h = (rr: number, cc: number) => ground[Math.min(Math.max(rr, 0), R - 1) * Cc + Math.min(Math.max(cc, 0), Cc - 1)] * hs;
      const gx = (h(r, c + 1) - h(r, c - 1)) / 2, gz = (h(r + 1, c) - h(r - 1, c)) / 2;
      const n = [-gx, 1, -gz], nn = Math.hypot(n[0], n[1], n[2]);
      return Math.max(0, (n[0] * L[0] + n[1] * L[1] + n[2] * L[2]) / (nn * ln));
    };
    const base = -1.5;
    const cells = Array.from({ length: R * Cc }, (_, k) => k);
    const depthOf = (k: number) => { const wx = (k % Cc) - (Cc - 1) / 2, wz = Math.floor(k / Cc) - (R - 1) / 2; return wx * sp + wz * cp; };
    cells.sort((a, b) => depthOf(a) - depthOf(b)); // far first
    ctx.clearRect(0, 0, W, H);
    const quad = (pts: [number, number][], fill: string) => {
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let j = 1; j < pts.length; j++) ctx.lineTo(pts[j][0], pts[j][1]);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
    };
    // visible side faces: +z (south) if cosφ>0, −z if <0; +x (east) if sinφ>0, −x if <0
    const sides: [number, number][] = [[cp >= 0 ? 1 : -1, 0], [0, sp >= 0 ? 1 : -1]]; // [dRow, dCol]
    const out: { poly: number[]; label: string }[] = [];
    for (const k of cells) {
      const r = Math.floor(k / Cc), c = k % Cc;
      const wx = c - (Cc - 1) / 2, wz = r - (R - 1) / 2;
      const g = ground[k] * hs;
      let col = coarse.river[k] ? [70, 100, 150] : ramp(ground[k]);
      const sh = shadeOn === 'on' ? 0.45 + 0.55 * lambert(k, r, c) : 0.92;
      // walls
      for (const [dr, dc] of sides) {
        const rn = r + dr, cn = c + dc;
        const gn = rn >= 0 && rn < R && cn >= 0 && cn < Cc ? ground[rn * Cc + cn] * hs : base;
        if (g <= gn) continue;
        const ex = wx + dc * 0.5, ez = wz + dr * 0.5;
        const ox = dr !== 0 ? 0.5 : 0, oz = dc !== 0 ? 0.5 : 0;
        quad([proj(ex - ox, g, ez - oz), proj(ex + ox, g, ez + oz), proj(ex + ox, gn, ez + oz), proj(ex - ox, gn, ez - oz)], rgb(col, sh * 0.68));
      }
      const top: [number, number][] = [proj(wx - 0.5, g, wz - 0.5), proj(wx + 0.5, g, wz - 0.5), proj(wx + 0.5, g, wz + 0.5), proj(wx - 0.5, g, wz + 0.5)];
      quad(top, rgb(col, sh));
      let poly = top.flat();
      // water
      const d = coarse.depth[k];
      if (d >= 0.01) {
        const wt = wTop[k] * hs;
        const wc = depthRGB(d);
        for (const [dr, dc] of sides) {
          const rn = r + dr, cn = c + dc;
          const inside = rn >= 0 && rn < R && cn >= 0 && cn < Cc;
          const nb = inside ? Math.max(wTop[rn * Cc + cn] * hs, ground[rn * Cc + cn] * hs) : base;
          const lo = Math.max(nb, g);
          if (wt <= lo + 1e-6) continue;
          const ex = wx + dc * 0.5, ez = wz + dr * 0.5;
          const ox = dr !== 0 ? 0.5 : 0, oz = dc !== 0 ? 0.5 : 0;
          quad([proj(ex - ox, wt, ez - oz), proj(ex + ox, wt, ez + oz), proj(ex + ox, lo, ez + oz), proj(ex - ox, lo, ez - oz)], rgb(wc, 0.8, 0.8));
        }
        const wq: [number, number][] = [proj(wx - 0.5, wt, wz - 0.5), proj(wx + 0.5, wt, wz - 0.5), proj(wx + 0.5, wt, wz + 0.5), proj(wx - 0.5, wt, wz + 0.5)];
        quad(wq, rgb(wc, 1, 0.82));
        poly = wq.flat();
      }
      const i = coarse.idx[k];
      out.push({
        poly,
        label: `(${Math.floor(i / v!.data.nx)}, ${i % v!.data.nx})  z = ${v!.grid.zRaw[i].toFixed(1)} m · HAND = ${Number.isNaN(lev!.hand[i]) ? '—' : lev!.hand[i].toFixed(2) + ' m'} · ${d >= 0.01 ? `${d.toFixed(2)} m deep` : 'dry'}`,
      });
    }
    tops.current = out;
    // orientation labels
    const label = (txt: string, r: number, c: number) => {
      const [x, y] = proj(c - (Cc - 1) / 2, ground[Math.min(r, R - 1) * Cc + Math.min(c, Cc - 1)] * hs + 3, r - (R - 1) / 2);
      ctx.font = 'bold 12px sans-serif';
      ctx.textAlign = 'center';
      ctx.lineWidth = 3.5;
      ctx.strokeStyle = 'white';
      ctx.strokeText(txt, x, y);
      ctx.fillStyle = C.ink;
      ctx.fillText(txt, x, y);
    };
    const [er, ec] = v!.data.entry, [or, oc] = v!.data.outlet;
    label('river enters', Math.floor(er / STRIDE), Math.floor(ec / STRIDE));
    label('outlet', Math.floor(or / STRIDE), Math.floor(oc / STRIDE));
  }, [coarse, t, exag, az, tilt, shadeOn, ok, v, lev]);

  const onMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const cv = canvasRef.current!;
    const rect = cv.getBoundingClientRect();
    if (dragRef.current) {
      const d = dragRef.current;
      setAz(((d.az - (e.clientX - d.x) * 0.4) % 360 + 360) % 360);
      setTilt(Math.min(Math.max(d.tilt + (e.clientY - d.y) * 0.3, 10), 85));
      return;
    }
    const x = ((e.clientX - rect.left) / rect.width) * cv.width, y = ((e.clientY - rect.top) / rect.height) * cv.height;
    const list = tops.current;
    for (let j = list.length - 1; j >= 0; j--) {
      const p = list[j].poly;
      let inside = false;
      for (let a = 0, b = 3; a < 4; b = a++) {
        const xa = p[2 * a], ya = p[2 * a + 1], xb = p[2 * b], yb = p[2 * b + 1];
        if ((ya > y) !== (yb > y) && x < ((xb - xa) * (y - ya)) / (yb - ya) + xa) inside = !inside;
      }
      if (inside) { setHud(list[j].label); return; }
    }
    setHud(null);
  };

  if (!v || !lev || !flood) return <WidgetFrame title="The valley in 3-D" idea="Loading…"><Loading /></WidgetFrame>;

  return (
    <WidgetFrame
      title="Flatten the valley: HAND in 3-D"
      idea={<>The valley floor slopes down towards the outlet, so no single flat water surface can flood it. Measure every cell from its own river instead, and the whole floor sinks onto one level — then one flat sheet of water floods it.</>}
    >
      {!ok && <Unstable msg="a displayed height became non-finite." />}
      <div className="flex flex-col lg:flex-row gap-5">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
            <Toggle label="Height of each block" value={view} onChange={setView}
              options={[{ value: 'elev', label: 'Ground as it is' }, { value: 'hand', label: 'Height above its river (HAND)' }]} />
            <DepthBar />
          </div>
          <div className="relative rounded-lg border border-slate-200 bg-gradient-to-b from-sky-100 to-white overflow-hidden">
            <canvas ref={canvasRef} width={760} height={470} role="img"
              aria-label="Three-dimensional block model of the valley with flood water; drag to rotate"
              className="w-full h-auto touch-none" style={{ cursor: dragRef.current ? 'grabbing' : 'grab' }}
              onPointerDown={(e) => { dragRef.current = { x: e.clientX, y: e.clientY, az, tilt }; (e.target as Element).setPointerCapture(e.pointerId); }}
              onPointerUp={() => { dragRef.current = null; }}
              onPointerMove={onMove}
              onPointerLeave={() => { if (!dragRef.current) setHud(null); }} />
            <div className="absolute left-2 top-2 rounded bg-white/85 px-2 py-1 text-[11px] font-mono text-slate-700">
              {hud ?? 'drag to rotate · point at a block'}
            </div>
            <div className="absolute right-2 top-2 rounded bg-white/85 px-2 py-1 text-[11px] font-semibold text-slate-700">
              {t < 0.5 ? 'block height = elevation above the outlet' : 'block height = height above its own river'}
            </div>
          </div>
          <Legend items={[
            { swatch: rgb(ramp(2)), label: 'low' },
            { swatch: rgb(ramp(11)), label: `high (heights capped at ${CAP} m)` },
            { swatch: 'rgb(70,100,150)', label: 'river cell' },
            { swatch: rgb(depthRGB(1.5), 1, 0.82), label: 'flood water' },
          ]} />
        </div>
        <div className="lg:w-64 flex-shrink-0 flex flex-col gap-3">
          <Slider label="Flood size" value={q} min={0.1} max={Q_MAX} step={0.05} display={`${q.toFixed(2)} m³/s per km²`} onChange={setQ}
            hint="Each river carries this much per km² draining to it." />
          <Slider label="Height exaggeration" value={exag} min={1} max={40} step={1} display={`× ${exag}`} onChange={setExag} />
          <Slider label="Azimuth (or drag sideways)" value={Math.round(az)} min={0} max={359} step={1} display={`${Math.round(az)}°`} onChange={setAz} />
          <Slider label="Tilt (or drag up/down)" value={Math.round(tilt)} min={10} max={85} step={1} display={`${Math.round(tilt)}°`} onChange={setTilt} />
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <button key={p.name} onClick={() => { setAz(p.az); setTilt(p.tilt); }}
                className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-sky-50">{p.name}</button>
            ))}
          </div>
          <Toggle label="Hillshading" value={shadeOn} onChange={setShadeOn}
            options={[{ value: 'on', label: 'hillshade on' }, { value: 'off', label: 'off' }]} />
          <Stat label="Flooded land" value={`${flood.km2.toFixed(2)} km²`} tone="sky" />
        </div>
      </div>
      <LookFor items={[
        <>With <b>Ground as it is</b>, the valley floor tilts down towards the outlet. The water follows the tilt: it is not one flat surface.</>,
        <>Press <b>Height above its river</b> and watch the floor sink onto one level. The water becomes one flat sheet: everything lower than it is flooded.</>,
        <>Watch the floor colours: light near where the river enters, dark at the outlet — it tilts. In HAND every floor cell turns dark: all of it is close to its river. Raise the <b>Flood size</b> and the sheet climbs the hillslopes.</>,
      ]} />
    </WidgetFrame>
  );
}
