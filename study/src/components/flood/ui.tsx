'use client';

// Shared building blocks for the flood-map chapters (7–9): the widget frame,
// sliders, the "what you are looking at" strip, legends, colour scales and a
// canvas raster painter. Keeps every flood widget looking and reading alike.

import React, { useEffect, useRef } from 'react';

// ── colours ──────────────────────────────────────────────────────────────────
export const C = {
  ink: '#1F2430',
  soft: '#5A6270',
  river: '#14427A', // river cells (dark navy, as "stream channel" in Ch 1)
  water: '#2B6CB0',
  waterLight: '#9CC3E6',
  ground: '#8B6B4A',
  groundFill: '#E4D7B8',
  raised: '#fdba74', // raised by filling (orange, as in Ch 1's pit fill)
  current: '#fbbf24', // currently processing (amber)
  downstream: '#a78bfa', // flow-to (purple)
  bad: '#C0392B',
  good: '#2E8B57',
};

const DEPTH_STOPS: [number, [number, number, number]][] = [
  [0, [220, 235, 247]],
  [0.33, [127, 179, 221]],
  [0.66, [43, 108, 176]],
  [1, [11, 47, 92]],
];

/** Flood depth → RGB (light blue = shallow, navy = deep), dMax at the dark end. */
export function depthRGB(d: number, dMax = 5): [number, number, number] {
  const t = Math.min(Math.max(d / dMax, 0), 1);
  for (let k = 1; k < DEPTH_STOPS.length; k++) {
    const [t1, c1] = DEPTH_STOPS[k];
    if (t <= t1) {
      const [t0, c0] = DEPTH_STOPS[k - 1];
      const f = (t - t0) / (t1 - t0);
      return [0, 1, 2].map((j) => Math.round(c0[j] + f * (c1[j] - c0[j]))) as [number, number, number];
    }
  }
  return DEPTH_STOPS[DEPTH_STOPS.length - 1][1];
}
export const depthCss = (d: number, dMax = 5) => `rgb(${depthRGB(d, dMax).join(',')})`;

/** A colour-blind-friendly qualitative palette (Okabe–Ito + Tol muted). */
export const QUAL = [
  '#E69F00', '#56B4E9', '#009E73', '#F0E442', '#0072B2', '#D55E00', '#CC79A7', '#999933',
  '#88CCEE', '#44AA99', '#117733', '#DDCC77', '#CC6677', '#AA4499', '#882255', '#332288',
];
export function qualRGB(k: number): [number, number, number] {
  const h = QUAL[((k % QUAL.length) + QUAL.length) % QUAL.length];
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}

/** Hillshade 0..1 (NW sun), for a grey relief under maps. */
export function hillshade(z: ArrayLike<number>, ny: number, nx: number, dx: number, exag = 1): Float32Array {
  const out = new Float32Array(ny * nx);
  const az = (315 * Math.PI) / 180, alt = (45 * Math.PI) / 180;
  for (let r = 0; r < ny; r++) for (let c = 0; c < nx; c++) {
    const zc = (rr: number, cc: number) => z[Math.min(Math.max(rr, 0), ny - 1) * nx + Math.min(Math.max(cc, 0), nx - 1)];
    const gx = ((zc(r, c + 1) - zc(r, c - 1)) / (2 * dx)) * exag;
    const gy = ((zc(r + 1, c) - zc(r - 1, c)) / (2 * dx)) * exag;
    const slope = Math.PI / 2 - Math.atan(Math.hypot(gx, gy));
    const aspect = Math.atan2(-gx, gy);
    const hs = Math.sin(alt) * Math.sin(slope) + Math.cos(alt) * Math.cos(slope) * Math.cos(az - aspect);
    out[r * nx + c] = Math.min(Math.max(hs, 0), 1);
  }
  return out;
}

// ── canvas raster ────────────────────────────────────────────────────────────
/**
 * A crisp pixel map: `paint(i)` returns the RGB(A) of cell i (row-major).
 * Draws once per change of `deps`; `overlay` draws on top in cell units.
 */
export function RasterCanvas({
  ny, nx, paint, deps, scale = 3, overlay, onCell, onHover, className, ariaLabel,
}: {
  ny: number; nx: number;
  paint: (i: number) => [number, number, number] | [number, number, number, number];
  deps: unknown[];
  scale?: number;
  overlay?: (ctx: CanvasRenderingContext2D, s: number) => void;
  onCell?: (r: number, c: number, e: React.MouseEvent) => void;
  onHover?: (r: number, c: number) => void;
  className?: string;
  ariaLabel: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const off = document.createElement('canvas');
    off.width = nx; off.height = ny;
    const octx = off.getContext('2d')!;
    const img = octx.createImageData(nx, ny);
    for (let i = 0; i < ny * nx; i++) {
      const p = paint(i);
      img.data[4 * i] = p[0]; img.data[4 * i + 1] = p[1]; img.data[4 * i + 2] = p[2];
      img.data[4 * i + 3] = p.length > 3 ? (p as number[])[3] : 255;
    }
    octx.putImageData(img, 0, 0);
    const ctx = cv.getContext('2d')!;
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.drawImage(off, 0, 0, nx * scale, ny * scale);
    if (overlay) { ctx.save(); overlay(ctx, scale); ctx.restore(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  const cell = (e: React.MouseEvent) => {
    const rect = (e.target as HTMLCanvasElement).getBoundingClientRect();
    const c = Math.floor(((e.clientX - rect.left) / rect.width) * nx);
    const r = Math.floor(((e.clientY - rect.top) / rect.height) * ny);
    return [Math.min(Math.max(r, 0), ny - 1), Math.min(Math.max(c, 0), nx - 1)] as const;
  };
  return (
    <canvas
      ref={ref}
      width={nx * scale}
      height={ny * scale}
      role="img"
      aria-label={ariaLabel}
      className={className}
      style={{ width: '100%', height: 'auto', imageRendering: 'pixelated', cursor: onCell ? 'crosshair' : undefined }}
      onClick={onCell ? (e) => { const [r, c] = cell(e); onCell(r, c, e); } : undefined}
      onContextMenu={onCell ? (e) => { e.preventDefault(); const [r, c] = cell(e); onCell(r, c, e); } : undefined}
      onMouseMove={onHover ? (e) => { const [r, c] = cell(e); onHover(r, c); } : undefined}
    />
  );
}

// ── frame, controls, explanation ─────────────────────────────────────────────
export function WidgetFrame({ title, idea, children, tone = 'water' }: {
  title: string; idea: React.ReactNode; children: React.ReactNode; tone?: 'water' | 'earth' | 'slate';
}) {
  const grad = tone === 'earth' ? 'from-amber-700 to-stone-800' : tone === 'slate' ? 'from-slate-700 to-slate-900' : 'from-sky-700 to-blue-900';
  return (
    <figure className="not-prose my-8 rounded-2xl border border-slate-200 bg-white shadow-xl overflow-hidden font-sans">
      <figcaption className={`bg-gradient-to-r ${grad} px-6 py-4`}>
        <h3 className="text-white font-bold text-lg tracking-tight">{title}</h3>
        <p className="text-sky-100 text-sm mt-0.5 leading-snug">{idea}</p>
      </figcaption>
      <div className="p-5">{children}</div>
    </figure>
  );
}

let sliderId = 0;
export function Slider({ label, value, min, max, step, display, onChange, hint }: {
  label: string; value: number; min: number; max: number; step: number;
  display: string; onChange: (v: number) => void; hint?: string;
}) {
  const id = useRef(`fs-${++sliderId}`).current;
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center justify-between gap-3">
        <label htmlFor={id} className="text-xs font-semibold text-slate-600">{label}</label>
        <span className="text-xs font-mono text-slate-800 tabular-nums">{display}</span>
      </div>
      <input id={id} type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 rounded-full cursor-pointer accent-sky-600" />
      {hint && <span className="text-[11px] text-slate-500 leading-tight">{hint}</span>}
    </div>
  );
}

export function Toggle<T extends string>({ options, value, onChange, label }: {
  options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-slate-300 overflow-hidden text-xs font-semibold">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={`px-3 py-1.5 transition-colors ${value === o.value ? 'bg-sky-700 text-white' : 'bg-white text-slate-600 hover:bg-sky-50'}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** "Look for" strip: numbered things to notice, in plain words. */
export function LookFor({ items }: { items: React.ReactNode[] }) {
  return (
    <ol className="mt-4 grid gap-2 sm:grid-cols-3 text-[13px] text-slate-700">
      {items.map((it, k) => (
        <li key={k} className="flex gap-2 rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 leading-snug">
          <span className="flex-shrink-0 w-5 h-5 rounded-full bg-sky-700 text-white text-[11px] font-bold flex items-center justify-center">{k + 1}</span>
          <span>{it}</span>
        </li>
      ))}
    </ol>
  );
}

export function Legend({ items }: { items: { swatch: React.ReactNode | string; label: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-slate-600">
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-1.5">
          {typeof it.swatch === 'string'
            ? <span className="inline-block w-3.5 h-3.5 rounded-sm border border-slate-300" style={{ background: it.swatch }} />
            : it.swatch}
          {it.label}
        </span>
      ))}
    </div>
  );
}

export function DepthBar({ dMax = 5 }: { dMax?: number }) {
  const stops = DEPTH_STOPS.map(([t, c]) => `rgb(${c.join(',')}) ${t * 100}%`).join(',');
  return (
    <div className="flex items-center gap-2 text-[11px] text-slate-600">
      <span>water depth</span>
      <span className="inline-block h-2.5 w-28 rounded" style={{ background: `linear-gradient(90deg, ${stops})` }} />
      <span className="font-mono">0 → {dMax} m</span>
    </div>
  );
}

export function Stat({ label, value, tone = 'slate' }: { label: string; value: React.ReactNode; tone?: 'slate' | 'sky' | 'red' | 'green' }) {
  const t = { slate: 'text-slate-900', sky: 'text-sky-800', red: 'text-red-700', green: 'text-emerald-700' }[tone];
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-slate-500 font-semibold">{label}</div>
      <div className={`text-lg font-bold tabular-nums ${t}`}>{value}</div>
    </div>
  );
}

export function Loading({ what = 'the valley' }: { what?: string }) {
  return <div className="py-16 text-center text-sm text-slate-500">Loading {what}…</div>;
}

/** Shown instead of a crash if a computation produces NaN/Infinity. */
export function Unstable({ msg }: { msg: string }) {
  return (
    <div role="alert" className="rounded-lg border-2 border-red-500 bg-red-50 px-4 py-3 text-sm text-red-800 font-semibold">
      Model Unstable — {msg}
    </div>
  );
}
