'use client';

// Shared pieces for the D8-tree interlude: the preset DEMs, a map view of the
// grid (with D8 arrows) and a drawing of the same cells as a tree. Every class
// of cell is told apart by shape *and* a text label, never by colour alone.

import React from 'react';
import presetsJson from '@/data/ch3b/presets.json';
import { treeLayout, childrenOf, D8_NAME, type TreeModel } from '@/lib/tree/tree';
import { C } from '../flood/ui';

export type Preset = { label: string; ny: number; nx: number; z: number[] };
export const PRESETS = presetsJson as Record<string, Preset>;
export const MAIN_PRESETS = ['valley', 'tributaries', 'flat', 'ridge'] as const;

export const T = {
  ...C,
  edge: '#7c3aed',       // flow-to arrows (purple family, as "downstream" in Ch 1)
  edgeSoft: '#a78bfa',
  path: '#0284c7',       // path to the outlet (sky, as the raindrop in Ch 1)
  subtree: '#bae6fd',
  inactive: '#e2e8f0',
  backward: '#C0392B',
};

/** A letter per grid cell (A, B, … Z, a, b, …), fixed while the terrain is edited. */
export const cellName = (flat: number) =>
  flat < 26 ? String.fromCharCode(65 + flat) : flat < 52 ? String.fromCharCode(71 + flat) : `#${flat}`;

// elevation colours shared with the Ch 1 widgets (blue low → snow high)
const STOPS: [number, [number, number, number]][] = [
  [0.0, [67, 117, 180]], [0.18, [116, 196, 163]], [0.4, [161, 218, 115]],
  [0.62, [255, 230, 130]], [0.82, [200, 130, 70]], [1.0, [245, 245, 244]],
];
export function elevRGB(z: number, lo: number, hi: number): [number, number, number] {
  const t = hi === lo ? 0.5 : (z - lo) / (hi - lo);
  for (let k = 1; k < STOPS.length; k++) {
    if (t <= STOPS[k][0]) {
      const [t0, c0] = STOPS[k - 1], [t1, c1] = STOPS[k];
      const f = (t - t0) / (t1 - t0 || 1);
      return [0, 1, 2].map((j) => c0[j] + f * (c1[j] - c0[j])) as [number, number, number];
    }
  }
  return STOPS[STOPS.length - 1][1];
}
export const elevCss = (z: number, lo: number, hi: number) =>
  `rgb(${elevRGB(z, lo, hi).map(Math.round).join(',')})`;

export type Role = 'root' | 'leaf' | 'chain' | 'confluence';
export function roles(m: TreeModel): Role[] {
  const kids = childrenOf(m.dsIdx);
  return m.dsIdx.map((d, i) => (d < 0 ? 'root' : kids[i].length === 0 ? 'leaf' : kids[i].length >= 2 ? 'confluence' : 'chain'));
}
export const ROLE_TEXT: Record<Role, string> = {
  root: 'root (outlet: water leaves here)',
  leaf: 'leaf (headwater: nothing flows in)',
  chain: 'chain (one cell flows in)',
  confluence: 'confluence (two or more flow in)',
};

/** The node symbol: circle = leaf/chain, diamond = confluence, square = root. */
export function NodeShape({ role, x, y, r, fill, stroke, strokeWidth = 1.5, dashed }: {
  role: Role; x: number; y: number; r: number; fill: string; stroke: string; strokeWidth?: number; dashed?: boolean;
}) {
  const common = { fill, stroke, strokeWidth, strokeDasharray: dashed ? '3 2' : undefined };
  if (role === 'root') return <rect x={x - r} y={y - r} width={2 * r} height={2 * r} rx={2} {...common} />;
  if (role === 'confluence') {
    const q = r * 1.25;
    return <polygon points={`${x},${y - q} ${x + q},${y} ${x},${y + q} ${x - q},${y}`} {...common} />;
  }
  return <circle cx={x} cy={y} r={r} {...common} />;
}

export function RoleLegend() {
  const items: [Role, string][] = [['leaf', 'leaf'], ['chain', 'chain'], ['confluence', 'confluence'], ['root', 'root / outlet']];
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-slate-600">
      {items.map(([r, label]) => (
        <span key={r} className="inline-flex items-center gap-1.5">
          <svg width="18" height="18" aria-hidden><NodeShape role={r} x={9} y={9} r={6} fill="#fff" stroke="#334155" /></svg>
          {label}
        </span>
      ))}
    </div>
  );
}

function arrowHead(x1: number, y1: number, x2: number, y2: number, size: number) {
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  const bx = x2 - ux * size, by = y2 - uy * size;
  return `${x2},${y2} ${bx - uy * size * 0.55},${by + ux * size * 0.55} ${bx + uy * size * 0.55},${by - ux * size * 0.55}`;
}

export function Arrow({ x1, y1, x2, y2, color, width = 2, head = 7, dashed }: {
  x1: number; y1: number; x2: number; y2: number; color: string; width?: number; head?: number; dashed?: boolean;
}) {
  const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
  const ex = x2 - (dx / len) * head * 0.8, ey = y2 - (dy / len) * head * 0.8;
  return (
    <g>
      <line x1={x1} y1={y1} x2={ex} y2={ey} stroke={color} strokeWidth={width} strokeDasharray={dashed ? '4 3' : undefined} />
      <polygon points={arrowHead(x1, y1, x2, y2, head)} fill={color} />
    </g>
  );
}

// ── the map: grid cells, letters, D8 arrows ───────────────────────────────────
export function GridView({
  m, size = 56, selected, onCell, path, subtree, showFa, label, extra,
}: {
  m: TreeModel;
  size?: number;
  selected?: number | null;          // flat index
  onCell?: (flat: number, button: number) => void;
  path?: Set<number>;                // flat cells drawn as the path to the outlet
  subtree?: Set<number>;             // flat cells drawn as the upstream area
  showFa?: boolean;
  label?: (flat: number) => React.ReactNode;
  extra?: (flat: number, x: number, y: number, s: number) => React.ReactNode;
}) {
  const { ny, nx } = m;
  const lo = Math.min(...m.filled), hi = Math.max(...m.filled);
  const W = nx * size, H = ny * size;
  const ctr = (f: number) => [(f % nx + 0.5) * size, (Math.floor(f / nx) + 0.5) * size];
  return (
    <svg viewBox={`-2 -2 ${W + 4} ${H + 4}`} className="w-full h-auto select-none" role="img"
      aria-label={`Elevation grid, ${ny} by ${nx} cells, with D8 flow arrows`}
      onContextMenu={(e) => e.preventDefault()}>
      <defs>
        <pattern id="tree-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke="#94a3b8" strokeWidth="1.5" />
        </pattern>
      </defs>
      {m.filled.map((z, f) => {
        const r = Math.floor(f / nx), c = f % nx, active = m.mask[f];
        const raised = m.filled[f] > m.z[f] + 1e-9;
        return (
          <g key={f} onMouseDown={onCell ? (e) => { e.preventDefault(); onCell(f, e.button); } : undefined}
            style={{ cursor: onCell ? 'pointer' : undefined }}>
            <rect x={c * size} y={r * size} width={size} height={size} fill={elevCss(z, lo, hi)}
              stroke="#fff" strokeWidth={1} />
            {!active && <rect x={c * size} y={r * size} width={size} height={size} fill="url(#tree-hatch)" opacity={0.55} />}
            {subtree?.has(f) && <rect x={c * size + 2} y={r * size + 2} width={size - 4} height={size - 4} fill={T.subtree} opacity={0.6} />}
            {raised && <rect x={c * size + 2} y={r * size + 2} width={size - 4} height={size - 4} fill="none" stroke={T.raised} strokeWidth={3} />}
            {selected === f && <rect x={c * size + 1.5} y={r * size + 1.5} width={size - 3} height={size - 3} fill="none" stroke={T.current} strokeWidth={3} />}
            <text x={c * size + 5} y={r * size + 14} fontSize={12} fontWeight={700} fill={active ? '#0f172a' : '#64748b'}>
              {label ? label(f) : cellName(f)}
            </text>
            <text x={(c + 1) * size - 5} y={(r + 1) * size - 5} fontSize={10} textAnchor="end" fill="#334155" fontFamily="monospace">
              {showFa ? `FA ${m.fa[f]}` : `${+z.toFixed(1)}${raised ? '↑' : ''}`}
            </text>
            {extra?.(f, c * size, r * size, size)}
          </g>
        );
      })}
      {/* D8 arrows */}
      {m.order.map((f, i) => {
        const d = m.dsIdx[i];
        const [x1, y1] = ctr(f);
        if (d < 0) {
          return (
            <g key={`a${f}`} pointerEvents="none">
              <NodeShape role="root" x={x1} y={y1} r={10} fill="#fff" stroke={T.ink} strokeWidth={2} />
              <text x={x1} y={y1 + 3.5} fontSize={9} fontWeight={700} textAnchor="middle" fill={T.ink}>out</text>
            </g>
          );
        }
        const [x2, y2] = ctr(m.order[d]);
        const onPath = path?.has(f) && path?.has(m.order[d]);
        return (
          <g key={`a${f}`} pointerEvents="none">
            <Arrow x1={x1 + (x2 - x1) * 0.18} y1={y1 + (y2 - y1) * 0.18} x2={x1 + (x2 - x1) * 0.66} y2={y1 + (y2 - y1) * 0.66}
              color={onPath ? T.path : T.edge} width={onPath ? 3.5 : 2} />
          </g>
        );
      })}
    </svg>
  );
}

// ── the same cells as a tree ─────────────────────────────────────────────────
export function TreeView({
  m, selected, onNode, path, subtree, nodeText, nodeFill, nodeStroke, edgeLabel, height, rowGap = 50, compact,
}: {
  m: TreeModel;
  selected?: number | null;                     // flat index
  onNode?: (flat: number) => void;
  path?: Set<number>;
  subtree?: Set<number>;
  nodeText?: (pos: number) => React.ReactNode;  // text under the node
  nodeFill?: (pos: number) => string | undefined;
  nodeStroke?: (pos: number) => string | undefined;
  edgeLabel?: (pos: number) => React.ReactNode;  // on the edge pos → dsIdx[pos]
  height?: number;
  rowGap?: number;
  compact?: boolean;
}) {
  const lay = treeLayout(m.dsIdx, (p) => m.order[p] % m.nx);
  const slotW = compact ? 42 : 36, r = compact ? 10 : 12, pad = 24;
  const W = Math.max(lay.slots * slotW + 2 * pad, 200);
  const H = height ?? (lay.maxDepth + 1) * rowGap + 2 * pad + (nodeText ? 10 : 0);
  const px = (p: number) => pad + lay.x[p] * slotW + slotW / 2;
  const py = (p: number) => H - pad - (nodeText ? 10 : 0) - lay.depth[p] * rowGap;
  const rl = roles(m);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto select-none" role="img"
      aria-label={`The same ${m.order.length} cells drawn as a tree: outlets at the bottom, headwaters at the top`}>
      {m.dsIdx.map((d, p) => {
        if (d < 0) return null;
        const on = path?.has(m.order[p]) && path?.has(m.order[d]);
        const x1 = px(p), y1 = py(p), x2 = px(d), y2 = py(d);
        const len = Math.hypot(x2 - x1, y2 - y1) || 1;
        const k = (r + 3) / len;
        return (
          <g key={`e${p}`}>
            <Arrow x1={x1 + (x2 - x1) * k} y1={y1 + (y2 - y1) * k} x2={x2 - (x2 - x1) * k * 1.15} y2={y2 - (y2 - y1) * k * 1.15}
              color={on ? T.path : T.edgeSoft} width={on ? 3 : 1.6} head={6} />
            {edgeLabel && (
              <text x={(x1 + x2) / 2 + 4} y={(y1 + y2) / 2} fontSize={10} fill={T.ink} fontFamily="monospace">{edgeLabel(p)}</text>
            )}
          </g>
        );
      })}
      {m.order.map((f, p) => {
        const sel = selected === f;
        const fill = nodeFill?.(p) ?? (subtree?.has(f) ? T.subtree : '#fff');
        const stroke = nodeStroke?.(p) ?? (sel ? T.current : path?.has(f) ? T.path : '#334155');
        return (
          <g key={`n${f}`} onClick={onNode ? () => onNode(f) : undefined} style={{ cursor: onNode ? 'pointer' : undefined }}>
            <NodeShape role={rl[p]} x={px(p)} y={py(p)} r={r} fill={fill} stroke={stroke} strokeWidth={sel ? 3.5 : path?.has(f) ? 2.5 : 1.5} />
            <text x={px(p)} y={py(p) + 4} fontSize={compact ? 10 : 11} fontWeight={700} textAnchor="middle" fill="#0f172a">{cellName(f)}</text>
            {nodeText && <text x={px(p)} y={py(p) + r + 12} fontSize={9.5} textAnchor="middle" fill="#334155" fontFamily="monospace">{nodeText(p)}</text>}
          </g>
        );
      })}
    </svg>
  );
}

/** Flat cells on the way from `flat` to its outlet (inclusive). */
export function pathToOutlet(m: TreeModel, flat: number): Set<number> {
  const s = new Set<number>();
  let p = m.pos[flat];
  while (p >= 0) { s.add(m.order[p]); p = m.dsIdx[p]; }
  return s;
}
/** Flat cells upstream of `flat` (its watershed, itself included). */
export function upstreamOf(m: TreeModel, flat: number): Set<number> {
  const kids = childrenOf(m.dsIdx), s = new Set<number>();
  const p0 = m.pos[flat];
  if (p0 < 0) return s;
  const st = [p0];
  while (st.length) { const p = st.pop()!; s.add(m.order[p]); st.push(...kids[p]); }
  return s;
}

export const d8Label = (code: number) => (D8_NAME[code] ? `${D8_NAME[code]} (${code})` : 'none (0)');

export function PresetButtons({ value, onChange, keys = MAIN_PRESETS as readonly string[] }: {
  value: string; onChange: (k: string) => void; keys?: readonly string[];
}) {
  return (
    <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Terrain">
      {keys.map((k) => (
        <button key={k} role="radio" aria-checked={value === k} onClick={() => onChange(k)}
          className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${value === k
            ? 'bg-sky-700 text-white border-sky-700' : 'bg-white text-slate-600 border-slate-300 hover:bg-sky-50'}`}>
          {PRESETS[k].label}
        </button>
      ))}
    </div>
  );
}

export function Btn({ onClick, children, primary, disabled }: {
  onClick: () => void; children: React.ReactNode; primary?: boolean; disabled?: boolean;
}) {
  return (
    <button onClick={onClick} disabled={disabled}
      className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors disabled:opacity-40 ${primary
        ? 'bg-sky-700 text-white border-sky-700 hover:bg-sky-800' : 'bg-white text-slate-700 border-slate-300 hover:bg-slate-50'}`}>
      {children}
    </button>
  );
}
