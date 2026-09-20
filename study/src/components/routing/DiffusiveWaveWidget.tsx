'use client';

import React, { useState, useMemo, useRef, useEffect } from 'react';

const BETA = 5 / 3;
const HYDROGRAPH = [2, 4, 7, 12, 10, 7, 5, 4, 3, 2, 2, 2];
const N_REACHES = 8;
const DX = 500;
const DT = 300;
const Q_BASE = 2;
const DEFAULT_B = 10;
const DEFAULT_N = 0.04;
const DEFAULT_S0 = 0.001;

function computeAlpha(S0: number, manN: number, B: number) {
  return Math.sqrt(S0) / (manN * Math.pow(B, 2 / 3));
}
function aToQ(A: number, alpha: number): number {
  return alpha * Math.pow(Math.max(A, 0.001), BETA);
}
function qToA(Q: number, alpha: number): number {
  return Math.pow(Math.max(Q, 0.001) / alpha, 1 / BETA);
}
function aToH(A: number, B: number): number {
  return A / B;
}

function diffusiveQ(
  A: number[],
  S0: number,
  B: number,
  manN: number,
  theta_diff: number
): number[] {
  return A.map((a, i) => {
    const h_i = aToH(a, B);
    const h_ds = i < A.length - 1 ? aToH(A[i + 1], B) : 0;
    const S_eff = Math.max(S0 + theta_diff * (h_i - h_ds) / DX, 1e-8);
    const alpha_eff = Math.sqrt(S_eff) / (manN * Math.pow(B, 2 / 3));
    return alpha_eff * Math.pow(Math.max(a, 0.001), BETA);
  });
}

function runScheme(theta_diff: number, S0: number): number[][] {
  const alpha = computeAlpha(S0, DEFAULT_N, DEFAULT_B);
  let A = Array(N_REACHES).fill(qToA(Q_BASE, alpha));
  const out: number[][] = [];
  for (let t = 0; t < HYDROGRAPH.length; t++) {
    const Q = diffusiveQ(A, S0, DEFAULT_B, DEFAULT_N, theta_diff);
    out.push([...Q]);
    const Qup = [HYDROGRAPH[t], ...Q.slice(0, -1)];
    A = A.map((a, i) => Math.max(a - (DT / DX) * (Q[i] - Qup[i]), 0.001));
  }
  return out;
}

function analyzeRun(Q: number[][]): { peakQ: number; peakT: number; mass: number } {
  const outlet = Q.map((row) => row[N_REACHES - 1]);
  const peakQ = Math.max(...outlet);
  const peakT = outlet.indexOf(peakQ);
  const mass = outlet.reduce((s, q) => s + q * DT, 0);
  return { peakQ, peakT, mass };
}

const svgW = 300;
const svgH = 160;
const PAD = { l: 35, r: 10, t: 10, b: 25 };

function xScale(t: number): number {
  return PAD.l + (t / (HYDROGRAPH.length - 1)) * (svgW - PAD.l - PAD.r);
}
function yScale(Q: number): number {
  return svgH - PAD.b - (Q / 14) * (svgH - PAD.t - PAD.b);
}
function makePath(Qs: number[]): string {
  return Qs
    .map((q, t) => `${t === 0 ? 'M' : 'L'}${xScale(t).toFixed(1)},${yScale(q).toFixed(1)}`)
    .join(' ');
}

export default function DiffusiveWaveWidget() {
  const [thetaDiff, setThetaDiff] = useState(0);
  const [flatSlope, setFlatSlope] = useState(false);
  const [stepIdx, setStepIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(500);

  const S0_use = flatSlope ? 0.00005 : DEFAULT_S0;
  const Q_kin = useMemo(() => runScheme(0, S0_use), [S0_use]);
  const Q_part = useMemo(() => runScheme(thetaDiff, S0_use), [thetaDiff, S0_use]);
  const Q_diff = useMemo(() => runScheme(1, S0_use), [S0_use]);
  const stats_kin = useMemo(() => analyzeRun(Q_kin), [Q_kin]);
  const stats_part = useMemo(() => analyzeRun(Q_part), [Q_part]);
  const stats_diff = useMemo(() => analyzeRun(Q_diff), [Q_diff]);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!playing) return;
    if (stepIdx >= HYDROGRAPH.length - 1) {
      setPlaying(false);
      return;
    }
    timerRef.current = setTimeout(() => setStepIdx((i) => i + 1), speed);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [playing, stepIdx, speed]);

  function handlePlay() {
    if (stepIdx >= HYDROGRAPH.length - 1) {
      setStepIdx(0);
    }
    setPlaying(true);
  }
  function handlePause() {
    setPlaying(false);
  }
  function handleStep() {
    setPlaying(false);
    setStepIdx((i) => Math.min(i + 1, HYDROGRAPH.length - 1));
  }
  function handleReset() {
    setPlaying(false);
    setStepIdx(0);
  }

  const peakQin = Math.max(...HYDROGRAPH);
  const attenPart =
    stats_kin.peakQ > 0
      ? ((stats_kin.peakQ - stats_part.peakQ) / stats_kin.peakQ) * 100
      : 0;
  const attenDiff =
    stats_kin.peakQ > 0
      ? ((stats_kin.peakQ - stats_diff.peakQ) / stats_kin.peakQ) * 100
      : 0;

  const massesClose =
    Math.abs(stats_kin.mass - stats_diff.mass) / stats_kin.mass < 0.05 &&
    Math.abs(stats_kin.mass - stats_part.mass) / stats_kin.mass < 0.05;

  const outletKin = Q_kin.map((row) => row[N_REACHES - 1]);
  const outletPart = Q_part.map((row) => row[N_REACHES - 1]);
  const outletDiff = Q_diff.map((row) => row[N_REACHES - 1]);

  const gridYs = [0, 2, 4, 6, 8, 10, 12, 14];
  const gridXs = [0, 2, 4, 6, 8, 10, 11];

  return (
    <div className="not-prose my-8 rounded-2xl border border-slate-200 bg-white shadow-xl overflow-hidden font-sans">
      <div className="bg-gradient-to-r from-sky-700 to-blue-900 px-6 py-4">
        <h3 className="text-white font-bold text-lg tracking-tight">
          Kinematic vs. Diffusive Wave
        </h3>
        <p className="text-sky-200 text-sm mt-0.5">
          Historical fixed-step illustration; not a production stability benchmark
        </p>
      </div>

      <div className="p-6 flex flex-col lg:flex-row gap-8 items-start">
        {/* LEFT: reach animation */}
        <div className="w-full lg:w-72 shrink-0 flex flex-col gap-4">
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
              8-Reach Channel — t = {stepIdx} / {HYDROGRAPH.length - 1}
            </p>
            <div className="space-y-1">
              {Array(N_REACHES)
                .fill(0)
                .map((_, i) => {
                  const qK = Q_kin[stepIdx]?.[i] ?? Q_BASE;
                  const qP = Q_part[stepIdx]?.[i] ?? Q_BASE;
                  const qD = Q_diff[stepIdx]?.[i] ?? Q_BASE;
                  const Qmax = 14;
                  return (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-xs text-slate-400 w-8 text-right font-mono">
                        i={i}
                      </span>
                      <div className="flex flex-col gap-0.5 flex-1">
                        {(
                          [
                            [qK, '#2563eb'],
                            [qP, '#f59e0b'],
                            [qD, '#dc2626'],
                          ] as [number, string][]
                        ).map(([q, col], k) => (
                          <div
                            key={k}
                            className="h-3 rounded"
                            style={{
                              width: `${Math.max(4, (q / Qmax) * 200)}px`,
                              background: col,
                              transition: 'width 0.2s',
                            }}
                          />
                        ))}
                      </div>
                      <span className="text-[10px] font-mono text-slate-500 w-12">
                        {(Q_kin[stepIdx]?.[i] ?? 0).toFixed(1)}
                      </span>
                    </div>
                  );
                })}
              <div className="flex gap-4 text-xs mt-2 flex-wrap">
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded bg-blue-600 inline-block" />
                  Kinematic
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded bg-amber-500 inline-block" />
                  θ={thetaDiff.toFixed(1)}
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded bg-red-600 inline-block" />
                  Diffusive
                </span>
              </div>
            </div>
          </div>

          {/* Play controls */}
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={playing ? handlePause : handlePlay}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-sky-600 text-white hover:bg-sky-700 transition-colors"
            >
              {playing ? 'Pause' : stepIdx >= HYDROGRAPH.length - 1 ? 'Restart' : 'Play'}
            </button>
            <button
              onClick={handleStep}
              disabled={stepIdx >= HYDROGRAPH.length - 1}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 disabled:opacity-40 transition-colors"
            >
              Step →
            </button>
            <button
              onClick={handleReset}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
            >
              Reset
            </button>
          </div>

          {/* Speed control */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-semibold text-slate-600">
              Speed: {speed} ms / step
            </label>
            <input
              type="range"
              min={100}
              max={1000}
              step={100}
              value={speed}
              onChange={(e) => setSpeed(+e.target.value)}
              className="w-full"
            />
            <div className="text-xs text-slate-400 flex justify-between">
              <span>Fast</span>
              <span>Slow</span>
            </div>
          </div>

          {/* θ_diff slider */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-semibold text-slate-600">
              θ_diff = {thetaDiff.toFixed(2)}
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={thetaDiff}
              onChange={(e) => setThetaDiff(+e.target.value)}
              className="w-full"
            />
            <div className="text-xs text-slate-400 flex justify-between">
              <span>0 = kinematic</span>
              <span>0.5 = blend</span>
              <span>1 = diffusive</span>
            </div>
          </div>

          {/* Flat slope toggle */}
          <div>
            <label className="flex items-center gap-2 text-sm cursor-pointer mt-2">
              <input
                type="checkbox"
                checked={flatSlope}
                onChange={(e) => setFlatSlope(e.target.checked)}
              />
              Try flat slope (S₀ = 0.00005)
            </label>
            {flatSlope && (
              <div className="bg-red-50 border border-red-200 rounded p-2 text-xs text-red-800 mt-1">
                ⚠ Kinematic wave breaks down on flat slopes. Diffusive wave handles it.
              </div>
            )}
          </div>

          {/* Input hydrograph reminder */}
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs text-slate-600">
            <span className="font-semibold">Input hydrograph:</span>{' '}
            peak = {peakQin} m³/s at t = {HYDROGRAPH.indexOf(peakQin)}
          </div>
        </div>

        {/* RIGHT: hydrograph + stats */}
        <div className="flex-1 flex flex-col gap-4 min-w-0">
          {/* SVG outlet hydrograph */}
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
              Outlet Hydrograph (reach i = 7)
            </p>
            <svg
              width={svgW}
              height={svgH}
              className="block overflow-visible"
              style={{ maxWidth: '100%' }}
            >
              {/* Grid lines */}
              {gridYs.map((q) => (
                <line
                  key={`gy-${q}`}
                  x1={PAD.l}
                  y1={yScale(q)}
                  x2={svgW - PAD.r}
                  y2={yScale(q)}
                  stroke="#e2e8f0"
                  strokeWidth={1}
                />
              ))}
              {gridXs.map((t) => (
                <line
                  key={`gx-${t}`}
                  x1={xScale(t)}
                  y1={PAD.t}
                  x2={xScale(t)}
                  y2={svgH - PAD.b}
                  stroke="#e2e8f0"
                  strokeWidth={1}
                />
              ))}

              {/* Axes */}
              <line
                x1={PAD.l}
                y1={PAD.t}
                x2={PAD.l}
                y2={svgH - PAD.b}
                stroke="#94a3b8"
                strokeWidth={1.5}
              />
              <line
                x1={PAD.l}
                y1={svgH - PAD.b}
                x2={svgW - PAD.r}
                y2={svgH - PAD.b}
                stroke="#94a3b8"
                strokeWidth={1.5}
              />

              {/* Y-axis labels */}
              {[0, 4, 8, 12].map((q) => (
                <text
                  key={`yl-${q}`}
                  x={PAD.l - 4}
                  y={yScale(q) + 4}
                  textAnchor="end"
                  fontSize={9}
                  fill="#64748b"
                >
                  {q}
                </text>
              ))}

              {/* X-axis labels */}
              {[0, 3, 6, 9, 11].map((t) => (
                <text
                  key={`xl-${t}`}
                  x={xScale(t)}
                  y={svgH - PAD.b + 12}
                  textAnchor="middle"
                  fontSize={9}
                  fill="#64748b"
                >
                  {t}
                </text>
              ))}

              {/* Axis unit labels */}
              <text
                x={PAD.l - 28}
                y={svgH / 2}
                fontSize={9}
                fill="#94a3b8"
                transform={`rotate(-90, ${PAD.l - 28}, ${svgH / 2})`}
                textAnchor="middle"
              >
                Q (m³/s)
              </text>
              <text
                x={(PAD.l + svgW - PAD.r) / 2}
                y={svgH - 2}
                fontSize={9}
                fill="#94a3b8"
                textAnchor="middle"
              >
                time step
              </text>

              {/* Peak dashed verticals */}
              <line
                x1={xScale(stats_kin.peakT)}
                y1={PAD.t}
                x2={xScale(stats_kin.peakT)}
                y2={svgH - PAD.b}
                stroke="#2563eb"
                strokeWidth={1}
                strokeDasharray="3,3"
                opacity={0.5}
              />
              <line
                x1={xScale(stats_part.peakT)}
                y1={PAD.t}
                x2={xScale(stats_part.peakT)}
                y2={svgH - PAD.b}
                stroke="#f59e0b"
                strokeWidth={1}
                strokeDasharray="3,3"
                opacity={0.5}
              />
              <line
                x1={xScale(stats_diff.peakT)}
                y1={PAD.t}
                x2={xScale(stats_diff.peakT)}
                y2={svgH - PAD.b}
                stroke="#dc2626"
                strokeWidth={1}
                strokeDasharray="3,3"
                opacity={0.5}
              />

              {/* Hydrograph curves */}
              <path
                d={makePath(outletDiff)}
                fill="none"
                stroke="#dc2626"
                strokeWidth={2}
              />
              <path
                d={makePath(outletPart)}
                fill="none"
                stroke="#f59e0b"
                strokeWidth={2}
                strokeDasharray="5,3"
              />
              <path
                d={makePath(outletKin)}
                fill="none"
                stroke="#2563eb"
                strokeWidth={2}
              />

              {/* Peak dots + labels */}
              <circle
                cx={xScale(stats_kin.peakT)}
                cy={yScale(stats_kin.peakQ)}
                r={4}
                fill="#2563eb"
              />
              <text
                x={xScale(stats_kin.peakT) + 5}
                y={yScale(stats_kin.peakQ) - 4}
                fontSize={8}
                fill="#2563eb"
              >
                {stats_kin.peakQ.toFixed(1)}
              </text>

              <circle
                cx={xScale(stats_part.peakT)}
                cy={yScale(stats_part.peakQ)}
                r={4}
                fill="#f59e0b"
              />
              <text
                x={xScale(stats_part.peakT) + 5}
                y={yScale(stats_part.peakQ) - 4}
                fontSize={8}
                fill="#f59e0b"
              >
                {stats_part.peakQ.toFixed(1)}
              </text>

              <circle
                cx={xScale(stats_diff.peakT)}
                cy={yScale(stats_diff.peakQ)}
                r={4}
                fill="#dc2626"
              />
              <text
                x={xScale(stats_diff.peakT) + 5}
                y={yScale(stats_diff.peakQ) - 4}
                fontSize={8}
                fill="#dc2626"
              >
                {stats_diff.peakQ.toFixed(1)}
              </text>

              {/* Current step vertical */}
              <line
                x1={xScale(stepIdx)}
                y1={PAD.t}
                x2={xScale(stepIdx)}
                y2={svgH - PAD.b}
                stroke="#f97316"
                strokeWidth={1.5}
              />
              <text
                x={xScale(stepIdx) + 3}
                y={PAD.t + 10}
                fontSize={8}
                fill="#f97316"
              >
                t={stepIdx}
              </text>

              {/* Legend */}
              <rect
                x={svgW - PAD.r - 80}
                y={PAD.t}
                width={72}
                height={44}
                rx={4}
                fill="white"
                stroke="#e2e8f0"
                strokeWidth={1}
              />
              <line
                x1={svgW - PAD.r - 76}
                y1={PAD.t + 10}
                x2={svgW - PAD.r - 62}
                y2={PAD.t + 10}
                stroke="#2563eb"
                strokeWidth={2}
              />
              <text x={svgW - PAD.r - 59} y={PAD.t + 13} fontSize={8} fill="#2563eb">
                Kinematic
              </text>
              <line
                x1={svgW - PAD.r - 76}
                y1={PAD.t + 24}
                x2={svgW - PAD.r - 62}
                y2={PAD.t + 24}
                stroke="#f59e0b"
                strokeWidth={2}
                strokeDasharray="4,2"
              />
              <text x={svgW - PAD.r - 59} y={PAD.t + 27} fontSize={8} fill="#f59e0b">
                θ={thetaDiff.toFixed(1)}
              </text>
              <line
                x1={svgW - PAD.r - 76}
                y1={PAD.t + 38}
                x2={svgW - PAD.r - 62}
                y2={PAD.t + 38}
                stroke="#dc2626"
                strokeWidth={2}
              />
              <text x={svgW - PAD.r - 59} y={PAD.t + 41} fontSize={8} fill="#dc2626">
                Diffusive
              </text>
            </svg>
          </div>

          {/* Stats table */}
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
              Outlet Statistics
            </p>
            <div className="overflow-x-auto">
              <table className="text-xs border-collapse w-full">
                <thead>
                  <tr className="bg-slate-100">
                    <th className="border border-slate-200 px-2 py-1 text-left font-semibold">
                      Scheme
                    </th>
                    <th className="border border-slate-200 px-2 py-1 text-right font-semibold">
                      Peak Q (m³/s)
                    </th>
                    <th className="border border-slate-200 px-2 py-1 text-right font-semibold">
                      Peak at t=
                    </th>
                    <th className="border border-slate-200 px-2 py-1 text-right font-semibold">
                      Attenuation
                    </th>
                    <th
                      className={`border border-slate-200 px-2 py-1 text-right font-semibold ${
                        massesClose ? 'text-green-700' : ''
                      }`}
                    >
                      Mass (m³) {massesClose ? '✓' : ''}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="hover:bg-slate-50">
                    <td className="border border-slate-200 px-2 py-1 font-mono text-blue-700">
                      Kinematic
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-right font-mono">
                      {stats_kin.peakQ.toFixed(1)}
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-right font-mono">
                      {stats_kin.peakT}
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-right font-mono text-slate-400">
                      0%
                    </td>
                    <td
                      className={`border border-slate-200 px-2 py-1 text-right font-mono ${
                        massesClose ? 'text-green-700' : ''
                      }`}
                    >
                      {stats_kin.mass.toFixed(0)}
                    </td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="border border-slate-200 px-2 py-1 font-mono text-amber-600">
                      θ={thetaDiff.toFixed(2)}
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-right font-mono">
                      {stats_part.peakQ.toFixed(1)}
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-right font-mono">
                      {stats_part.peakT}
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-right font-mono text-amber-600">
                      {attenPart.toFixed(1)}%
                    </td>
                    <td
                      className={`border border-slate-200 px-2 py-1 text-right font-mono ${
                        massesClose ? 'text-green-700' : ''
                      }`}
                    >
                      {stats_part.mass.toFixed(0)}
                    </td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="border border-slate-200 px-2 py-1 font-mono text-red-700">
                      Diffusive
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-right font-mono">
                      {stats_diff.peakQ.toFixed(1)}
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-right font-mono">
                      {stats_diff.peakT}
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-right font-mono text-red-600">
                      {attenDiff.toFixed(1)}%
                    </td>
                    <td
                      className={`border border-slate-200 px-2 py-1 text-right font-mono ${
                        massesClose ? 'text-green-700' : ''
                      }`}
                    >
                      {stats_diff.mass.toFixed(0)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Limitations table */}
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">
              Routing Scheme Limitations
            </p>
            <div className="overflow-x-auto">
              <table className="text-xs border-collapse w-full mt-1">
                <thead>
                  <tr className="bg-slate-100">
                    <th className="border border-slate-200 px-2 py-1 text-left font-semibold">
                      Limitation
                    </th>
                    <th className="border border-slate-200 px-2 py-1 text-center font-semibold text-blue-700">
                      Kinematic
                    </th>
                    <th className="border border-slate-200 px-2 py-1 text-center font-semibold text-red-700">
                      Diffusive
                    </th>
                    <th className="border border-slate-200 px-2 py-1 text-center font-semibold text-green-700">
                      Dynamic
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="hover:bg-slate-50">
                    <td className="border border-slate-200 px-2 py-1">
                      No backwater effects
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center text-red-600">
                      ✗ blind
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center text-amber-600">
                      partial
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center text-green-600">
                      ✓
                    </td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="border border-slate-200 px-2 py-1">
                      Hydrograph attenuation
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center text-red-600">
                      ✗ zero
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center text-green-600">
                      ✓ some
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center text-green-600">
                      ✓ full
                    </td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="border border-slate-200 px-2 py-1">
                      Flat reaches (S→0)
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center text-red-600">
                      ✗ fails
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center text-amber-600">
                      ~ marginal
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center text-green-600">
                      ✓
                    </td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="border border-slate-200 px-2 py-1">
                      Computational cost
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center font-mono">
                      O(N)
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center font-mono">
                      O(N)
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center font-mono">
                      O(N log N)
                    </td>
                  </tr>
                  <tr className="hover:bg-slate-50">
                    <td className="border border-slate-200 px-2 py-1">Valid when</td>
                    <td className="border border-slate-200 px-2 py-1 text-center font-mono">
                      S₀ &gt; 0.001
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center font-mono">
                      S₀ &gt; 0.0001
                    </td>
                    <td className="border border-slate-200 px-2 py-1 text-center font-mono">
                      always
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* OPM connection box */}
          <div className="bg-sky-50 border border-sky-200 rounded-lg p-3 text-xs font-mono text-sky-800 mt-1">
            In OPM config.py:
            <br />
            &nbsp;&nbsp;ROUTING_SCHEME = &apos;kinematic&apos;&nbsp;&nbsp;→&nbsp;&nbsp;θ_diff = 0
            <br />
            &nbsp;&nbsp;ROUTING_SCHEME = &apos;diffusive&apos;&nbsp;&nbsp;→&nbsp;&nbsp;uses DIFFUSION_THETA
            <br />
            &nbsp;&nbsp;DIFFUSION_THETA = 1.0&nbsp;&nbsp;(full diffusion by default)
          </div>
        </div>
      </div>
    </div>
  );
}
