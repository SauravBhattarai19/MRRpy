'use client';

// §7.4 — the carve-only river bed. A long profile of one river: the DEM shows
// a bridge, a "dam" where a gorge is narrower than a cell, and metre-scale
// steps. MRRpy's riverBedProfile lowers river cells (never raises them) until
// the bed never rises downstream; HAND is measured from that bed.

import React, { useMemo, useRef, useState } from 'react';
import { gradedRiverBed, reachSlope, riverBedProfile } from '@/lib/flood/hand';
import { C, Legend, LookFor, Slider, Stat, Toggle, Unstable, WidgetFrame } from './ui';

const N = 120; // river cells
const DX = 30; // m
const BRIDGE = [34, 35]; // cells under the bridge
const DAM0 = 70; // first cell of the DEM dam
const DAM_SHAPE = [2, 5, 8, 11, 12, 12, 12, 12, 11, 8, 5, 2].map((v) => v / 12);
const FP_ABOVE = 2.5; // the floodplain cell stands this far above the true river [m]

// deterministic smooth noise (so the picture is the same for everyone)
function smoothNoise(n: number, amp: number, seed: number): Float64Array {
  let s = seed;
  const rnd = () => { s = (s * 1664525 + 1013904223) % 4294967296; return s / 4294967296 - 0.5; };
  const raw = Array.from({ length: n }, rnd);
  const out = new Float64Array(n);
  let mx = 1e-12;
  for (let i = 0; i < n; i++) {
    let a = 0, w = 0;
    for (let k = -2; k <= 2; k++) { const j = i + k; if (j >= 0 && j < n) { const ww = 3 - Math.abs(k); a += raw[j] * ww; w += ww; } }
    out[i] = a / w;
    mx = Math.max(mx, Math.abs(out[i]));
  }
  for (let i = 0; i < n; i++) out[i] = (amp * out[i]) / mx;
  return out;
}
const NOISE = smoothNoise(N, 0.25, 7);

export default function CarveBedWidget() {
  const [bridge, setBridge] = useState(4);
  const [dam, setDam] = useState(12);
  const [steps, setSteps] = useState(true);
  const [fpCell, setFpCell] = useState(DAM0 + 5);
  const [graded, setGraded] = useState<'off' | 'on'>('off');
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<null | 'bridge' | 'dam'>(null);

  const prof = useMemo(() => {
    const truth = new Float64Array(N), z = new Float64Array(N);
    for (let i = 0; i < N; i++) {
      truth[i] = 100 - 0.0012 * i * DX;
      // DEM "water flattening": flat runs ending in steps of 1.2 m, plus noise
      z[i] = steps ? Math.round(truth[i] / 1.2) * 1.2 + 0.25 + NOISE[i] : truth[i] + 0.25;
    }
    for (const b of BRIDGE) z[b] += bridge;
    DAM_SHAPE.forEach((f, k) => { z[DAM0 + k] += f * dam; });
    // a chain: cell i drains to i+1; the last cell is the outlet
    const ds = Int32Array.from({ length: N }, (_, i) => (i < N - 1 ? i + 1 : -1));
    const order = Int32Array.from({ length: N }, (_, k) => N - 1 - k); // outlet first
    const dist = new Float64Array(N).fill(DX);
    const drains = new Uint8Array(N).fill(1);
    const carve = riverBedProfile(order, ds, drains, z);
    const sReach = reachSlope(ds, carve, dist, DX, Float64Array.from({ length: N }, (_, i) => i + 1),
      new Float64Array(N).fill(1e-3), 1000, 1e-4);
    const grade = gradedRiverBed(order, ds, dist, drains, z, sReach);
    let maxLow = 0, at = 0, nLow = 0;
    for (let i = 0; i < N; i++) {
      const d = z[i] - carve[i];
      if (d > 0.005) nLow++;
      if (d > maxLow) { maxLow = d; at = i; }
    }
    return { truth, z, carve, grade, maxLow, at, nLow };
  }, [bridge, dam, steps]);

  const ok = [prof.z, prof.carve, prof.grade].every((a) => a.every(Number.isFinite));

  // ── geometry ──
  const W = 760, H = 390, PL = 50, PR = 16, PT = 22, PB = 44;
  const zLo = Math.min(...prof.carve) - 1;
  const zHi = Math.max(...prof.z) + 2;
  const xOf = (i: number) => PL + ((i + 0.5) / N) * (W - PL - PR);
  const yOf = (m: number) => PT + ((zHi - m) / (zHi - zLo)) * (H - PT - PB);
  const zOfY = (py: number) => zHi - ((py - PT) / (H - PT - PB)) * (zHi - zLo);
  const step = (a: Float64Array) => {
    let d = '';
    const cw = (W - PL - PR) / N;
    for (let i = 0; i < N; i++) {
      const x0 = PL + i * cw, x1 = x0 + cw;
      d += `${i ? 'L' : 'M'}${x0.toFixed(1)},${yOf(a[i]).toFixed(1)}L${x1.toFixed(1)},${yOf(a[i]).toFixed(1)}`;
    }
    return d;
  };
  // the lowered area: polygon between raw (top) and carved (bottom)
  const lowered = (() => {
    const cw = (W - PL - PR) / N;
    const polys: string[] = [];
    let cur: string[] = [], bot: string[] = [];
    for (let i = 0; i <= N; i++) {
      const low = i < N && prof.z[i] - prof.carve[i] > 0.005;
      if (low) {
        const x0 = PL + i * cw, x1 = x0 + cw;
        cur.push(`${x0},${yOf(prof.z[i])}`, `${x1},${yOf(prof.z[i])}`);
        bot.unshift(`${x1},${yOf(prof.carve[i])}`, `${x0},${yOf(prof.carve[i])}`);
      } else if (cur.length) {
        polys.push([...cur, ...bot].join(' '));
        cur = []; bot = [];
      }
    }
    return polys;
  })();

  const onMove = (e: React.PointerEvent) => {
    if (!drag.current || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const py = ((e.clientY - rect.top) / rect.height) * H;
    const zz = zOfY(py);
    if (drag.current === 'bridge') {
      const base = prof.z[BRIDGE[0]] - bridge;
      setBridge(Math.round(Math.min(Math.max(zz - base, 0), 8) * 2) / 2);
    } else {
      const base = prof.z[DAM0 + 5] - dam;
      setDam(Math.round(Math.min(Math.max(zz - base, 0), 20)));
    }
  };

  const k = fpCell;
  const zFp = prof.truth[k] + FP_ABOVE;
  const handRaw = Math.max(zFp - prof.z[k], 0);
  const handBed = Math.max(zFp - prof.carve[k], 0);
  const xb = xOf(BRIDGE[0]) + (xOf(1) - xOf(0)) / 2;
  const xd = xOf(DAM0 + 5) + (xOf(1) - xOf(0)) / 2;

  return (
    <WidgetFrame tone="earth"
      title="Clear the river path — never dig a channel"
      idea={<>A DEM&apos;s river climbs over bridges, &ldquo;dams&rdquo; where a gorge is narrower than a cell, and steps. The carve-only bed lowers river cells — never raises them — until the bed never rises downstream. HAND is measured from that bed.</>}>
      {!ok && <Unstable msg="the profile produced a non-finite value; reset the sliders." />}
      <div className="flex flex-col lg:flex-row gap-5">
        <div className="flex-1 min-w-0">
          <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="w-full rounded-lg border border-slate-200 bg-gradient-to-b from-sky-50 to-white touch-none"
            role="img" aria-label="Long profile of a river: DEM elevation, carve-only bed and the lowered parts"
            onPointerMove={onMove} onPointerUp={() => { drag.current = null; }} onPointerLeave={() => { drag.current = null; }}>
            <defs>
              <pattern id="cb-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="6" height="6" fill="#fde2e2" />
                <line x1="0" y1="0" x2="0" y2="6" stroke={C.bad} strokeWidth="1.4" />
              </pattern>
            </defs>
            {/* ground below the carved bed */}
            <path d={`${step(prof.carve)}L${W - PR},${H - PB}L${PL},${H - PB}Z`} fill={C.groundFill} />
            {/* what carving removes */}
            {lowered.map((p, i) => <polygon key={i} points={p} fill="url(#cb-hatch)" opacity={0.9} />)}
            <path d={step(prof.z)} fill="none" stroke={C.ground} strokeWidth={1.6} />
            <path d={step(prof.carve)} fill="none" stroke="#D97A1E" strokeWidth={2.6} />
            {graded === 'on' && <path d={step(prof.grade)} fill="none" stroke={C.water} strokeWidth={2} strokeDasharray="7 4" />}

            {/* labels on the picture */}
            <text x={xb} y={yOf(prof.z[BRIDGE[0]]) - 22} textAnchor="middle" fontSize={11} fill={C.ink} fontWeight={600}>bridge</text>
            <text x={xd} y={yOf(prof.z[DAM0 + 5]) - 22} textAnchor="middle" fontSize={11} fill={C.ink} fontWeight={600}>DEM &ldquo;dam&rdquo; in a gorge</text>
            {prof.maxLow > 0.05 && (
              <text x={xOf(prof.at)} y={(yOf(prof.z[prof.at]) + yOf(prof.carve[prof.at])) / 2 + 4} textAnchor="middle"
                fontSize={11} fill={C.bad} fontWeight={700} stroke="white" strokeWidth={3} paintOrder="stroke">
                lowered {prof.maxLow.toFixed(1)} m
              </text>
            )}
            {/* drag handles */}
            {([['bridge', xb, prof.z[BRIDGE[0]]], ['dam', xd, prof.z[DAM0 + 5]]] as const).map(([id, x, zz]) => (
              <g key={id} style={{ cursor: 'ns-resize' }} onPointerDown={(e) => { drag.current = id; (e.target as Element).setPointerCapture?.(e.pointerId); }}>
                <circle cx={x} cy={yOf(zz)} r={11} fill="white" stroke={C.ink} strokeWidth={1.5} opacity={0.95} />
                <text x={x} y={yOf(zz) + 4} textAnchor="middle" fontSize={11} fill={C.ink} pointerEvents="none">↕</text>
              </g>
            ))}

            {/* the floodplain cell and its two HANDs */}
            <g>
              <line x1={xOf(k) - 5} x2={xOf(k) - 5} y1={yOf(zFp)} y2={yOf(prof.z[k])} stroke={C.bad} strokeWidth={1.6} strokeDasharray="3 3" />
              {Math.abs(prof.z[k] - zFp) > 0.3 && (
                <text x={xOf(k) - 12} y={yOf(Math.max(prof.z[k], zFp)) - 4} textAnchor="end" fontSize={10.5} fill={C.bad} fontWeight={700}
                  stroke="white" strokeWidth={3} paintOrder="stroke">
                  {prof.z[k] > zFp ? `raw DEM: "river" ${(prof.z[k] - zFp).toFixed(1)} m ABOVE the field` : `from raw DEM: ${handRaw.toFixed(1)} m`}
                </text>
              )}
              <line x1={xOf(k)} x2={xOf(k)} y1={yOf(zFp)} y2={yOf(prof.carve[k])} stroke="#D97A1E" strokeWidth={2} markerEnd="url(#cb-arr)" />
              <rect x={xOf(k) - 9} y={yOf(zFp) - 4} width={18} height={8} fill={C.good} stroke="white" />
              <text x={xOf(k) + 12} y={yOf(zFp) - 6} fontSize={10.5} fill={C.good} fontWeight={700}>field beside the river</text>
              <text x={xOf(k) + 12} y={yOf((zFp + prof.carve[k]) / 2) + 4} fontSize={10.5} fill="#B45309" fontWeight={700}
                stroke="white" strokeWidth={3} paintOrder="stroke">HAND from the bed: {handBed.toFixed(1)} m</text>
            </g>

            {/* axes */}
            <line x1={PL} x2={PL} y1={PT} y2={H - PB} stroke="#94a3b8" />
            {Array.from({ length: 6 }, (_, j) => zLo + ((zHi - zLo) * j) / 5).map((m) => (
              <g key={m}>
                <line x1={PL - 4} x2={PL} y1={yOf(m)} y2={yOf(m)} stroke="#94a3b8" />
                <text x={PL - 7} y={yOf(m) + 3.5} textAnchor="end" fontSize={10} fill={C.soft} fontFamily="monospace">{m.toFixed(0)}</text>
              </g>
            ))}
            {[0, 1, 2, 3].map((km) => (
              <text key={km} x={PL + ((km * 1000) / (N * DX)) * (W - PL - PR)} y={H - PB + 14} textAnchor="middle" fontSize={10} fill={C.soft} fontFamily="monospace">{km}</text>
            ))}
            <text x={(PL + W - PR) / 2} y={H - 8} textAnchor="middle" fontSize={10.5} fill={C.ink}>distance downstream (km) — flow →</text>
            <text x={13} y={(PT + H - PB) / 2} fontSize={10.5} fill={C.ink} textAnchor="middle" transform={`rotate(-90 13 ${(PT + H - PB) / 2})`}>elevation (m)</text>
          </svg>
          <Legend items={[
            { swatch: <span className="inline-block w-4 h-0.5" style={{ background: C.ground }} />, label: 'DEM along the river (raw)' },
            { swatch: <span className="inline-block w-4 h-1" style={{ background: '#D97A1E' }} />, label: 'carve-only bed (never rises downstream)' },
            { swatch: <span className="inline-block w-3.5 h-3.5 border border-red-400" style={{ background: 'repeating-linear-gradient(45deg,#fde2e2 0 3px,#C0392B 3px 4px)' }} />, label: 'lowered by carving' },
            ...(graded === 'on' ? [{ swatch: <span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: C.water }} />, label: 'graded bed (2D model, Chapter 8)' }] : []),
          ]} />
        </div>

        <div className="lg:w-64 flex-shrink-0 flex flex-col gap-3">
          <Slider label="Bridge height (or drag ↕)" value={bridge} min={0} max={8} step={0.5} display={`+${bridge.toFixed(1)} m`} onChange={setBridge} />
          <Slider label="DEM dam height (or drag ↕)" value={dam} min={0} max={20} step={1} display={`+${dam} m`} onChange={setDam}
            hint="A gorge narrower than a 30 m cell: the DEM sees the canyon walls, not the water." />
          <Toggle label="DEM steps" value={steps ? 'on' : 'off'} onChange={(v) => setSteps(v === 'on')}
            options={[{ value: 'on', label: 'DEM steps + noise' }, { value: 'off', label: 'smooth' }]} />
          <Slider label="Field position" value={fpCell} min={2} max={N - 3} step={1}
            display={`${((fpCell * DX) / 1000).toFixed(2)} km`} onChange={setFpCell}
            hint={`A field ${FP_ABOVE} m above the true river.`} />
          <div className="grid grid-cols-2 gap-2">
            <Stat label="HAND from raw DEM" value={`${handRaw.toFixed(1)} m`} tone={Math.abs(handRaw - FP_ABOVE) > 0.6 ? 'red' : 'slate'} />
            <Stat label="HAND from bed" value={`${handBed.toFixed(1)} m`} tone="green" />
            <Stat label="Cells lowered" value={`${prof.nLow} / ${N}`} />
            <Stat label="Largest" value={`${prof.maxLow.toFixed(1)} m`} tone="red" />
          </div>
          <p className="text-[12px] text-slate-600 leading-snug">
            {handRaw < FP_ABOVE - 0.6
              ? (prof.z[k] > zFp
                ? <>Measured from the raw DEM, the field lies <b>below</b> a &ldquo;river&rdquo; that is really a bridge or canyon wall: HAND 0, so it would flood at any flow at all.</>
                : <>Measured from the raw DEM, the field looks only {handRaw.toFixed(1)} m above a &ldquo;river&rdquo; that is really a bridge or canyon wall: it would flood far too easily.</>)
              : <>Here the raw river surface is close to the true one, so both HANDs agree. Move the field onto the dam or the bridge.</>}
          </p>
          <Toggle label="Graded bed" value={graded} onChange={setGraded}
            options={[{ value: 'off', label: 'carve only' }, { value: 'on', label: '+ graded bed (Ch 8)' }]} />
        </div>
      </div>
      <LookFor items={[
        <>Drag the <b>dam</b> handle up: the orange bed stays down at the river&apos;s level and the red hatching shows what is cut away. Nothing is ever raised.</>,
        <>Move the <b>field</b> onto the dam: from the raw DEM it seems to sit below the river; from the carved bed it is {FP_ABOVE} m above, as it really is.</>,
        <>Only the one-cell river line is lowered. No channel is dug beside it, and the land is never touched{graded === 'on' ? '. The dashed graded bed turns each drop into a ramp so a 2D model does not see a weir (Chapter 8)' : ''}.</>,
      ]} />
    </WidgetFrame>
  );
}
