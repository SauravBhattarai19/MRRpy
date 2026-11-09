'use client';

// §7.9 — HAND's main limit. One valley narrows to a 90 m gorge; the same flood
// is mapped by HAND and by MRRpy's 2D model (frames from scripts/export_ch7.py,
// both computed with the package's own code). HAND gives each reach a level
// from its own section; the 2D ponds water behind the gorge.
// The valley is drawn lying down (flow left → right) so the two maps and the
// long profile share one axis: distance down the valley.

import React, { useEffect, useMemo, useState } from 'react';
import { b64ToBytes, decodeZ } from '@/lib/flood/hand';
import { C, DepthBar, Legend, Loading, LookFor, RasterCanvas, Slider, Stat, Unstable, WidgetFrame, depthRGB, hillshade } from './ui';

interface GorgeData {
  ny: number; nx: number; dx: number; col0: number; riverCol: number; zmin: number;
  z_cm: string; bed2d_cm: string; valleyGradient: number; gorgeKm: [number, number];
  timesH: number[]; inflow: number[]; frameTimesH: number[]; depthStepM: number;
  hand: string; twoD: string; handMax: string; twoDMax: string;
  floodedKm2: { hand: number; twoD: number }; massError: number;
}

const D_MAX = 8; // depth colour scale top [m]
const SCALE = 3;

export default function GorgeWidget() {
  const [data, setData] = useState<GorgeData | null>(null);
  const [k, setK] = useState(12); // frame (hour) — the flood peak
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    let live = true;
    import('@/data/ch7/gorge.json').then((m) => live && setData((m.default ?? m) as unknown as GorgeData));
    return () => { live = false; };
  }, []);

  useEffect(() => {
    if (!playing || !data) return;
    const id = setInterval(() => setK((x) => (x + 1) % data.frameTimesH.length), 350);
    return () => clearInterval(id);
  }, [playing, data]);

  const d = useMemo(() => {
    if (!data) return null;
    const { ny, nx, dx, riverCol } = data;
    const z = decodeZ(data.z_cm, data.zmin);
    const bed = decodeZ(data.bed2d_cm, data.zmin);
    const hand = b64ToBytes(data.hand), twoD = b64ToBytes(data.twoD);
    const hMax = b64ToBytes(data.handMax), tMax = b64ToBytes(data.twoDMax);
    const shade = hillshade(z, ny, nx, dx, 2);
    const ref = Float64Array.from({ length: ny }, (_, r) => 1000 - data.valleyGradient * (r + 0.5) * dx);
    const s = data.depthStepM;
    // highest level along the river (above the valley trend)
    const lvlH = (f: Uint8Array, off: number) => Float64Array.from({ length: ny }, (_, r) => z[r * nx + riverCol] + f[off + r * nx + riverCol] * s - ref[r]);
    const lvl2 = (f: Uint8Array, off: number) => Float64Array.from({ length: ny }, (_, r) => bed[r] + f[off + r * nx + riverCol] * s - ref[r]);
    const peakH = lvlH(hMax, 0), peak2 = lvl2(tMax, 0);
    let maxDiff = -Infinity, rDiff = 0;
    for (let r = 0; r < ny; r++) if (peak2[r] - peakH[r] > maxDiff) { maxDiff = peak2[r] - peakH[r]; rDiff = r; }
    return { z, bed, hand, twoD, shade, ref, lvlH, lvl2, peakH, peak2, maxDiff, rDiff, bedRel: Float64Array.from(bed, (b, r) => b - ref[r]) };
  }, [data]);

  if (!data || !d) return <WidgetFrame title="HAND cannot see a gorge downstream" idea="Loading…"><Loading what="the gorge experiment" /></WidgetFrame>;

  const { ny, nx, dx } = data;
  const T = data.frameTimesH.length;
  const off = k * ny * nx;
  const s = data.depthStepM;
  const g0 = Math.round((data.gorgeKm[0] * 1000) / dx), g1 = Math.round((data.gorgeKm[1] * 1000) / dx);
  const nowH = d.lvlH(d.hand, off), now2 = d.lvl2(d.twoD, off);
  let wetH = 0, wet2 = 0;
  for (let i = 0; i < ny * nx; i++) { if (d.hand[off + i] * s >= 0.01) wetH++; if (d.twoD[off + i] * s >= 0.01) wet2++; }
  const bad = !Number.isFinite(d.maxDiff) || nowH.some((x) => !Number.isFinite(x));

  // transposed painter: canvas x = distance down the valley (row), y = across (col)
  const painter = (frames: Uint8Array) => (p: number): [number, number, number] => {
    const r = p % ny, c = Math.floor(p / ny);
    const i = r * nx + c;
    const dep = frames[off + i] * s;
    if (dep >= 0.01) return depthRGB(dep, D_MAX);
    const m = 0.55 + 0.45 * d.shade[i];
    return [Math.round(232 * m), Math.round(226 * m), Math.round(212 * m)];
  };
  // 2D − HAND: blue where the 2D is deeper, orange where HAND is deeper (±3 m)
  const diffPaint = (p: number): [number, number, number] => {
    const r = p % ny, c = Math.floor(p / ny);
    const i = r * nx + c;
    const a = d.twoD[off + i] * s, b = d.hand[off + i] * s;
    const m = 0.55 + 0.45 * d.shade[i];
    const grey: [number, number, number] = [Math.round(232 * m), Math.round(226 * m), Math.round(212 * m)];
    if (a < 0.01 && b < 0.01) return grey;
    const t = Math.max(-1, Math.min(1, (a - b) / 3));
    const tip: [number, number, number] = t >= 0 ? [33, 102, 172] : [217, 95, 2];
    const f = 0.15 + 0.85 * Math.abs(t);
    return [0, 1, 2].map((j) => Math.round(247 * (1 - f) + tip[j] * f)) as [number, number, number];
  };
  const mapOverlay = (label: string, note?: { r: number; text: string }) => (ctx: CanvasRenderingContext2D, sc: number) => {
    ctx.fillStyle = 'rgba(217,122,30,0.18)';
    ctx.fillRect(g0 * sc, 0, (g1 - g0) * sc, nx * sc);
    ctx.strokeStyle = 'rgba(217,122,30,0.9)'; ctx.setLineDash([4, 3]); ctx.lineWidth = 1.2;
    ctx.strokeRect(g0 * sc, 0.5, (g1 - g0) * sc, nx * sc - 1);
    ctx.setLineDash([]);
    ctx.font = `bold ${4.2 * sc}px sans-serif`;
    ctx.fillStyle = '#9a3412'; ctx.fillText('gorge', g0 * sc + 2, nx * sc - 3 * sc);
    ctx.fillStyle = C.ink; ctx.fillText(label, 3 * sc, 5 * sc);
    ctx.font = `${3.6 * sc}px sans-serif`;
    ctx.fillStyle = 'rgba(31,36,48,0.75)'; ctx.fillText('flow →', (ny - 26) * sc, 5 * sc);
    if (note) { ctx.font = `bold ${3.6 * sc}px sans-serif`; ctx.fillStyle = C.river; ctx.fillText(note.text, note.r * sc, nx * sc - 3 * sc); }
  };

  // ── long profile ──
  const W = 900, H = 230, PL = 46, PR = 10, PT = 14, PB = 34;
  const all = [...d.bedRel, ...d.peakH, ...d.peak2];
  const lo = Math.floor(Math.min(...all) - 0.5), hi = Math.ceil(Math.max(...all) + 0.5);
  const xOf = (r: number) => PL + ((r + 0.5) / ny) * (W - PL - PR);
  const yOf = (m: number) => PT + ((hi - m) / (hi - lo)) * (H - PT - PB);
  const path = (a: ArrayLike<number>) => Array.from(a, (m, r) => `${r ? 'L' : 'M'}${xOf(r).toFixed(1)},${yOf(m).toFixed(1)}`).join('');

  // ── hydrograph ──
  const HW = 900, HH = 110, HPL = 46, HPB = 26;
  const qMax = Math.max(...data.inflow) * 1.08;
  const tEnd = data.timesH[data.timesH.length - 1];
  const hx = (t: number) => HPL + (t / tEnd) * (HW - HPL - PR);
  const hy = (q: number) => 8 + (1 - q / qMax) * (HH - 8 - HPB);

  return (
    <WidgetFrame
      title="HAND cannot see a gorge downstream"
      idea={<>One valley narrows to a 90 m gorge. The same flood is mapped twice, both with MRRpy&apos;s code. HAND gives every reach a level from its own section. The 2D model lets water move, so it ponds behind the gorge.</>}
    >
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <button onClick={() => setPlaying((p) => !p)} className="rounded-lg bg-sky-700 text-white text-xs font-semibold px-3 py-1.5 hover:bg-sky-800">
              {playing ? '❚❚ Pause' : '▶ Play the flood'}
            </button>
            <span className="text-sm font-semibold text-slate-700 tabular-nums">hour {data.frameTimesH[k].toFixed(0)} of {data.frameTimesH[T - 1].toFixed(0)}</span>
          </div>
          <DepthBar dMax={D_MAX} />
        </div>
        <div className="rounded-lg overflow-hidden border border-slate-300">
          <RasterCanvas ny={nx} nx={ny} scale={SCALE} paint={painter(d.hand)} deps={[k, d]} overlay={mapOverlay('HAND')}
            ariaLabel="HAND flood depth along the valley, flow from left to right" />
        </div>
        <div className="rounded-lg overflow-hidden border border-slate-300">
          <RasterCanvas ny={nx} nx={ny} scale={SCALE} paint={painter(d.twoD)} deps={[k, d]}
            overlay={mapOverlay('2D', { r: Math.max(g0 - 95, 30), text: 'water ponds behind the gorge →' })}
            ariaLabel="2D flood depth along the valley, flow from left to right" />
        </div>

        <div className="rounded-lg overflow-hidden border border-slate-300">
          <RasterCanvas ny={nx} nx={ny} scale={SCALE} paint={diffPaint} deps={[k, d]} overlay={mapOverlay('2D minus HAND')}
            ariaLabel="Difference in depth, 2D minus HAND: blue where the 2D is deeper, orange where HAND is deeper" />
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-600 -mt-0.5">
          <span>2D minus HAND:</span>
          <span className="inline-block h-2.5 w-36 rounded" style={{ background: 'linear-gradient(90deg, rgb(217,95,2), rgb(247,247,247), rgb(33,102,172))' }} />
          <span className="font-mono">HAND deeper by 3 m · same · 2D deeper by 3 m</span>
        </div>

        <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-lg border border-slate-200 bg-white" role="img"
          aria-label="Highest water level along the river: HAND in orange, 2D in blue, bed in brown">
          <rect x={xOf(g0) - (W - PL - PR) / ny / 2} y={PT} width={((g1 - g0) / ny) * (W - PL - PR)} height={H - PT - PB} fill="rgba(217,122,30,0.15)" />
          {[lo, Math.round((lo + hi) / 2), hi].map((m) => (
            <g key={m}>
              <line x1={PL} x2={W - PR} y1={yOf(m)} y2={yOf(m)} stroke="#e2e8f0" />
              <text x={PL - 6} y={yOf(m) + 3.5} textAnchor="end" fontSize={10} fill={C.soft} fontFamily="monospace">{m}</text>
            </g>
          ))}
          <path d={path(d.peakH)} fill="none" stroke="#D97A1E" strokeWidth={1} strokeDasharray="3 3" opacity={0.6} />
          <path d={path(d.peak2)} fill="none" stroke={C.water} strokeWidth={1} strokeDasharray="3 3" opacity={0.6} />
          <path d={path(d.bedRel)} fill="none" stroke={C.ground} strokeWidth={1.4} />
          <path d={path(nowH)} fill="none" stroke="#D97A1E" strokeWidth={2.4} />
          <path d={path(now2)} fill="none" stroke={C.water} strokeWidth={2.4} />
          <text x={xOf(d.rDiff)} y={yOf(d.peak2[d.rDiff]) - 8} textAnchor="end" fontSize={11} fill={C.river} fontWeight={700}>
            2D rises towards the gorge
          </text>
          <text x={W - PR - 4} y={yOf(Math.min(...Array.from(d.peak2).slice(g1))) + 22} textAnchor="end" fontSize={11} fill="#9a3412" fontWeight={700}>
            HAND: highest in and below the narrow section
          </text>
          <text x={14} y={(PT + H - PB) / 2} fontSize={10.5} fill={C.ink} textAnchor="middle" transform={`rotate(-90 14 ${(PT + H - PB) / 2})`}>m above valley trend</text>
          {[0, 2, 4, 6, 8].map((km) => (
            <text key={km} x={xOf((km * 1000) / dx)} y={H - PB + 14} textAnchor="middle" fontSize={10} fill={C.soft} fontFamily="monospace">{km} km</text>
          ))}
          <text x={(PL + W) / 2} y={H - 4} textAnchor="middle" fontSize={10.5} fill={C.ink}>distance down the valley — water level along the river at hour {data.frameTimesH[k].toFixed(0)} (dashed: highest over the whole flood)</text>
        </svg>

        <svg viewBox={`0 0 ${HW} ${HH}`} className="w-full rounded-lg border border-slate-200 bg-white cursor-pointer" role="img"
          aria-label="Inflow hydrograph; click to choose the hour"
          onClick={(e) => {
            const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const t = (((e.clientX - rect.left) / rect.width) * HW - HPL) / (HW - HPL - PR) * tEnd;
            setK(Math.min(Math.max(Math.round(t), 0), T - 1));
          }}>
          <path d={data.inflow.map((q, j) => `${j ? 'L' : 'M'}${hx(data.timesH[j]).toFixed(1)},${hy(q).toFixed(1)}`).join('')} fill="none" stroke={C.ink} strokeWidth={1.6} />
          <line x1={hx(data.frameTimesH[k])} x2={hx(data.frameTimesH[k])} y1={6} y2={HH - HPB} stroke={C.bad} strokeWidth={2} />
          <text x={HPL - 6} y={hy(900) + 4} textAnchor="end" fontSize={10} fill={C.soft} fontFamily="monospace">900</text>
          <text x={HPL - 6} y={hy(0) + 4} textAnchor="end" fontSize={10} fill={C.soft} fontFamily="monospace">0</text>
          {[0, 12, 24, 36].map((t) => <text key={t} x={hx(t)} y={HH - 10} textAnchor={t === 36 ? 'end' : 'middle'} fontSize={10} fill={C.soft} fontFamily="monospace">{t} h</text>)}
          <text x={HW - PR - 4} y={20} textAnchor="end" fontSize={11} fill={C.ink}>flood entering at the top of the valley [m³/s] — click to pick the hour</text>
        </svg>
        <Slider label="Hour" value={k} min={0} max={T - 1} step={1} display={`${data.frameTimesH[k].toFixed(0)} h`} onChange={(x) => { setPlaying(false); setK(x); }} />

        {bad ? <Unstable msg="the saved flood frames could not be read." /> : (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="Flooded now, HAND" value={`${((wetH * dx * dx) / 1e6).toFixed(2)} km²`} />
            <Stat label="Flooded now, 2D" value={`${((wet2 * dx * dx) / 1e6).toFixed(2)} km²`} tone="sky" />
            <Stat label="Largest, HAND → 2D" value={<span className="text-base">{data.floodedKm2.hand.toFixed(2)} → {data.floodedKm2.twoD.toFixed(2)} km²</span>} tone="sky" />
            <Stat label="2D level above HAND" value={`up to ${d.maxDiff.toFixed(1)} m`} tone="red" />
          </div>
        )}
        <Legend items={[
          { swatch: <span className="inline-block w-4 h-1 rounded" style={{ background: '#D97A1E' }} />, label: 'HAND water level' },
          { swatch: <span className="inline-block w-4 h-1 rounded" style={{ background: C.water }} />, label: '2D water level' },
          { swatch: <span className="inline-block w-4 h-1 rounded" style={{ background: C.ground }} />, label: 'river bed' },
          { swatch: 'rgba(217,122,30,0.25)', label: 'gorge (6.0–6.6 km, 90 m wide)' },
        ]} />
        <p className="text-[12px] text-slate-500 leading-snug">
          Same ground, roughness and inflow for both. 2D water balance error {data.massError.toExponential(0)}. The 2D model that sees the gorge is built in Chapter 8.
        </p>
      </div>
      <LookFor items={[
        <>Press <b>Play</b>: the <b>2D minus HAND</b> strip turns blue for about 3 km above the gorge. There the 2D water is deeper and wider; HAND does not see it.</>,
        <>In the profile the <span className="text-sky-800 font-semibold">blue 2D level</span> climbs smoothly towards the gorge; the <span className="text-orange-700 font-semibold">orange HAND level</span> jumps reach by reach.</>,
        <>HAND puts its highest water <i>in and below</i> the gorge, where the section is narrow, not behind it where the water really backs up.</>,
      ]} />
    </WidgetFrame>
  );
}
