'use client';

import React, { useState, useMemo } from 'react';

// ─────────────────────────────────────────────────────────────────────────
// Historical wide-sheet illustration; not the current production kernel.
//
//   S_w      = S0 + theta * (h_i - h_ds) / dist        (water-surface slope)
//   S_eff    = max(S_w, 0)                              (adverse grad -> no discharge)
//   WSE_i    = z_i + h_i ;  WSE_ds = z_ds + h_ds
//   h_higher = max(WSE_i, WSE_ds) - max(z_i, z_ds)      (CASC2D / GSSHA conveyance depth)
//   h_flow   = (1 - theta) * h_i + theta * h_higher     (theta = 1 in OPM production)
//   Q_diff   = (1/n) * h_flow^(5/3) * S_eff^(1/2) * cell_size
// ─────────────────────────────────────────────────────────────────────────

const THETA = 1.0; // OPM production default — DIFFUSION_THETA = 1.0 (full diffusive)
const N = 0.05; // Manning's n
const DIST = 100; // m, flow-path length (also used as cell_size here)
const MIN_DEPTH = 0.001; // m, wet/dry conveyance floor

interface Result {
  z_i: number;
  z_ds: number;
  h_i: number;
  h_ds: number;
  wse_i: number;
  wse_ds: number;
  h_higher: number;
  h_naive: number; // naive scheme: just use h_i, ignoring the downstream bed
  h_flow: number;
  S_w: number;
  S_eff: number;
  Q_diff: number;
  Q_naive: number; // what you'd get if conveyance depth were just h_i (S_eff unchanged)
  isAdverseBed: boolean;
  divergence: number; // % difference between h_higher and h_naive
}

function compute(z_i: number, z_ds: number, h_i: number, h_ds: number): Result {
  const wse_i = z_i + h_i;
  const wse_ds = z_ds + h_ds;

  const S_w = (z_i - z_ds) / DIST + (THETA * (h_i - h_ds)) / DIST;
  const S_eff = Math.max(S_w, 0);

  const h_higher = Math.max(wse_i, wse_ds) - Math.max(z_i, z_ds);
  const h_flow = Math.max((1 - THETA) * h_i + THETA * h_higher, MIN_DEPTH);
  const h_naive = Math.max(h_i, MIN_DEPTH);

  const Q_diff = (1 / N) * Math.pow(h_flow, 5 / 3) * Math.pow(S_eff, 0.5) * DIST;
  const Q_naive = (1 / N) * Math.pow(h_naive, 5 / 3) * Math.pow(S_eff, 0.5) * DIST;

  const isAdverseBed = z_ds > z_i;
  const divergence = h_naive > 0 ? ((h_higher - h_naive) / h_naive) * 100 : 0;

  return {
    z_i,
    z_ds,
    h_i,
    h_ds,
    wse_i,
    wse_ds,
    h_higher,
    h_naive,
    h_flow,
    S_w,
    S_eff,
    Q_diff,
    Q_naive,
    isAdverseBed,
    divergence,
  };
}

function fmt(n: number, d = 4): string {
  return n.toFixed(d);
}

interface Preset {
  key: string;
  label: string;
  z_i: number;
  z_ds: number;
  h_i: number;
  h_ds: number;
  blurb: string;
}

const PRESETS: Preset[] = [
  {
    key: 'normal',
    label: 'Normal downhill',
    z_i: 5.0,
    z_ds: 4.7,
    h_i: 0.3,
    h_ds: 0.1,
    blurb: 'Bed and water surface both fall downstream — the ordinary case.',
  },
  {
    key: 'adverse',
    label: 'Adverse bed (D8 saddle)',
    z_i: 5.0,
    z_ds: 5.3,
    h_i: 0.5,
    h_ds: 0.1,
    blurb:
      "z_ds > z_i: the downstream cell's ground is locally HIGHER, but the water surface still drains forward.",
  },
];

// ─────────────────────────────────────────────────────────────────────────
// SVG side-view diagram of the two cells
// ─────────────────────────────────────────────────────────────────────────
const SVG_W = 360;
const SVG_H = 210;
const PAD_L = 32;
const PAD_R = 20;
const PAD_T = 26;
const PAD_B = 30;

function CellDiagram({ result }: { result: Result }) {
  const { z_i, z_ds, h_i, h_ds, wse_i, wse_ds, h_higher } = result;

  const zMin = Math.min(z_i, z_ds) - 0.3;
  const zMax = Math.max(wse_i, wse_ds, z_i, z_ds) + 0.3;
  function yOfZ(z: number): number {
    const t = (z - zMin) / (zMax - zMin);
    return SVG_H - PAD_B - t * (SVG_H - PAD_T - PAD_B);
  }

  const cellW = (SVG_W - PAD_L - PAD_R) / 2;
  const xI0 = PAD_L;
  const xI1 = PAD_L + cellW;
  const xDs0 = xI1;
  const xDs1 = xI1 + cellW;

  const bedI = yOfZ(z_i);
  const bedDs = yOfZ(z_ds);
  const wseILine = yOfZ(wse_i);
  const wseDsLine = yOfZ(wse_ds);
  const zHigherLine = yOfZ(Math.max(z_i, z_ds));
  const hHigherTop = yOfZ(Math.max(wse_i, wse_ds));

  const wseHigherInDs = wse_ds > wse_i;

  return (
    <svg
      width={SVG_W}
      height={SVG_H}
      className="block overflow-visible"
      style={{ maxWidth: '100%' }}
    >
      <line
        x1={PAD_L}
        y1={SVG_H - PAD_B}
        x2={SVG_W - PAD_R}
        y2={SVG_H - PAD_B}
        stroke="#e2e8f0"
        strokeWidth={1}
      />

      {/* Bed (brown/tan) */}
      <polygon
        points={`${xI0},${SVG_H - PAD_B} ${xI0},${bedI} ${xI1},${bedI} ${xI1},${bedDs} ${xDs1},${bedDs} ${xDs1},${SVG_H - PAD_B}`}
        fill="#c9a577"
        stroke="#92703f"
        strokeWidth={1}
      />

      {/* Water depth, cell i */}
      <rect
        x={xI0}
        y={wseILine}
        width={cellW}
        height={Math.max(bedI - wseILine, 0)}
        fill="#60a5fa"
        opacity={0.75}
      />
      {/* Water depth, cell ds */}
      <rect
        x={xDs0}
        y={wseDsLine}
        width={cellW}
        height={Math.max(bedDs - wseDsLine, 0)}
        fill="#60a5fa"
        opacity={0.75}
      />

      {/* h_higher band: from max(z_i,z_ds) up to max(WSE_i,WSE_ds), spanning both cells */}
      <rect
        x={xI0}
        y={hHigherTop}
        width={cellW * 2}
        height={Math.max(zHigherLine - hHigherTop, 0)}
        fill="#a855f7"
        opacity={0.18}
      />
      <line
        x1={xI0}
        y1={zHigherLine}
        x2={xDs1}
        y2={zHigherLine}
        stroke="#a855f7"
        strokeWidth={1}
        strokeDasharray="2,2"
      />

      {/* Cell divider */}
      <line
        x1={xI1}
        y1={PAD_T}
        x2={xI1}
        y2={SVG_H - PAD_B}
        stroke="#94a3b8"
        strokeWidth={1}
        strokeDasharray="3,3"
      />

      {/* Water surface lines */}
      <line x1={xI0} y1={wseILine} x2={xI1} y2={wseILine} stroke="#1d4ed8" strokeWidth={2} />
      <line
        x1={xDs0}
        y1={wseDsLine}
        x2={xDs1}
        y2={wseDsLine}
        stroke={wseHigherInDs ? '#dc2626' : '#1d4ed8'}
        strokeWidth={2}
      />
      <line
        x1={xI1}
        y1={wseILine}
        x2={xDs0}
        y2={wseDsLine}
        stroke={wseHigherInDs ? '#dc2626' : '#1d4ed8'}
        strokeWidth={1.5}
        strokeDasharray="2,2"
      />

      {/* h_higher bracket on the higher-bed side */}
      <line
        x1={wse_ds >= wse_i ? xDs1 - 6 : xI0 + 6}
        y1={hHigherTop}
        x2={wse_ds >= wse_i ? xDs1 - 6 : xI0 + 6}
        y2={zHigherLine}
        stroke="#7e22ce"
        strokeWidth={1.5}
      />
      <text
        x={wse_ds >= wse_i ? xDs1 - 10 : xI0 + 10}
        y={(hHigherTop + zHigherLine) / 2 + 3}
        textAnchor={wse_ds >= wse_i ? 'end' : 'start'}
        fontSize={8}
        fontWeight="bold"
        fill="#7e22ce"
      >
        h_higher
      </text>

      {/* Bed labels */}
      <text x={xI0 + cellW / 2} y={bedI + 14} textAnchor="middle" fontSize={9} fill="#6b4f2a">
        z_i = {z_i.toFixed(2)}
      </text>
      <text x={xDs0 + cellW / 2} y={bedDs + 14} textAnchor="middle" fontSize={9} fill="#6b4f2a">
        z_ds = {z_ds.toFixed(2)}
      </text>

      {/* WSE labels */}
      <text
        x={xI0 + cellW / 2}
        y={wseILine - 5}
        textAnchor="middle"
        fontSize={9}
        fontWeight="bold"
        fill="#1d4ed8"
      >
        WSE_i = {wse_i.toFixed(2)}
      </text>
      <text
        x={xDs0 + cellW / 2}
        y={wseDsLine - 5}
        textAnchor="middle"
        fontSize={9}
        fontWeight="bold"
        fill={wseHigherInDs ? '#dc2626' : '#1d4ed8'}
      >
        WSE_ds = {wse_ds.toFixed(2)}
      </text>

      {/* Cell labels */}
      <text x={xI0 + 4} y={PAD_T - 8} fontSize={10} fontWeight="bold" fill="#334155">
        Cell i (upstream)
      </text>
      <text x={xDs0 + 4} y={PAD_T - 8} fontSize={10} fontWeight="bold" fill="#334155">
        Cell ds (downstream)
      </text>

      {result.isAdverseBed && (
        <text
          x={SVG_W / 2}
          y={SVG_H - 6}
          textAnchor="middle"
          fontSize={9}
          fontWeight="bold"
          fill="#b45309"
        >
          z_ds &gt; z_i — adverse / D8-saddle bed
        </text>
      )}
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Root widget
// ─────────────────────────────────────────────────────────────────────────
export default function ConveyanceDepthWidget() {
  const [presetKey, setPresetKey] = useState<string>('adverse');
  const [z_i, setZi] = useState(5.0);
  const [z_ds, setZds] = useState(5.3);
  const [h_i, setHi] = useState(0.5);
  const [h_ds, setHds] = useState(0.1);

  function applyPreset(p: Preset) {
    setPresetKey(p.key);
    setZi(p.z_i);
    setZds(p.z_ds);
    setHi(p.h_i);
    setHds(p.h_ds);
  }

  const result = useMemo(() => compute(z_i, z_ds, h_i, h_ds), [z_i, z_ds, h_i, h_ds]);

  const diverges = Math.abs(result.divergence) > 0.5;

  return (
    <div className="not-prose my-8 rounded-2xl border border-slate-200 bg-white shadow-xl overflow-hidden font-sans">
      <div className="bg-gradient-to-r from-purple-700 to-indigo-900 px-6 py-4">
        <h3 className="text-white font-bold text-lg tracking-tight">
          Conveyance Depth: GSSHA-Style &ldquo;Depth Over the Higher Bed&rdquo;
        </h3>
        <p className="text-purple-200 text-sm mt-0.5">
          The real <code>diffusive_wave_discharge()</code> from OPM&apos;s production
          routing_utils.py
        </p>
      </div>

      <div className="p-6 flex flex-col gap-6">
        {/* ───────── Part A: interactive scenario ───────── */}
        <div>
          <h4 className="text-sm font-bold text-slate-700 uppercase tracking-wide mb-2">
            Part A — The D8-Saddle Scenario
          </h4>

          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-900 mb-4">
            <span className="font-semibold">Why the upstream depth alone is not always right: </span>
            On a normal downhill bed, the upstream cell&apos;s own depth h_i is the correct
            conveyance depth — water flows off the higher bed into the lower. But at a{' '}
            <strong>D8 saddle</strong>, DEM step, or flow reversal, the downstream cell&apos;s{' '}
            <em>ground</em> can actually be higher (z_ds &gt; z_i) even while its water surface is
            still lower than upstream — water is conveyed across that higher downstream lip, and
            the relevant depth is the depth of water <em>over that higher bed</em>, not over the
            upstream one. A naive scheme that always uses h_i either misjudges how much
            cross-sectional flow area is actually available, or — in some adverse-bed schemes —
            could drain a cell when it shouldn&apos;t be able to.
          </div>

          {/* Preset buttons */}
          <div className="flex gap-2 flex-wrap mb-3">
            {PRESETS.map((p) => (
              <button
                key={p.key}
                onClick={() => applyPreset(p)}
                className={`px-4 py-2 rounded-lg text-sm font-semibold transition-colors border ${
                  presetKey === p.key
                    ? p.key === 'adverse'
                      ? 'bg-amber-600 text-white border-amber-600'
                      : 'bg-sky-600 text-white border-sky-600'
                    : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-slate-500 mb-4">
            {PRESETS.find((p) => p.key === presetKey)?.blurb}
          </p>

          <div className="flex flex-col lg:flex-row gap-6">
            {/* Sliders */}
            <div className="w-full lg:w-64 shrink-0 flex flex-col gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-xs font-semibold text-slate-600">
                  z_i (upstream bed) = {z_i.toFixed(2)} m
                </label>
                <input
                  type="range"
                  min={0}
                  max={10}
                  step={0.1}
                  value={z_i}
                  onChange={(e) => {
                    setPresetKey('');
                    setZi(+e.target.value);
                  }}
                  className="w-full"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs font-semibold text-slate-600">
                  z_ds (downstream bed) = {z_ds.toFixed(2)} m
                </label>
                <input
                  type="range"
                  min={0}
                  max={10}
                  step={0.1}
                  value={z_ds}
                  onChange={(e) => {
                    setPresetKey('');
                    setZds(+e.target.value);
                  }}
                  className="w-full"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs font-semibold text-slate-600">
                  h_i (upstream depth) = {h_i.toFixed(2)} m
                </label>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.01}
                  value={h_i}
                  onChange={(e) => {
                    setPresetKey('');
                    setHi(+e.target.value);
                  }}
                  className="w-full"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs font-semibold text-slate-600">
                  h_ds (downstream depth) = {h_ds.toFixed(2)} m
                </label>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.01}
                  value={h_ds}
                  onChange={(e) => {
                    setPresetKey('');
                    setHds(+e.target.value);
                  }}
                  className="w-full"
                />
              </div>

              <div className="bg-slate-50 font-mono text-xs p-3 rounded border border-slate-200">
                n = {N} &nbsp;dist = {DIST} m &nbsp;θ = {THETA.toFixed(1)}
                <br />
                WSE_i = {result.wse_i.toFixed(3)} m
                <br />
                WSE_ds = {result.wse_ds.toFixed(3)} m
              </div>
            </div>

            {/* Diagram */}
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                Side view (to scale on elevation)
              </p>
              <CellDiagram result={result} />
            </div>
          </div>

          {/* h_higher vs naive readout */}
          <div className="mt-4 overflow-x-auto">
            <table className="border-collapse text-xs w-full">
              <thead>
                <tr className="bg-slate-100">
                  <th className="border border-slate-200 px-2 py-1 text-left font-semibold">
                    Quantity
                  </th>
                  <th className="border border-slate-200 px-2 py-1 text-right font-semibold">
                    Value
                  </th>
                  <th className="border border-slate-200 px-2 py-1 text-left font-semibold">
                    Meaning
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr className="hover:bg-slate-50">
                  <td className="border border-slate-200 px-2 py-1 font-mono text-red-700">
                    h_naive (= h_i)
                  </td>
                  <td className="border border-slate-200 px-2 py-1 text-right font-mono text-red-700">
                    {fmt(result.h_naive, 3)} m
                  </td>
                  <td className="border border-slate-200 px-2 py-1 text-slate-500">
                    What a scheme using only the upstream cell&apos;s own depth would compute
                  </td>
                </tr>
                <tr className="hover:bg-slate-50">
                  <td className="border border-slate-200 px-2 py-1 font-mono text-purple-700">
                    h_higher
                  </td>
                  <td className="border border-slate-200 px-2 py-1 text-right font-mono text-purple-700">
                    {fmt(result.h_higher, 3)} m
                  </td>
                  <td className="border border-slate-200 px-2 py-1 text-slate-500">
                    CASC2D / GSSHA: depth of water over whichever bed is higher
                  </td>
                </tr>
                <tr
                  className={diverges ? 'bg-amber-50' : 'hover:bg-slate-50'}
                >
                  <td className="border border-slate-200 px-2 py-1 font-semibold">
                    Divergence
                  </td>
                  <td
                    className={`border border-slate-200 px-2 py-1 text-right font-mono font-bold ${
                      diverges ? 'text-amber-700' : 'text-green-700'
                    }`}
                  >
                    {result.divergence >= 0 ? '+' : ''}
                    {result.divergence.toFixed(1)}%
                  </td>
                  <td className="border border-slate-200 px-2 py-1 text-slate-500">
                    {diverges
                      ? 'h_higher corrects for the higher downstream bed — h_naive would be wrong'
                      : 'h_higher reduces exactly to h_i in the ordinary downhill case'}
                  </td>
                </tr>
                <tr className="hover:bg-slate-50">
                  <td className="border border-slate-200 px-2 py-1 font-mono text-blue-700">
                    Q (using h_naive)
                  </td>
                  <td className="border border-slate-200 px-2 py-1 text-right font-mono text-blue-700">
                    {fmt(result.Q_naive, 5)} m³/s
                  </td>
                  <td className="border border-slate-200 px-2 py-1 text-slate-500">
                    Same S_eff, conveyance depth swapped to h_naive
                  </td>
                </tr>
                <tr className="hover:bg-slate-50">
                  <td className="border border-slate-200 px-2 py-1 font-mono text-indigo-700">
                    Q_diff (actual OPM)
                  </td>
                  <td className="border border-slate-200 px-2 py-1 text-right font-mono text-indigo-700">
                    {fmt(result.Q_diff, 5)} m³/s
                  </td>
                  <td className="border border-slate-200 px-2 py-1 text-slate-500">
                    Production formula: h_flow built from h_higher
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {presetKey === 'adverse' && diverges && (
            <div className="bg-amber-50 border border-amber-300 rounded-lg p-3 text-sm text-amber-900 mt-3">
              <span className="font-semibold">This is the saddle case: </span>
              WSE_i ({result.wse_i.toFixed(2)} m) is still above WSE_ds ({result.wse_ds.toFixed(2)}{' '}
              m), so water correctly drains forward (S_eff = {fmt(result.S_eff, 5)} &gt; 0). But the
              downstream bed (z_ds = {z_ds.toFixed(2)} m) sits {(z_ds - z_i).toFixed(2)} m{' '}
              <em>above</em> the upstream bed (z_i = {z_i.toFixed(2)} m) — a D8 saddle that can
              occur on a real DEM. h_naive would just report h_i = {fmt(result.h_naive, 3)} m,
              ignoring that higher lip entirely; h_higher correctly reports{' '}
              {fmt(result.h_higher, 3)} m — the depth of water actually standing over the higher of
              the two beds.
            </div>
          )}

          {presetKey === 'normal' && (
            <div className="bg-green-50 border border-green-300 rounded-lg p-3 text-sm text-green-900 mt-3">
              <span className="font-semibold">The ordinary case reduces exactly to kinematic: </span>
              Here z_i &gt; z_ds and WSE_i &gt; WSE_ds, so WSE_higher = z_i + h_i and z_higher = z_i,
              which makes h_higher = h_i exactly — identical to h_naive (divergence ={' '}
              {result.divergence.toFixed(1)}%). The GSSHA convention only changes the answer when
              the downstream bed or water surface is locally higher.
            </div>
          )}
        </div>

        {/* ───────── Part B: annotated source code ───────── */}
        <div>
          <h4 className="text-sm font-bold text-slate-700 uppercase tracking-wide mb-2">
            Part B — Historical Simplified Formula
          </h4>
          <p className="text-xs text-slate-500 mb-3">
            This older wide-sheet example omits current slope regularization, rectangular
            channels, and zero dry conveyance. See <code>MRRpy/core/routing/hydraulics.py</code>
            for the current kernel. Numbered comments explain this illustration only.
          </p>

          <pre className="bg-slate-50 font-mono text-xs p-3 rounded border border-slate-200 whitespace-pre overflow-x-auto">
{`def diffusive_wave_discharge(depth, dem, dist, slope_bnd, n, ds_safe, valid_ds,
                             theta, cell_size, xp, min_depth):
    depth_ds = depth[ds_safe]
    dem_ds   = dem[ds_safe]

    # ① water-surface slope = bed slope + theta * depth gradient
    S_w = slope_bnd + theta * (depth - depth_ds) / dist
    # ② outlet cells fall back to bed slope; clamp adverse gradient to 0
    S_eff = xp.where(valid_ds, S_w, slope_bnd)
    S_eff = xp.maximum(S_eff, 0.0)

    # ③ water-surface elevations (this cell and its downstream neighbour)
    wse      = dem + depth
    wse_ds   = wse[ds_safe]
    # ④ CASC2D / GSSHA conveyance depth = water over the higher bed
    h_higher = xp.maximum(wse, wse_ds) - xp.maximum(dem, dem_ds)
    # ⑤ blend own depth (kinematic) with h_higher (diffusive) by theta
    h_flow   = (1.0 - theta) * depth + theta * h_higher
    h_flow   = xp.where(valid_ds, h_flow, depth)
    h_flow   = xp.maximum(h_flow, min_depth)

    # ⑥ Manning-style discharge on (h_flow, S_eff)
    return (1.0 / n) * (h_flow ** (5.0 / 3.0)) * (S_eff ** 0.5) * cell_size`}
          </pre>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-700">
              <span className="font-mono font-bold text-indigo-700">① S_w</span> — the
              water-surface slope: the existing bed slope (<code>slope_bnd</code>, already floored
              at MIN_SLOPE with watershed-boundary handling) plus θ times the depth-gradient term{' '}
              <code>(h_i − h_ds)/dist</code>. At θ=0 this is pure bed slope (kinematic); at θ=1 it
              is the full water-surface slope.
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-700">
              <span className="font-mono font-bold text-indigo-700">② S_eff = max(S_w, 0)</span> —
              backwater / adverse-gradient protection. Cells with no valid downstream neighbour
              (the outlet, or any cell draining off-mask) keep <code>slope_bnd</code> instead — free
              outflow identical to the kinematic scheme.
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-700">
              <span className="font-mono font-bold text-indigo-700">③ wse / wse_ds</span> — stack
              depth on bed elevation for this cell and its downstream neighbour:{' '}
              <code>WSE = z + h</code>. Everything from here on follows the water surface, not the
              ground.
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-700">
              <span className="font-mono font-bold text-indigo-700">④ h_higher</span> — the GSSHA
              convention: depth above whichever bed is higher,{' '}
              <code>max(WSE_i, WSE_ds) − max(z_i, z_ds)</code>. In the normal downhill case this
              reduces exactly to h_i; at a saddle it correctly uses the depth over the raised
              downstream lip.
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-700">
              <span className="font-mono font-bold text-indigo-700">⑤ h_flow blend</span> — the
              same θ that blends the slope also blends the conveyance depth, so the two terms stay
              a coherent pair: θ=0 → own depth + bed slope (kinematic exactly); θ=1 → h_higher +
              water-surface slope (full diffusion wave). Outlet cells fall back to their own depth;
              a <code>min_depth</code> floor guards the wet/dry boundary.
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-700">
              <span className="font-mono font-bold text-indigo-700">⑥ Q_diff</span> — Manning&apos;s
              equation with the two replacements installed:{' '}
              <code>(1/n)·h_flow^(5/3)·S_eff^(1/2)·cell_size</code>. Not yet flux-limited — the
              caller applies the CFL limiter afterward.
            </div>
          </div>

          <div className="bg-sky-50 border border-sky-200 rounded-lg p-3 text-sm text-sky-900 mt-4">
            <span className="font-semibold">The CASC2D / GSSHA convention: </span>
            The CASC2D family of models (Julien et al., 1995; later GSSHA, and the LISFLOOD-FP
            diffusion wave) use the depth above whichever of the two beds is higher. When the bed
            goes downhill (z_i &gt; z_ds) and the water surface too (WSE_i &gt; WSE_ds): WSE_higher
            = z_i + h_i and z_higher = z_i, so h_higher = h_i — exactly the kinematic depth. The
            formula only differs when the downstream water surface is higher.
          </div>
        </div>

        {/* ───────── ds_safe callout ───────── */}
        <div className="bg-rose-50 border border-rose-300 rounded-lg p-4 text-sm text-rose-900">
          <p className="font-bold mb-1">A Small but Vital Coding Trick: ds_safe</p>
          <p className="mb-2">
            To compute S_w and h_higher, every cell must look up its downstream neighbour&apos;s
            depth and elevation: <code>h_ds = h[ds_idx]</code>, <code>z_ds = z[ds_idx]</code>. But
            the outlet (and any cell draining off the watershed edge) has{' '}
            <code>ds_idx = -1</code> — there is no downstream cell.
          </p>
          <p className="mb-2">
            <span className="font-semibold">Why −1 is dangerous: </span>
            in Python, <code>array[-1]</code> silently returns the <em>last</em> element — wrong,
            but not a crash. On a GPU, CuPy treats the index as unsigned, so −1 becomes a gigantic
            address: garbage or a crash. Either way the outlet would read nonsense.
          </p>
          <p className="mb-2">
            The fix, computed once before the time loop, is to replace every −1 with a harmless
            valid index (0), then <em>discard</em> the bogus result afterwards with a masked
            select:
          </p>
          <pre className="bg-white font-mono text-xs p-3 rounded border border-rose-200 whitespace-pre overflow-x-auto">
{`valid_ds = ds_idx >= 0                       # True for interior cells
ds_safe  = xp.where(valid_ds, ds_idx, 0)     # outlet's -1 -> 0 (any valid index)`}
          </pre>
          <p className="mt-2">
            <span className="font-semibold">&ldquo;Compute everywhere, mask the result.&rdquo; </span>
            This is the standard pattern for fast parallel code. Rather than branching (
            <code>if outlet: do one thing else: another</code>), which makes a GPU&apos;s threads
            diverge and stall, every cell runs the <em>same</em> instructions; the few cells whose
            result is meaningless (the outlet) simply have that result thrown away by{' '}
            <code>xp.where</code>. Outlet cells thus fall back to free outflow — the kinematic bed
            slope and their own depth — with no special case.
          </p>
        </div>

        {/* OPM connection box */}
        <div className="bg-sky-50 border border-sky-200 rounded-lg p-3 text-xs font-mono text-sky-800">
          In OPM routing_utils.py:
          <br />
          &nbsp;&nbsp;diffusive_wave_discharge(depth, dem, dist, slope_bnd, n, ds_safe, valid_ds,
          theta, cell_size, xp, min_depth)
          <br />
          &nbsp;&nbsp;DIFFUSION_THETA = 1.0&nbsp;&nbsp;(full diffusive in production — θ = 1 used
          throughout this widget)
        </div>
      </div>
    </div>
  );
}
